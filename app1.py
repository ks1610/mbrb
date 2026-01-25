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
import psutil       
import subprocess   
import cv2          
import numpy as np
import signal 
from time import sleep 
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, Response
from ctypes import *
from difflib import SequenceMatcher
from dotenv import load_dotenv

load_dotenv()

# --- CẤU HÌNH GPIO ---
os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'
from gpiozero import OutputDevice

# ==========================================
# 1. CẤU HÌNH CHUNG & TRẠNG THÁI HỆ THỐNG
# ==========================================

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

# --- BIẾN QUẢN LÝ ---
STOP_EVENT = threading.Event()

SYSTEM_CONFIG = {
    "camera": True,  # Bật/Tắt luồng Camera
    "ai": True,      # Bật/Tắt Ollama
    "mic": True,     # Bật/Tắt lắng nghe
    "sound": True    # Bật/Tắt loa
}

RSS_FEEDS = {
    "thời sự": "https://vnexpress.net/rss/thoi-su.rss",
    "thế giới": "https://vnexpress.net/rss/the-gioi.rss",
    "pháp luật": "https://vnexpress.net/rss/phap-luat.rss",
    "công nghệ": "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss",
    "kinh doanh": "https://vnexpress.net/rss/kinh-doanh.rss"
}

app = Flask(__name__)
app.secret_key = "mysecretkey"
WEB_PASSWORD = os.getenv('WEB_PASSWORD', '1')
WEB_PORT = 8080

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

SYS_INSTRUCT_BASE = "Bạn là trợ lý ảo tên Hanah, tính cách nhí nhảnh. Trả lời tiếng Việt ngắn gọn."

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
    amp = OutputDevice(AMP_PIN, active_high=True, initial_value=False)
except Exception as e:
    print(f"❌ Lỗi khởi tạo: {e}")
    sys.exit(1)

# ==========================================
# 3. CAMERA THREAD (ĐÃ THÊM LẬT HÌNH & TỐI ƯU)
# ==========================================
global_frame = None
camera_lock = threading.Lock()

def start_camera_thread():
    global global_frame
    cap = None

    while not STOP_EVENT.is_set():
        # Nếu setting Camera đang TẮT
        if not SYSTEM_CONFIG["camera"]:
            if cap and cap.isOpened(): cap.release(); cap = None
            sleep(1); continue

        # Nếu chưa mở camera
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(0)
            if not cap.isOpened(): sleep(5); continue
            
            # Cấu hình giảm tải
            cap.set(3, 320); cap.set(4, 240); cap.set(5, 20); cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        success, frame = cap.read()
        if success:
            # Lật hình (Mirror)
            frame = cv2.flip(frame, 1)
            with camera_lock: global_frame = frame.copy()
        else: sleep(0.1)
    
    if cap: cap.release()

threading.Thread(target=start_camera_thread, daemon=True).start()

