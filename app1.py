# -*- coding: utf-8 -*-
import asyncio
import edge_tts
import pygame
import speech_recognition as sr
import ollama
import paho.mqtt.publish as publish
import sys
import os
import re
import threading
import logging
import requests
import feedparser
import pytz
from time import sleep 
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, render_template, jsonify
from ctypes import *
from difflib import SequenceMatcher
from dotenv import load_dotenv

load_dotenv()

# --- CẤU HÌNH GPIO ---
os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'
from gpiozero import OutputDevice

# ==========================================
# 1. CẤU HÌNH CHUNG
# ==========================================

#MQTT_BROKER = "broker.hivemq.com"
MQTT_BROKER = os.getenv('MQTT_BROKER', 'broker.hivemq.com')
TOPIC_CMD = "raspi/esp32/relay"

MIC_DEVICE_INDEX = 0 
AMP_PIN = 4 
LOCAL_MODEL = "qwen2.5:1.5b"
VOICE_NAME = "vi-VN-HoaiMyNeural"
TTS_PITCH = '+40Hz'
TTS_RATE = '+15%'
SIMILARITY_THRESHOLD = 0.1 
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')

# RSS Feeds
RSS_FEEDS = {
    "thời sự": "https://vnexpress.net/rss/thoi-su.rss",
    "thế giới": "https://vnexpress.net/rss/the-gioi.rss",
    "pháp luật": "https://vnexpress.net/rss/phap-luat.rss",
    "công nghệ": "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss",
    "kinh doanh": "https://vnexpress.net/rss/kinh-doanh.rss"
}

app = Flask(__name__)
app.secret_key = "mysecretkey"
# WEB_PASSWORD = "1"
WEB_PASSWORD = os.getenv('WEB_PASSWORD', '1')
WEB_PORT = 8080

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

SYS_INSTRUCT_BASE = """
Bạn là trợ lý ảo tên Hanah, tính cách nhí nhảnh.
Nhiệm vụ: Trò chuyện vui vẻ.
- Trả lời tiếng Việt, ngắn gọn dưới 40 từ.
- Không dùng icon.
"""

# ==========================================
# 2. KHỞI TẠO PHẦN CỨNG
# ==========================================
try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    def py_error_handler(filename, line, function, err, fmt): pass
    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = cdll.LoadLibrary('libasound.so')
    asound.snd_lib_error_set_handler(c_error_handler)
except: pass

try:
    print(f"\n>>> ⏳ Đang kết nối Local AI ({LOCAL_MODEL})...")
    # Chỉ khởi tạo GPIO, KHÔNG khởi tạo Audio ở đây nữa để tránh chiếm dụng
    amp = OutputDevice(AMP_PIN, active_high=True, initial_value=False)
except Exception as e:
    print(f"❌ Lỗi khởi tạo: {e}")
    sys.exit(1)

# ==========================================
# 3. CÁC HÀM XỬ LÝ THÔNG TIN
# ==========================================

def get_current_time():
    try:
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now = datetime.now(vn_tz)
        return f"Bây giờ là {now.hour} giờ {now.minute} phút, ngày {now.day} tháng {now.month}."
    except: return "Lỗi đồng hồ ạ."

def extract_city_name(text):
    prompt = f"Trích xuất tên thành phố hoặc quốc gia trong câu: '{text}'. Chỉ trả về tên tiếng Anh (Ví dụ: Hanoi). Nếu không có trả về 'None'."
    try:
        resp = ollama.chat(model=LOCAL_MODEL, messages=[{'role': 'user', 'content': prompt}])
        city = re.sub(r'[^\w\s]', '', resp['message']['content'].strip())
        if "None" in city or len(city) > 20: return "Hanoi"
        return city
    except: return "Hanoi"

def get_weather(text_input):
    city = extract_city_name(text_input)
    print(f"🔍 Tra thời tiết: {city}")
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=vi"
        res = requests.get(url, timeout=5).json()
        if res.get("cod") != 200: return f"Không tìm thấy thời tiết {city}."
        
        desc = res["weather"][0]["description"]
        temp = int(res["main"]["temp"])
        hum = res["main"]["humidity"]
        return f"Tại {res['name']}, trời {desc}, nhiệt độ {temp} độ, độ ẩm {hum}%."
    except: return "Mất kết nối thời tiết."

