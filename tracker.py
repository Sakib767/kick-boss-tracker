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

# keywords.txt থেকে তোমার দেওয়া সব কীওয়ার্ড পড়া
try:
    with open("keywords.txt", "r") as f:
        ALL_KEYWORDS = [line.strip().upper() for line in f.readlines() if line.strip()]
except FileNotFoundError:
    ALL_KEYWORDS = ["BONUS BUY ($100)", "STAKE CASH $50", "$100 IN BTC", "$200 IN BTC", "STAKE CASH $100", "PICK YOUR CARD"]

SCAN_DURATION = 18000   # ৫ ঘণ্টা
SCAN_INTERVAL = 10      # প্রতি ১০ সেকেন্ড পর পর স্ক্যান

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

def send_alert(keyword, frame, box_coords=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    # ছবির উপর সবুজ বক্স আঁকবে
    if box_coords:
        x, y, w, h = box_coords
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 3) 
        cv2.putText(frame, f"Matched: {keyword}", (x, max(y - 10, 30)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2) 

    # ছবির কোয়ালিটি ১০০%
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
    print(f"Keywords: {ALL_KEYWORDS}", flush=True)
    
    end_time = time.time() + SCAN_DURATION
    found_already = set()
    iteration = 0
    stream_url = None

    print(f"Starting Game-Only Scan (Chat Box Excluded)...", flush=True)
    
    while time.time() < end_time:
        iteration += 1
        try:
            if not stream_url:
                try:
                    stream_url = get_stream_url()
                    print(f"[{iteration}] ✅ Stream is Online!", flush=True)
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
            
            # 👇 এখানে তোমার দেওয়া লাল দাগ বরাবর কাটা হচ্ছে (ডান দিকের ২২% বাদ)
            crop_w = int(w * 0.78)
            game_area = frame[:, 0:crop_w]  # পুরো উচ্চতা নিচ্ছে, কিন্তু ডান দিক বাদ দিচ্ছে
            
            # গেমের অংশটা গ্রে-স্কেল করা
            gray = cv2.cvtColor(game_area, cv2.COLOR_BGR2GRAY)
            
            # OCR ডাটা বের করা 
            data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
            
            n_boxes = len(data['text'])
            full_text_lines = []
            current_line_text = ""
            current_line_boxes = []
            
            for i in range(n_boxes):
                if int(data['conf'][i]) > 20:
                    word = data['text'][i].strip().upper()
                    if word:
                        current_line_text += word + " "
                        current_line_boxes.append((data['left'][i], data['top'][i], data['width'][i], data['height'][i]))
                    elif current_line_text:
                        full_text_lines.append((current_line_text.strip(), current_line_boxes))
                        current_line_text = ""
                        current_line_boxes = []
            
            if current_line_text:
                full_text_lines.append((current_line_text.strip(), current_line_boxes))
                
            final_full_text = " ".join([line[0] for line in full_text_lines])
            safe_text = final_full_text.replace('\n', ' ')[:60]
            print(f"[{iteration}] Game OCR: {safe_text}...", flush=True)
            
            for kw in ALL_KEYWORDS:
                if kw in final_full_text and kw not in found_already:
                    print(f"[{iteration}] 🚨 HIT: {kw}", flush=True)
                    
                    match_box = None
                    for line_text, boxes in full_text_lines:
                        if kw in line_text:
                            x_min = min(b[0] for b in boxes)
                            y_min = min(b[1] for b in boxes)
                            x_max = max(b[0] + b[2] for b in boxes)
                            y_max = max(b[1] + b[3] for b in boxes)
                            match_box = (x_min, y_min, x_max - x_min, y_max - y_min)
                            break
                            
                    send_alert(kw, frame.copy(), match_box) 
                    found_already.add(kw)
            
        except Exception as e:
            print(f"[{iteration}] Error: {e}", flush=True)
            stream_url = None
            time.sleep(10)
            
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
