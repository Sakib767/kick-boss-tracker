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
KICK_URL = "https://kick.com/classybeef" # 👈 সরাসরি লিংক বসানো হলো
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# পার্সোনাল এবং গ্রুপের Chat ID
TELEGRAM_CHAT_IDS = [
    "8949091966",        # তোমার পার্সোনাল Chat ID
    "-1004493539395"     # গ্রুপের Chat ID
]

SCAN_DURATION = 17000   # ৫ ঘণ্টার একটু কম (GitHub Actions টাইমআউট এড়াতে)
SCAN_INTERVAL = 10      # প্রতি ১০ সেকেন্ড পর পর স্ক্যান
HEARTBEAT_INTERVAL = 1800 # প্রতি ৩০ মিনিট পর পর স্ট্যাটাস ছবি
CENTER_COOLDOWN = 120   # আসল অ্যালার্টের জন্য ২ মিনিট

# ডিবাগ টাইমার (USERNAME দেখলে ছবি পাঠানোর জন্য)
DEBUG_COOLDOWN = 60 
last_debug_time = 0

# 👇 স্ক্রিপ্ট শেষ হওয়ার ১ মিনিট আগে মেসেজ পাঠানোর জন্য ভেরিয়েবল
END_WARNING_SENT = False

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

def get_stream_url():
    # ডিরেক্ট টেস্ট করার জন্য yt-dlp-কে বলছি সব ডিটেইল দেখাতে
    ydl_opts = {
        "quiet": False,         # 👈 False করায় এখন স্ক্রিনে সব ডিটেইল আসবে
        "verbose": True,        # 👈 True করায় গভীরভাবে চেক করবে
        "format": "best", 
        "noplaylist": True, 
        "live_from_start": False,
        "impersonate": "chrome",
        "nocheckcertificate": True,
        "extractor_args": {
            "kick": {
                "api": ["v2", "v1"], 
                "client": ["web", "android"] 
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(KICK_URL, download=False)
        
        # যদি স্ট্রিম অফলাইন থাকে, info None হতে পারে
        if not info:
            raise Exception("No info returned (Channel might be offline)")
            
        if 'url' in info:
            return info['url']
        elif 'formats' in info and len(info['formats']) > 0:
            return info['formats'][-1]['url']
        elif 'requested_formats' in info:
            return info['requested_formats'][0]['url']
        else:
            raise Exception("Stream is offline or no formats found.")

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

def process_center_ocr(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_white = (0, 0, 180)
    upper_white = (180, 50, 255)
    mask = cv2.inRange(hsv, lower_white, upper_white)
    mask = cv2.bitwise_not(mask)
    mask = cv2.resize(mask, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    
    text = pytesseract.image_to_string(mask, config='--psm 6').upper()
    
    data = pytesseract.image_to_data(mask, output_type=pytesseract.Output.DICT)
    words_data = []
    for i in range(len(data['text'])):
        word = data['text'][i].strip().upper()
        if word and int(data['conf'][i]) > 10:
            words_data.append({
                'text': word,
                'left': int(data['left'][i] / 3.0),
                'top': int(data['top'][i] / 3.0),
                'width': int(data['width'][i] / 3.0),
                'height': int(data['height'][i] / 3.0)
            })
    return text, words_data

def process_side_ocr(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
    words_data = []
    for i in range(len(data['text'])):
        word = data['text'][i].strip().upper()
        if word and int(data['conf'][i]) > 15:
            words_data.append({
                'text': word,
                'left': int(data['left'][i] / 2.0),
                'top': int(data['top'][i] / 2.0),
                'width': int(data['width'][i] / 2.0),
                'height': int(data['height'][i] / 2.0)
            })
    return " ".join([wd['text'] for wd in words_data]), words_data

def main():
    global last_debug_time, END_WARNING_SENT
    
    print(f"Target: {KICK_URL}", flush=True)
    send_telegram_message(f"✅ Bot Started!\nStatus: Public/Guest Mode")
    
    try:
        with open("keywords.txt", "r") as f:
            OTHER_KEYWORDS = [line.strip().upper() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        OTHER_KEYWORDS = ["BONUS BUY", "STAKE CASH", "BTC"]
        
    OTHER_KEYWORDS = [kw for kw in OTHER_KEYWORDS if "PICK YOUR CARD" not in kw]

    end_time = time.time() + SCAN_DURATION
    iteration = 0
    stream_url = None
    last_heartbeat_time = time.time()
    
    last_center_alert_time = 0
    last_side_keyword = ""

    print(f"Starting Scan Loop...", flush=True)
    
    while time.time() < end_time:
        iteration += 1
        try:
            if not stream_url:
                try:
                    stream_url = get_stream_url()
                    print(f"[{iteration}] ✅ Stream is Online!", flush=True)
                except Exception as e:
                    # 👇 এখানেই এবার ডিটেইল এরর প্রিন্ট হবে
                    print(f"[{iteration}] 🔴 Stream is Offline or Error: {str(e)}", flush=True)
                    time.sleep(300) 
                    continue

            frame = grab_frame(stream_url)
            if frame is None:
                stream_url = None 
                time.sleep(10)
                continue
            
            h, w = frame.shape[:2]
            current_time = time.time()
            
            time_left = end_time - current_time
            if time_left <= 60 and not END_WARNING_SENT:
                print(f"[{iteration}] ⏰ Sending '1 minute left' warning...", flush=True)
                send_telegram_message(f"⏰ **Warning!**\nThe bot will stop in 1 minute.\nNew run will start soon via cron.\nChannel: {KICK_URL}")
                END_WARNING_SENT = True
            
            # ---------------------------------------------------------
            # ১. মাঝখানের অংশ চেক 
            # ---------------------------------------------------------
            center_y1, center_y2 = int(h * 0.20), int(h * 0.60)
            center_x1, center_x2 = int(w * 0.28), int(w * 0.72)
            center_image = frame[center_y1:center_y2, center_x1:center_x2]
            
            center_text, center_words = process_center_ocr(center_image)
            
            safe_center = center_text.replace('\n', ' ')[:60]
            print(f"[{iteration}] Center OCR: {safe_center}...", flush=True)
            
            has_enter = "ENTER" in center_text or "ENT" in center_text
            has_your = "YOUR" in center_text or "YUR" in center_text or "Y0UR" in center_text or "YOU" in center_text
            has_stake = "STAKE" in center_text or "5TAKE" in center_text or "STAKE.COM" in center_text
            has_username = "USERNAME" in center_text or "USERNANE" in center_text or "USER" in center_text or "USRNME" in center_text

            if has_enter and has_your and has_stake and has_username:
                if current_time - last_center_alert_time >= CENTER_COOLDOWN:
                    print(f"[{iteration}] 🚨 HIT (Center): ENTER YOUR STAKE USERNAME", flush=True)
                    match_box = find_keyword_box("ENTER", center_words, offset_x=center_x1, offset_y=center_y1)
                    
                    caption = f"🚨 Kick Alert!\nDetected: ENTER YOUR STAKE USERNAME\nChannel: {KICK_URL}"
                    send_telegram_photo(frame.copy(), caption, match_box, "ENTER YOUR STAKE USERNAME") 
                    last_center_alert_time = current_time
            
            elif has_username:
                if current_time - last_debug_time >= DEBUG_COOLDOWN:
                    print(f"[{iteration}] 🔍 DEBUG HIT: Missing 4-word match", flush=True)
                    
                    debug_caption = f"🔍 **DEBUG: Missing Words**\n\nBot Read: `{center_text[:100]}`\nChannel: {KICK_URL}"
                    
                    match_box = find_keyword_box("USER", center_words, offset_x=center_x1, offset_y=center_y1)
                    send_telegram_photo(frame.copy(), debug_caption, match_box, "DEBUG: MISSING WORDS")
                    
                    last_debug_time = current_time

            # ---------------------------------------------------------
            # ২. বাঁ দিকের অংশ চেক (keywords.txt)
            # ---------------------------------------------------------
            side_y1 = int(h * 0.45) 
            side_y2 = int(h * 0.90) 
            side_x1 = 0
            side_x2 = int(w * 0.35) 
            
            game_area = frame[side_y1:side_y2, side_x1:side_x2] 
            game_text, game_words = process_side_ocr(game_area)
            
            safe_side = game_text[:60]
            print(f"[{iteration}] Side OCR: {safe_side}...", flush=True)
            
            current_side_keyword = ""
            current_side_box = None
            
            for kw in OTHER_KEYWORDS:
                if kw in game_text:
                    current_side_keyword = kw
                    current_side_box = find_keyword_box(kw, game_words, offset_x=side_x1, offset_y=side_y1)
                    break 
            
            if current_side_keyword and current_side_keyword != last_side_keyword:
                print(f"[{iteration}] 🚨 NEW SIDE HIT: {current_side_keyword}", flush=True)
                caption = f"🚨 Kick Alert!\nDetected: {current_side_keyword}\nChannel: {KICK_URL}"
                send_telegram_photo(frame.copy(), caption, current_side_box, current_side_keyword) 
                last_side_keyword = current_side_keyword

            elif current_side_keyword and current_side_keyword == last_side_keyword:
                print(f"[{iteration}] ⏭️ Skipping same side keyword: {current_side_keyword}", flush=True)
            
            # ---------------------------------------------------------
            # ৩. ৩০ মিনিট পর পর স্ট্যাটাস ছবি (Heartbeat)
            # ---------------------------------------------------------
            if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                print(f"[{iteration}] ⏱️ Sending 30-min heartbeat screenshot...", flush=True)
                caption = f"⏱️ Status Update (30 min)\nScanning...\nLast Side Match: {last_side_keyword if last_side_keyword else 'None'}\nChannel: {KICK_URL}"
                send_telegram_photo(frame.copy(), caption)
                last_heartbeat_time = current_time
            
        except Exception as e:
            print(f"[{iteration}] Error: {e}", flush=True)
            stream_url = None
            time.sleep(10)
            
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
