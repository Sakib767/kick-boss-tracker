import cv2
import yt_dlp
import pytesseract
import requests
import os
import time
import io

# গোপন তথ্যগুলো GitHub Secrets থেকে অটোমেটিক আসবে
KICK_URL = os.environ.get("KICK_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# টেস্ট করার জন্য "USE CODE" এবং "CLASSYBEEF" যোগ করা হলো
KEYWORDS = ["TICKET", "BTC", "STAKE CASH", "WHEEL", "USE CODE", "CLASSYBEEF"]

# ৩০ মিনিট = ১৮০০ সেকেন্ড
SCAN_DURATION = 1800   
SCAN_INTERVAL = 15     

def get_stream_url():
    ydl_opts = {
        "quiet": True,
        "format": "worst",
        "noplaylist": True,
        "live_from_start": False,
    }
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
    """বাঁ সাইডবার, মাঝের পপআপ এবং ডান দিকের অংশ স্ক্যান করবে।"""
    h, w = frame.shape[:2]
    regions = [
        frame[:, : int(w * 0.22)],                      # ১. বাঁ সাইডবার
        frame[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)],  # ২. মাঝের popup
        frame[int(h * 0.10):int(h * 0.50), int(w * 0.75):], # ৩. ডান দিকের বোনাস/কোড বক্স (নতুন)
    ]
    texts = []
    for region in regions:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        # OCR আরও ভালো করার জন্য ছবিটা বড় এবং কনট্রাস্ট বাড়ানো হলো
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        _, gray = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        text = pytesseract.image_to_string(gray).upper()
        texts.append(text)
    return " ".join(texts)

def send_alert(keyword, frame):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram token or chat ID missing!")
        return

    _, buffer = cv2.imencode('.jpg', frame)
    photo_bytes = io.BytesIO(buffer)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": f"🚨 **Kick Alert!**\nDetected: {keyword}\nChannel: {KICK_URL}",
        "parse_mode": "Markdown"
    }
    
    files = {
        "photo": ("screenshot.jpg", photo_bytes, "image/jpeg")
    }
    
    try:
        r = requests.post(url, data=payload, files=files, timeout=15)
        print(f"[SENT] {keyword} screenshot -> HTTP {r.status_code}")
    except Exception as e:
        print(f"[ERR] Telegram photo failed: {e}")

def main():
    print(f"Target Channel: {KICK_URL}")
    if not KICK_URL:
        print("ERROR: KICK_URL missing! Check GitHub Secrets.")
        return

    try:
        stream_url = get_stream_url()
        print("Successfully got stream URL.")
    except Exception as e:
        print(f"[ERR] yt-dlp failed: {e}")
        return

    end_time = time.time() + SCAN_DURATION
    found_already = set()
    iteration = 0

    print(f"Starting {SCAN_DURATION//60} minutes scan loop...")
    
    while time.time() < end_time:
        iteration += 1
        try:
            frame = grab_frame(stream_url)
            if frame is None:
                print(f"[{iteration}] No frame grabbed, retrying...")
                time.sleep(SCAN_INTERVAL)
                continue
            
            text = ocr_regions(frame)
            for kw in KEYWORDS:
                if kw in text and kw not in found_already:
                    print(f"[{iteration}] 🚨 HIT: {kw}")
                    send_alert(kw, frame) 
                    found_already.add(kw)
            
            if iteration % 4 == 0:
                print(f"[{iteration}] Scanned... (No new hits)")
                
        except Exception as e:
            print(f"[{iteration}] Error during scan: {e}")
            
        time.sleep(SCAN_INTERVAL)

    print(f"✅ Scan completed. Total checks: {iteration}, Hits: {found_already}")

if __name__ == "__main__":
    main()