def get_news(text_input):
    text_input = text_input.lower()
    try:
        specific_category = None
        for key in RSS_FEEDS:
            if key in text_input:
                specific_category = key
                break
        
        if specific_category:
            url = RSS_FEEDS[specific_category]
            feed = feedparser.parse(url)
            if not feed.entries: return f"Không có tin {specific_category} mới."
            titles = [entry.title for entry in feed.entries[:5]]
            return f"Điểm tin {specific_category}: {'. '.join(titles)}. Hết tin."
        else:
            final_speech = "Điểm tin nhanh. "
            for category, url in RSS_FEEDS.items():
                feed = feedparser.parse(url)
                if feed.entries:
                    top_news = [entry.title for entry in feed.entries[:2]] 
                    final_speech += f"Mục {category}: {'. '.join(top_news)}. "
            return final_speech
    except: return "Lỗi tải tin tức."

def check_info_request(text):
    if not text: return None
    t = text.lower()
    if any(w in t for w in ["mấy giờ", "thời gian", "ngày bao nhiêu"]): return get_current_time()
    if any(w in t for w in ["thời tiết", "nhiệt độ", "mưa không"]): return get_weather(text)
    if any(w in t for w in ["tin tức", "tin mới", "đọc báo", "thời sự", "thế giới", "pháp luật", "công nghệ", "kinh doanh"]): return get_news(text)
    return None

def analyze_command_similarity(user_text):
    if not user_text: return None
    user_text = user_text.lower()
    
    if not (any(w in user_text for w in ["bật", "tắt", "mở", "đóng"]) and 
            any(w in user_text for w in ["1", "2", "3", "4", "một", "hai", "ba", "bốn"])):
        return None

    actions = {"bật": "on", "tắt": "off", "mở": "on", "đóng": "off"}
    best_score = 0; best_cmd = None
    
    for dev_id in ["1", "2", "3", "4"]:
        for act, state in actions.items():
            phrases = [f"{act} đèn {dev_id}", f"{act} thiết bị {dev_id}", f"{act} {dev_id}"]
            for p in phrases:
                score = SequenceMatcher(None, user_text, p).ratio()
                if dev_id in user_text or (dev_id=="1" and "một" in user_text) or \
                   (dev_id=="2" and "hai" in user_text) or (dev_id=="3" and "ba" in user_text) or \
                   (dev_id=="4" and "bốn" in user_text): score += 0.2
                if score > best_score: best_score = score; best_cmd = (dev_id, state)

    if best_score >= SIMILARITY_THRESHOLD: return best_cmd
    return None

# ==========================================
# 4. WEB SERVER
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == WEB_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Sai mật khẩu")
    return render_template('login.html', error=None)

@app.route('/dashboard')
def dashboard(): return redirect(url_for('login')) if not session.get('logged_in') else render_template('dashboard.html')

@app.route('/hanah')
def chat_page(): return redirect(url_for('login')) if not session.get('logged_in') else render_template('chat.html')

@app.route('/device')
def device_page(): return redirect(url_for('login')) if not session.get('logged_in') else render_template('device.html')

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    msg = request.json.get("message", "")
    
    cmd = analyze_command_similarity(msg)
    if cmd:
        publish.single(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}", hostname=MQTT_BROKER)
        return jsonify({"reply": f"Ok, đã {cmd[1]} thiết bị {cmd[0]}."})
    
    info = check_info_request(msg)
    if info: return jsonify({"reply": info})
    
    try:
        res = ollama.chat(model=LOCAL_MODEL, messages=[{'role':'system','content':SYS_INSTRUCT_BASE},{'role':'user','content':msg}])
        return jsonify({"reply": res['message']['content']})
    except: return jsonify({"reply": "Lỗi AI."})

@app.route('/control/<relay>/<state>')
def control(relay, state):
    if not session.get('logged_in'): return "Unauthorized", 401
    try: publish.single(TOPIC_CMD, f"{relay}:{state}", hostname=MQTT_BROKER); return "OK"
    except: return "Error"

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

def run_flask(): app.run(host='0.0.0.0', port=WEB_PORT, use_reloader=False)
print(f">>> 🌍 Web Server: http://<IP-PI>:{WEB_PORT}")
threading.Thread(target=run_flask, daemon=True).start()

