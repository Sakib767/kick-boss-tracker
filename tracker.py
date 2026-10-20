import cv2
import yt_dlp
import pytesseract
import requests
import os
import time

# গোপন তথ্যগুলো GitHub Secrets থেকে অটোমেটিক আসবে
KICK_URL = os.environ.get("KICK_URL", "")
WEBHOOK = os.environ.get("RENDER_WEBHOOK", "")
KEYWORDS = ["TICKET", "BTC", "STAKE CASH", "WHEEL"]

# ৩০ মিনিট = ১৮০০ সেকেন্ড
SCAN_DURATION = 1800   
SCAN_INTERVAL = 15     # প্রতি ১৫ সেকেন্ড পর পর ফ্রেম নেবে

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
    # লাইভ এজে পৌঁছাতে কয়েকটা ফ্রেম ডিসকার্ড করি
    for _ in range(10):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None

def ocr_regions(frame):
    """বাঁ সাইডবার এবং মাঝের অংশ থেকে টেক্সট বের করে।"""
    h, w = frame.shape[:2]
    regions = [
        frame[:, : int(w * 0.22)],                      # বাঁ সাইডবার
        frame[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)],  # মাঝের popup
    ]
    texts = []
    for region in regions:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        text = pytesseract.image_to_string(gray).upper()
        texts.append(text)
    return " ".join(texts)

def send_alert(keyword):
    try:
        r = requests.post(
            WEBHOOK,
            json={"action": "giveaway_detected", "text": keyword},
            timeout=10,
        )
        print(f"[SENT] {keyword} -> HTTP {r.status_code}")
    except Exception as e:
        print(f"[ERR] Webhook failed: {e}")

def main():
    print(f"Target Channel: {KICK_URL}")
    if not KICK_URL or not WEBHOOK:
        print("ERROR: KICK_URL or RENDER_WEBHOOK env missing! Check GitHub Secrets.")
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
                    send_alert(kw)
                    found_already.add(kw)
            
            if iteration % 4 == 0:
                print(f"[{iteration}] Scanned... (No new hits)")
                
        except Exception as e:
            print(f"[{iteration}] Error during scan: {e}")
            
        time.sleep(SCAN_INTERVAL)

    print(f"✅ Scan completed. Total checks: {iteration}, Hits: {found_already}")

if __name__ == "__main__":
    main()
