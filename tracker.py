import cv2
import yt_dlp
import pytesseract
import requests
import os
import time
import io
import re
from datetime import datetime

# গোপন তথ্যগুলো
KICK_URL = os.environ.get("KICK_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
KICK_CURL = os.environ.get("KICK_CURL", "") 

SCAN_DURATION = 18000   # ৫ ঘণ্টা
SCAN_INTERVAL = 10      # প্রতি ১০ সেকেন্ড পর পর স্ক্যান
HEARTBEAT_INTERVAL = 60 # প্রতি ৬০ সেকেন্ড (১ মিনিট) পর পর স্ট্যাটাস ছবি

def parse_curl(curl_string):
    headers = {}
    if not curl_string:
        return headers
    cookie_match = re.search(r"-H\s+['\"]cookie:\s*(.*?)['\"]", curl_string, re.IGNORECASE)
    if cookie_match:
        headers["Cookie"] = cookie_match.group(1)
    else:
        if "curl" not in curl_string.lower():
            headers["Cookie"] = curl_string.strip()
    ua_match = re.search(r"-H\s+['\"]user-agent:\s*(.*?)['\"]", curl_string, re.IGNORECASE)
    if ua_match:
        headers["User-Agent"] = ua_match.group(1)
    else:
        headers["User-Agent"] = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36"
    return headers

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text} 
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[ERR] Message failed: {e}", flush=True)

def get_stream_url(headers):
    ydl_opts = {
        "quiet": True, 
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best", 
        "noplaylist": True, 
        "live_from_start": False
    }
    if headers:
        ydl_opts["http_headers"] = headers
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