def generate_frames():
    global global_frame
    blank = np.zeros((240, 320, 3), np.uint8)
    cv2.putText(blank, "OFF", (100, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
    _, b_buf = cv2.imencode(".jpg", blank); b_bytes = b_buf.tobytes()

    while not STOP_EVENT.is_set():
        if not SYSTEM_CONFIG["camera"]:
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + b_bytes + b'\r\n')
            sleep(1); continue

        with camera_lock:
            if global_frame is None: continue
            (flag, enc) = cv2.imencode(".jpg", global_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
            if not flag: continue
        
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(enc) + b'\r\n')
        sleep(0.05)

# --- SYSTEM STATS FUNCTIONS ---
def get_cpu_temperature():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return round(int(f.read()) / 1000.0, 1)
    except: return 45.5

def get_uptime():
    try: return str(timedelta(seconds=int(datetime.now().timestamp() - psutil.boot_time())))
    except: return "--"

def get_memory_usage():
    try: return psutil.virtual_memory().percent
    except: return 0

def get_disk_usage():
    try:
        disk = psutil.disk_usage('/')
        percent = (disk.used / disk.total) * 100
        return round(percent, 1)
    except: return 0

def get_power_status():
    try:
        out = subprocess.check_output(["vcgencmd", "get_throttled"]).decode()
        s = int(out.split("=")[1].strip(), 16)
        if s == 0: return "Ổn Định"
        elif s & 0x1: return "Yếu Nguồn"
        else: return "Throttled"
    except: return "Unknown"

def get_network_speed():
    # Giản lược để tránh delay loop
    return "N/A"

# ==========================================
# 4. CÁC HÀM LOGIC (RÚT GỌN)
# ==========================================
def get_current_time(): return datetime.now().strftime("%H:%M")
def extract_city_name(t): return "Hanoi"
def get_weather(t): return "Đang cập nhật"
def get_news(t): return "Tin mới"
def check_info_request(text):
    if not text: return None
    t = text.lower()
    if "giờ" in t: return get_current_time()
    if "thời tiết" in t: return get_weather(text)
    if "tin" in t or "báo" in t: return get_news(text)
    return None

def analyze_command_similarity(user_text):
    if not user_text: return None
    user_text = user_text.lower()
    if not (any(w in user_text for w in ["bật", "tắt"]) and any(w in user_text for w in ["1", "2", "3", "4"])): return None
    best_score = 0; best_cmd = None
    actions = {"bật": "on", "tắt": "off"}
    for dev in ["1", "2", "3", "4"]:
        for act, state in actions.items():
            phrase = f"{act} đèn {dev}"
            score = SequenceMatcher(None, user_text, phrase).ratio()
            if dev in user_text: score += 0.2
            if score > best_score: best_score = score; best_cmd = (dev, state)
    return best_cmd if best_score >= SIMILARITY_THRESHOLD else None

# ==========================================
# 5. WEB SERVER (ROUTES ĐÃ GỘP VÀ SỬA LỖI)
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == WEB_PASSWORD:
            session['logged_in'] = True; return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/dashboard')
def dashboard(): return render_template('dashboard.html') if session.get('logged_in') else redirect(url_for('login'))

@app.route('/control')
def control_page(): return render_template('control.html') if session.get('logged_in') else redirect(url_for('login'))

@app.route('/camera')
def camera_page(): return render_template('camera.html') if session.get('logged_in') else redirect(url_for('login'))

@app.route('/device')
def device_page(): return render_template('device.html') if session.get('logged_in') else redirect(url_for('login'))

@app.route('/hanah')
def chat_page(): return render_template('chat.html') if session.get('logged_in') else redirect(url_for('login'))

@app.route('/video_feed')
def video_feed(): return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- API CONTROL ---
@app.route('/api/toggle_system/<target>/<action>', methods=['POST'])
def toggle_system(target, action):
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    if target in SYSTEM_CONFIG: 
        SYSTEM_CONFIG[target] = (action == "on")
        return jsonify({"status":"success", "new_state": SYSTEM_CONFIG[target]})
    return jsonify({"error":"bad request"})

@app.route('/api/get_system_config')
def get_config(): return jsonify(SYSTEM_CONFIG) if session.get('logged_in') else (jsonify({"error": "Unauthorized"}), 401)

# --- API SYSTEM STATS (ĐÃ SỬA LỖI DUPLICATE) ---
@app.route('/api/system-stats')
def system_stats():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    
    cpu_temp = get_cpu_temperature()
    return jsonify({
        "cpu_temp": cpu_temp,
        "status": "Normal" if cpu_temp < 70 else "Hot",
        "uptime": get_uptime(),
        "memory": get_memory_usage(),
        "disk": get_disk_usage(), # Đã có Disk
        "power": get_power_status(),
        "net_speed": get_network_speed()
    })

# --- API CHAT & CONTROL ---
@app.route('/api/chat', methods=['POST'])
def api_chat():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    msg = request.json.get("message", "")
    
    cmd = analyze_command_similarity(msg)
    if cmd:
        publish.single(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}", hostname=MQTT_BROKER)
        return jsonify({"reply": f"Ok, đã {cmd[1]} đèn {cmd[0]}."})
    
    info = check_info_request(msg)
    if info: return jsonify({"reply": info})
    
    if SYSTEM_CONFIG["ai"]:
        try:
            res = ollama.chat(model=LOCAL_MODEL, messages=[{'role':'system','content':SYS_INSTRUCT_BASE},{'role':'user','content':msg}])
            return jsonify({"reply": res['message']['content']})
        except: return jsonify({"reply": "Lỗi AI."})
    return jsonify({"reply": "AI đang tắt."})

@app.route('/control/<relay>/<state>')
def control(relay, state):
    try: publish.single(TOPIC_CMD, f"{relay}:{state}", hostname=MQTT_BROKER); return "OK"
    except: return "Error"

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

def run_flask(): app.run(host='0.0.0.0', port=WEB_PORT, use_reloader=False)
threading.Thread(target=run_flask, daemon=True).start()

# ==========================================
# 6. VOICE & MAIN LOOP (ĐÃ KHÔI PHỤC)
# ==========================================

def clean_text(text):
    text = re.sub(r'\([^)]*\)', '', text)
    return text.replace("*", "").replace("#", "").replace("😊", "").replace("👋", "")

async def speak(text):
    if not SYSTEM_CONFIG["sound"] or STOP_EVENT.is_set(): return
    clean = clean_text(text)
    if not clean.strip(): return
    print(f"Bot (Voice): {clean}") 
    
    try:
        communicate = edge_tts.Communicate(clean, VOICE_NAME, pitch=TTS_PITCH, rate=TTS_RATE)
        await communicate.save("reply.mp3")
        
        # Chỉ bật loa khi cần nói
        amp.on(); sleep(0.1)
        pygame.mixer.init(frequency=24000)
        pygame.mixer.music.load("reply.mp3")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy(): pygame.time.Clock().tick(10)
        pygame.mixer.quit()
    except Exception as e: print(f"❌ Lỗi loa: {e}")
    finally:
        sleep(0.2); amp.off()
        if os.path.exists("reply.mp3"): os.remove("reply.mp3")

def listen():
    if not SYSTEM_CONFIG["mic"] or STOP_EVENT.is_set(): 
        sleep(1); return None
        
    r = sr.Recognizer()
    r.energy_threshold = 2000; r.dynamic_energy_threshold = True 
    try:
        with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
            print("\n🎤 Đang nghe... (Mời bạn nói)") 
            r.adjust_for_ambient_noise(source, duration=0.5)
            # Timeout ngắn để vòng lặp chính không bị kẹt lâu
            audio = r.listen(source, timeout=5, phrase_time_limit=10)
            print("⏳ Đang dịch...")
            text = r.recognize_google(audio, language="vi-VN")
            print(f"👤 Bạn nói: {text}")
            return text
    except sr.WaitTimeoutError: return None
    except sr.UnknownValueError: return None
    except Exception as e: 
        print(f"⚠️ Lỗi Mic: {e}")
        return None

# Xử lý ngắt Ctrl+C
def signal_handler(sig, frame):
    print("\nSTOPPING..."); STOP_EVENT.set(); sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

async def main():
    # [YÊU CẦU] Speak câu chào khi khởi động
    await speak("Hanah đã sẵn sàng!")
    
    while not STOP_EVENT.is_set():
        try:
            # [YÊU CẦU] Luôn lắng nghe input
            user_input = listen()
            if not user_input: continue
            
            if "tạm biệt" in user_input.lower(): 
                await speak("Bai bai."); break 

            cmd = analyze_command_similarity(user_input)
            if cmd:
                publish.single(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}", hostname=MQTT_BROKER)
                await speak(f"Ok, đã {cmd[1]} đèn {cmd[0]}.")
                continue

            info = check_info_request(user_input)
            if info: await speak(info); continue

            # AI Logic
            if SYSTEM_CONFIG["ai"]:
                res = ollama.chat(model=LOCAL_MODEL, messages=[{'role':'system','content':SYS_INSTRUCT_BASE},{'role':'user','content':user_input}])
                await speak(res['message']['content'])
            else:
                await speak("Chức năng chat AI đang tắt.")
            
        except Exception as e:
            print(f"Lỗi vòng lặp: {e}")
            await speak("Có lỗi nhỏ, thử lại nhé.")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
    finally: print(">>> DONE.")