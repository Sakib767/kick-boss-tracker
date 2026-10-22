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
KICK_CURL = os.environ.get("KICK_CURL", "") 

# পার্সোনাল এবং গ্রুপের Chat ID
TELEGRAM_CHAT_IDS = [
    "8949091966",        # তোমার পার্সোনাল Chat ID
    "-1004493539395"     # গ্রুপের Chat ID
]

SCAN_DURATION = 18000   # ৫ ঘণ্টা
SCAN_INTERVAL = 10      # প্রতি ১০ সেকেন্ড পর পর স্ক্যান
HEARTBEAT_INTERVAL = 600 # 👈 প্রতি ১০ মিনিট (৬০০ সেকেন্ড) পর পর স্ট্যাটাস ছবি

CENTER_COOLDOWN = 120   # ২ মিনিট (শুধু Stake.com Username এর জন্য)
OTHER_COOLDOWN = 600    # ১০ মিনিট (বাকি সব কীওয়ার্ডের জন্য)

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
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {"chat_id": chat_id, "text": text} 
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"[ERR] Message failed to {chat_id}: {e}", flush=True)

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
    if not TELEGRAM_BOT_TOKEN:
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
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    
    for chat_id in TELEGRAM_CHAT_IDS:
        photo_bytes = io.BytesIO(buffer)
        photo_bytes.seek(0)
        payload = {"chat_id": chat_id, "caption": caption}
        files = {"photo": ("screenshot.jpg", photo_bytes, "image/jpeg")}
        
        try:
            r = requests.post(url, data=payload, files=files, timeout=20)
            if r.status_code == 200:
                print(f"[SENT] Photo to {chat_id} -> OK", flush=True)
            else:
                print(f"[ERR] Telegram rejected photo to {chat_id}! Reason: {r.text}", flush=True)
        except Exception as e:
            print(f"[ERR] Photo failed to {chat_id}: {e}", flush=True)
            
    time.sleep(2)

def find_keyword_box(keyword, words_data, offset_x=0, offset_y=0):
    kw_parts = keyword.split()
    for i in range(len(words_data)):
        match = True
        for j, part in enumerate(kw_parts):
            if i + j >= len(words_data) or part not in words_data[i+j]['text']:
                match = False
                break
        if match:
            x_min = min(words_data[i+k]['left'] for k in range(len(kw_parts))) + offset_x
            y_min = min(words_data[i+k]['top'] for k in range(len(kw_parts))) + offset_y
            x_max = max(words_data[i+k]['left'] + words_data[i+k]['width'] for k in range(len(kw_parts))) + offset_x
            y_max = max(words_data[i+k]['top'] + words_data[i+k]['height'] for k in range(len(kw_parts))) + offset_y
            return (x_min, y_min, x_max - x_min, y_max - y_min)
    return None

def process_ocr(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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
    return " ".join([wd['text'] for wd in words_data]), words_data

def main():
    headers = parse_curl(KICK_CURL)
    cookie_status = "Loaded" if "Cookie" in headers else "Not Found (Guest)"
    
    print(f"Target: {KICK_URL}", flush=True)
    send_telegram_message(f"✅ Bot Started!\nStatus: {cookie_status}")
    
    try:
        with open("keywords.txt", "r") as f:
            OTHER_KEYWORDS = [line.strip().upper() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        OTHER_KEYWORDS = ["BONUS BUY ($100)", "STAKE CASH $50", "$100 IN BTC", "$200 IN BTC", "STAKE CASH $100"]
        
    OTHER_KEYWORDS = [kw for kw in OTHER_KEYWORDS if "PICK YOUR CARD" not in kw]

    end_time = time.time() + SCAN_DURATION
    iteration = 0
    stream_url = None
    last_heartbeat_time = time.time() # 👈 টাইমার শুরু হলো
    last_alert_times = {} 

    print(f"Starting 5-hour Scan Loop...", flush=True)
    
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
            current_time = time.time()
            
            # ১. মাঝখানের অংশ চেক (গিভঅ্যাওয়ে পপআপ)
            center_y1, center_y2 = int(h * 0.15), int(h * 0.65)
            center_x1, center_x2 = int(w * 0.25), int(w * 0.75)
            center_image = frame[center_y1:center_y2, center_x1:center_x2]
            
            center_text, center_words = process_ocr(center_image)
            
            safe_center = center_text[:50]
            print(f"[{iteration}] Center OCR: {safe_center}...", flush=True)
            
            center_match = False
            match_text = ""
            if "STAKE" in center_text and "USERNAME" in center_text:
                center_match = True
                match_text = "STAKE USERNAME"
            elif "STAKE.COM" in center_text:
                center_match = True
                match_text = "STAKE.COM"

            if center_match:
                last_alert = last_alert_times.get("CENTER", 0)
                if current_time - last_alert >= CENTER_COOLDOWN:
                    print(f"[{iteration}] 🚨 HIT (Center): {match_text}", flush=True)
                    match_box = find_keyword_box("STAKE", center_words, offset_x=center_x1, offset_y=center_y1)
                    if not match_box:
                        match_box = find_keyword_box("STAKE.COM", center_words, offset_x=center_x1, offset_y=center_y1)
                        
                    caption = f"🚨 Kick Alert!\nDetected: {match_text}\nChannel: {KICK_URL}"
                    send_telegram_photo(frame.copy(), caption, match_box, match_text) 
                    last_alert_times["CENTER"] = current_time

            # ২. বাকি স্ক্রিন চেক (keywords.txt এর জন্য)
            crop_w = int(w * 0.78) 
            game_area = frame[:, 0:crop_w] 
            game_text, game_words = process_ocr(game_area)
            
            for kw in OTHER_KEYWORDS:
                if kw in game_text:
                    last_alert = last_alert_times.get(kw, 0)
                    if current_time - last_alert >= OTHER_COOLDOWN:
                        print(f"[{iteration}] 🚨 HIT (10min): {kw}", flush=True)
                        match_box = find_keyword_box(kw, game_words)
                        caption = f"🚨 Kick Alert!\nDetected: {kw}\nChannel: {KICK_URL}"
                        send_telegram_photo(frame.copy(), caption, match_box, kw) 
                        last_alert_times[kw] = current_time
                    break 
            
            # ৩. ১০ মিনিট পর পর স্ট্যাটাস ছবি (Heartbeat)
            if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                print(f"[{iteration}] ⏱️ Sending 10-min heartbeat screenshot...", flush=True)
                caption = f"⏱️ Status Update (10 min)\nScanning... No new match yet.\nChannel: {KICK_URL}"
                send_telegram_photo(frame.copy(), caption)
                last_heartbeat_time = current_time
            
        except Exception as e:
            print(f"[{iteration}] Error: {e}", flush=True)
            stream_url = None
            time.sleep(10)
            
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