def send_telegram_photo(frame, caption, box_coords=None, keyword=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    if box_coords and keyword:
        x, y, w, h = box_coords
        pad = 5
        cv2.rectangle(frame, (max(0, x-pad), max(0, y-pad)), (x + w + pad, y + h + pad), (0, 255, 0), 2) 
        cv2.putText(frame, f"Matched: {keyword}", (max(0, x-pad), max(0, y - 15)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2) 

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(frame, f"Time: {current_time}", (20, frame.shape[0] - 20), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 100]
    _, buffer = cv2.imencode('.jpg', frame, encode_param)
    photo_bytes = io.BytesIO(buffer)
    photo_bytes.seek(0)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
    files = {"photo": ("screenshot.jpg", photo_bytes, "image/jpeg")}
    
    try:
        r = requests.post(url, data=payload, files=files, timeout=20)
        if r.status_code == 200:
            print(f"[SENT] Photo -> OK", flush=True)
        else:
            print(f"[ERR] Telegram rejected photo! Reason: {r.text}", flush=True)
    except Exception as e:
        print(f"[ERR] Photo failed: {e}", flush=True)
    time.sleep(2)

def find_keyword_box(keyword, words_data):
    kw_parts = keyword.split()
    for i in range(len(words_data)):
        match = True
        for j, part in enumerate(kw_parts):
            if i + j >= len(words_data) or part not in words_data[i+j]['text']:
                match = False
                break
        if match:
            x_min = min(words_data[i+k]['left'] for k in range(len(kw_parts)))
            y_min = min(words_data[i+k]['top'] for k in range(len(kw_parts)))
            x_max = max(words_data[i+k]['left'] + words_data[i+k]['width'] for k in range(len(kw_parts)))
            y_max = max(words_data[i+k]['top'] + words_data[i+k]['height'] for k in range(len(kw_parts)))
            return (x_min, y_min, x_max - x_min, y_max - y_min)
    return None

def main():
    headers = parse_curl(KICK_CURL)
    cookie_status = "Loaded" if "Cookie" in headers else "Not Found (Guest)"
    
    print(f"Target: {KICK_URL}", flush=True)
    print(f"Cookie Status: {cookie_status}", flush=True)
    
    send_telegram_message(f"✅ Bot Started!\nCookie Status: {cookie_status}\nTracking has begun.")
    
    # কীওয়ার্ড লোড করা
    try:
        with open("keywords.txt", "r") as f:
            ALL_KEYWORDS = [line.strip().upper() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        ALL_KEYWORDS = ["BONUS BUY ($100)", "STAKE CASH $50", "$100 IN BTC", "$200 IN BTC", "STAKE CASH $100", "PICK YOUR CARD"]

    # 👇 "PICK YOUR CARD" কে আলাদা করা হলো ২ মিনিটের কুলডাউনের জন্য
    TARGET_CARD_KEYWORD = "PICK YOUR CARD"
    # বাকি কীওয়ার্ডগুলো যেগুলো ১ বারই ধরবে
    OTHER_KEYWORDS = [kw for kw in ALL_KEYWORDS if kw != TARGET_CARD_KEYWORD]

    end_time = time.time() + SCAN_DURATION
    found_already = set() # বাকি কীওয়ার্ডগুলোর জন্য মেমোরি
    iteration = 0
    stream_url = None
    last_heartbeat_time = time.time()
    
    # 👇 PICK YOUR CARD এর কুলডাউন টাইমার (শুরুতে ০ করে দেওয়া হলো)
    last_card_alert_time = 0 

    print(f"Starting Scan Loop...", flush=True)
    
    while time.time() < end_time:
        iteration += 1
        try:
            if not stream_url:
                try:
                    stream_url = get_stream_url(headers)
                    print(f"[{iteration}] ✅ Stream is Online!", flush=True)
                except Exception as e:
                    print(f"[{iteration}] 🔴 Stream is Offline or Error. Waiting 5 mins...", flush=True)
                    time.sleep(300) 
                    continue

            frame = grab_frame(stream_url)
            if frame is None:
                stream_url = None 
                time.sleep(10)
                continue
            
            h, w = frame.shape[:2]
            crop_w = int(w * 0.78) 
            game_area = frame[:, 0:crop_w] 
            
            gray = cv2.cvtColor(game_area, cv2.COLOR_BGR2GRAY)
            data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
            
            words_data = []
            for i in range(len(data['text'])):
                word = data['text'][i].strip().upper()
                if word and int(data['conf'][i]) > 20:
                    words_data.append({
                        'text': word,
                        'left': data['left'][i],
                        'top': data['top'][i],
                        'width': data['width'][i],
                        'height': data['height'][i]
                    })
            
            full_text = " ".join([wd['text'] for wd in words_data])
            current_time = time.time()
            
            # 👇 ১. "PICK YOUR CARD" এর জন্য আলাদা চেক (২ মিনিটের কুলডাউন)
            if TARGET_CARD_KEYWORD in full_text:
                # যদি ২ মিনিট (১২০ সেকেন্ড) পার হয়ে যায়
                if current_time - last_card_alert_time >= 120:
                    print(f"[{iteration}] 🚨 HIT (Card): {TARGET_CARD_KEYWORD}", flush=True)
                    match_box = find_keyword_box(TARGET_CARD_KEYWORD, words_data)
                    caption = f"🚨 Kick Alert!\nDetected: {TARGET_CARD_KEYWORD}\nChannel: {KICK_URL}"
                    send_telegram_photo(frame.copy(), caption, match_box, TARGET_CARD_KEYWORD) 
                    # টাইমার রিসেট করা হলো
                    last_card_alert_time = current_time
                else:
                    print(f"[{iteration}] ⏭️ Skipping '{TARGET_CARD_KEYWORD}' (Cooldown active)...", flush=True)

            # 👇 ২. বাকি কীওয়ার্ডগুলোর জন্য চেক (রানে একবারই)
            for kw in OTHER_KEYWORDS:
                if kw in full_text and kw not in found_already:
                    print(f"[{iteration}] 🚨 HIT: {kw}", flush=True)
                    match_box = find_keyword_box(kw, words_data)
                    caption = f"🚨 Kick Alert!\nDetected: {kw}\nChannel: {KICK_URL}"
                    send_telegram_photo(frame.copy(), caption, match_box, kw) 
                    found_already.add(kw)
                    break
            
            # ১ মিনিটের Heartbeat
            if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                caption = f"⏱️ Status Update\nNo new match found yet.\nChannel: {KICK_URL}"
                send_telegram_photo(frame.copy(), caption)
                last_heartbeat_time = current_time
            
        except Exception as e:
            print(f"[{iteration}] Error: {e}", flush=True)
            stream_url = None
            time.sleep(10)
            
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
