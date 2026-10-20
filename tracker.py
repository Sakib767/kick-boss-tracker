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

# keywords.txt থেকে তোমার দেওয়া কীওয়ার্ডগুলো পড়া
try:
    with open("keywords.txt", "r") as f:
        ALL_KEYWORDS = [line.strip().upper() for line in f.readlines() if line.strip()]
except FileNotFoundError:
    ALL_KEYWORDS = ["BONUS BUY ($100)", "STAKE CASH $50", "$100 IN BTC", "$200 IN BTC", "STAKE CASH $100", "PICK YOUR CARD"]

# কীওয়ার্ডগুলোকে দুই ভাগে ভাগ করা হচ্ছে
LEFT_KEYWORDS = [kw for kw in ALL_KEYWORDS if kw != "PICK YOUR CARD"]
CENTER_KEYWORDS = ["PICK YOUR CARD"]

SCAN_DURATION = 18000   # ৫ ঘণ্টা
SCAN_INTERVAL = 10      # প্রতি ১০ সেকেন্ড পর পর স্ক্যান হবে

def get_stream_url():
    ydl_opts = {
        "quiet": True, 
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best", 
        "noplaylist": True, 
        "live_from_start": False
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

def process_region(region):
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, gray = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    return pytesseract.image_to_string(gray).upper()

def send_alert(keyword, frame):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    # ছবির কোয়ালিটি ১০০% (High Res)
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 100]
    _, buffer = cv2.imencode('.jpg', frame, encode_param)
    
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
        r = requests.post(url, data=payload, files=files, timeout=20)
        print(f"[SENT] {keyword} -> HTTP {r.status_code}", flush=True)
    except Exception as e:
        print(f"[ERR] Telegram photo failed: {e}", flush=True)
    
    time.sleep(2)

def main():
    print(f"Target: {KICK_URL}", flush=True)
    print(f"Left Keywords: {LEFT_KEYWORDS}", flush=True)
    print(f"Center Keywords: {CENTER_KEYWORDS}", flush=True)
    
    end_time = time.time() + SCAN_DURATION
    found_already = set()
    iteration = 0
    stream_url = None

    print(f"Starting 5-hour scan loop (Interval: {SCAN_INTERVAL}s)...", flush=True)
    
    while time.time() < end_time:
        iteration += 1
        try:
            if not stream_url:
                try:
                    stream_url = get_stream_url()
                    print(f"[{iteration}] ✅ Stream is Online! High-Res URL Got.", flush=True)
                except Exception as e:
                    print(f"[{iteration}] 🔴 Stream is Offline. Waiting 5 mins...", flush=True)
                    time.sleep(300) 
                    continue

            frame = grab_frame(stream_url)
            if frame is None:
                stream_url = None 
                time.sleep(10)
                continue
            
            h, w = frame.shape[:2]
            
            # ১. বাঁ দিকের নিচের অংশ
            left_region = frame[int(h * 0.55):int(h * 0.95), : int(w * 0.25)]
            left_text = process_region(left_region)
            
            # ২. মাঝখানের অংশ
            center_region = frame[int(h * 0.05):int(h * 0.60), int(w * 0.25):int(w * 0.75)]
            center_text = process_region(center_region)
            
            safe_left = left_text.replace('\n', ' ')[:30]
            safe_center = center_text.replace('\n', ' ')[:30]
            print(f"[{iteration}] L: {safe_left} | C: {safe_center}", flush=True)
            
            # বাঁ দিকের কীওয়ার্ড চেক
            for kw in LEFT_KEYWORDS:
                if kw in left_text and kw not in found_already:
                    print(f"[{iteration}] 🚨 HIT (Left): {kw}", flush=True)
                    send_alert(kw, frame) 
                    found_already.add(kw)
            
            # মাঝখানের কীওয়ার্ড চেক
            for kw in CENTER_KEYWORDS:
                if kw in center_text and kw not in found_already:
                    print(f"[{iteration}] 🚨 HIT (Center): {kw}", flush=True)
                    send_alert(kw, frame) 
                    found_already.add(kw)
            
        except Exception as e:
            print(f"[{iteration}] Error: {e}", flush=True)
            stream_url = None
            time.sleep(10)
            
        time.sleep(SCAN_INTERVAL)

    print(f"✅ Scan completed for this 5-hour run.", flush=True)

if __name__ == "__main__":
    main()