# ==========================================
# 5. VOICE ASSISTANT (ĐÃ SỬA LỖI AUDIO)
# ==========================================

def clean_text(text):
    text = re.sub(r'\([^)]*\)', '', text)
    return text.replace("*", "").replace("#", "").replace("😊", "").replace("👋", "")

def split_text_smart(text, chunk_size=200):
    sentences = re.split(r'(?<=[.?!])\s+', text)
    merged = []
    curr = ""
    for s in sentences:
        if not s.strip(): continue
        if len(curr) + len(s) < chunk_size: curr += s + " "
        else:
            if curr: merged.append(curr.strip())
            curr = s + " "
    if curr: merged.append(curr.strip())
    return merged

async def generate_tts_file(text, filename):
    try:
        communicate = edge_tts.Communicate(text, VOICE_NAME, pitch=TTS_PITCH, rate=TTS_RATE)
        await communicate.save(filename)
        return True
    except: return False

async def speak(text):
    clean_content = clean_text(text)
    if not clean_content.strip(): return
    print(f"Bot (Voice): {clean_content}") 
    
    chunks = split_text_smart(clean_content, chunk_size=250)
    if not chunks: return

    try:
        amp.on()
        sleep(0.1)
        
        # [QUAN TRỌNG] Khởi tạo Loa trước khi nói
        try: pygame.mixer.init(frequency=24000)
        except: pass
        
        current_file = "tts_part_0.mp3"
        await generate_tts_file(chunks[0], current_file)
        
        for i in range(len(chunks)):
            if os.path.exists(current_file):
                pygame.mixer.music.load(current_file)
                pygame.mixer.music.play()
            
            next_file = f"tts_part_{i+1}.mp3"
            next_task = None
            if i + 1 < len(chunks):
                next_task = asyncio.create_task(generate_tts_file(chunks[i+1], next_file))
            
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            
            if os.path.exists(current_file):
                os.remove(current_file)
            
            if next_task:
                await next_task
                current_file = next_file
        
        # [QUAN TRỌNG] Tắt Loa để trả lại Sound Card cho Mic
        pygame.mixer.quit()
                
    except Exception as e:
        print(f"❌ Lỗi loa: {e}")
    finally:
        sleep(0.2)
        amp.off()
        for f in os.listdir():
            if f.startswith("tts_part_") and f.endswith(".mp3"):
                try: os.remove(f)
                except: pass

def listen():
    r = sr.Recognizer()
    r.energy_threshold = 2000; r.dynamic_energy_threshold = True 
    try:
        # [QUAN TRỌNG] Đảm bảo MIC_DEVICE_INDEX đúng
        with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
            print("\n🎤 Đang nghe... (Mời bạn nói)") 
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=8, phrase_time_limit=10)
            print("⏳ Đang dịch...")
            text = r.recognize_google(audio, language="vi-VN")
            print(f"👤 Bạn nói: {text}")
            return text
    except Exception as e: 
        print(f"⚠️ Lỗi Mic: {e}")
        return None

async def main():
    await speak("Hanah đã sẵn sàng!")
    while True:
        try:
            user_input = listen()
            if not user_input: continue
            
            if user_input.lower() in ["tạm biệt", "tắt máy"]:
                await speak("Bai bai."); break 

            cmd = analyze_command_similarity(user_input)
            if cmd:
                publish.single(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}", hostname=MQTT_BROKER)
                await speak(f"Ok, đã {cmd[1]} đèn {cmd[0]}.")
                continue

            info = check_info_request(user_input)
            if info: await speak(info); continue

            res = ollama.chat(model=LOCAL_MODEL, messages=[{'role':'system','content':SYS_INSTRUCT_BASE},{'role':'user','content':user_input}])
            await speak(res['message']['content'])
            
        except Exception as e:
            print(f"⚠️ Lỗi vòng lặp: {e}")
            await speak("Có lỗi nhỏ, thử lại nhé.")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\nSTOPPING...")
    # [QUAN TRỌNG] Bắt lỗi sập chương trình để biết lý do
    except Exception as e: print(f"\n\n>>> ☠️ CHƯƠNG TRÌNH CRASH VÌ LỖI: {e}")
    finally: 
        try: amp.off()
        except: pass
        try: pygame.mixer.quit()
        except: pass
        sys.exit(0)