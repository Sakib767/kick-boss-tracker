import cv2
import yt_dlp
import pytesseract
import requests
import os
import time
import io

# গোপন তথ্যগুলো
KICK_URL = os.environ.get("KICK_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# keywords.txt থেকে কীওয়ার্ড পড়া
try:
    with open("keywords.txt", "r") as f:
        KEYWORDS = [line.strip().upper() for line in f.readlines() if line.strip()]
except FileNotFoundError:
    KEYWORDS = ["TICKET", "STAKE CASH", "BONUS BUY", "BTC"]

# ৫ ঘণ্টা = ১৮০০০ সেকেন্ড
SCAN_DURATION = 18000   

# প্রতি ১ মিনিট (৬০ সেকেন্ড) পর পর স্ক্যান হবে
SCAN_INTERVAL = 60     

def get_stream_url():
    ydl_opts = {"quiet": True, "format": "best", "noplaylist": True, "live_from_start": False}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(KICK_URL, download=False)
        return info["url"]

def grab_frame(stream_url):
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        return None
    for _ in range(10):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None

def ocr_regions(frame):
    h, w = frame.shape[:2]
    regions = [
        frame[:, : int(w * 0.30)],                      
        frame[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)],  
        frame[int(h * 0.10):int(h * 0.50), int(w * 0.75):], 
    ]
    texts = []
    for region in regions:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        _, gray = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        text = pytesseract.image_to_string(gray).upper()
        texts.append(text)
    return " ".join(texts)

def send_alert(keyword, frame):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram token or chat ID missing!", flush=True)
        return

    _, buffer = cv2.imencode('.jpg', frame)
    photo_bytes = io.BytesIO(buffer)
    photo_bytes.seek(0)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": f"🚨 **Kick Alert!**\nDetected: {keyword}\nChannel: {KICK_URL}",
        "parse_mode": "Markdown"
    }
    files = {"photo": ("screenshot.jpg", photo_bytes, "image/jpeg")}
    
    try:
        r = requests.post(url, data=payload, files=files, timeout=15)
        print(f"[SENT] {keyword} -> HTTP {r.status_code}", flush=True)
    except Exception as e:
        print(f"[ERR] Telegram photo failed: {e}", flush=True)
    
    time.sleep(2) # টেলিগ্রাম ব্লক এড়াতে ২ সেকেন্ড গ্যাপ

def main():
    print(f"Target: {KICK_URL}", flush=True)
    print(f"Keywords: {KEYWORDS}", flush=True)
    
    end_time = time.time() + SCAN_DURATION
    found_already = set()
    iteration = 0
    stream_url = None

    print(f"Starting {SCAN_DURATION//3600} hours scan loop...", flush=True)
    
    while time.time() < end_time:
        iteration += 1
        try:
            # ১. স্ট্রিম লিংক না থাকলে (অফলাইন থাকলে) বের করার চেষ্টা করবে
            if not stream_url:
                try:
                    stream_url = get_stream_url()
                    print(f"[{iteration}] ✅ Stream is Online! Got URL.", flush=True)
                except Exception as e:
                    print(f"[{iteration}] 🔴 Stream is Offline or Error. Waiting 5 mins...", flush=True)
                    time.sleep(300) # ৫ মিনিট অপেক্ষা করবে
                    continue

            # ২. ফ্রেম নেওয়ার চেষ্টা করবে
            frame = grab_frame(stream_url)
            if frame is None:
                print(f"[{iteration}] ⚠️ Frame grab failed (Stream might have gone offline). Refetching URL...", flush=True)
                stream_url = None # লিংক রিসেট করবে
                time.sleep(10)
                continue
            
            # ৩. OCR স্ক্যান
            text = ocr_regions(frame)
            
            for kw in KEYWORDS:
                if kw in text and kw not in found_already:
                    print(f"[{iteration}] 🚨 HIT: {kw}", flush=True)
                    send_alert(kw, frame) 
                    found_already.add(kw)
            
            # প্রতি ১০ বারে একবার লগ দেবে, যাতে লগ স্প্যাম না হয়
            if iteration % 10 == 0 and not any(kw in text for kw in KEYWORDS):
                print(f"[{iteration}] Scanned... (No new hits)", flush=True)
                
        except Exception as e:
            print(f"[{iteration}] Unexpected Error: {e}", flush=True)
            stream_url = None
            time.sleep(10)
            
        time.sleep(SCAN_INTERVAL)

    print(f"✅ Scan completed.", flush=True)

if __name__ == "__main__":
    main()
