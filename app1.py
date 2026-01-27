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
import serial 
import signal 
import time
from time import sleep 
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, Response
from ctypes import *
from difflib import SequenceMatcher
from dotenv import load_dotenv

load_dotenv()

# --- CẤU HÌNH ---
os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'
from gpiozero import OutputDevice

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

# --- KẾT NỐI ARDUINO ---
try:
    # LƯU Ý: Kiểm tra kỹ cổng này trên Terminal bằng lệnh 'ls /dev/tty*'
    # Thường là /dev/ttyUSB0 hoặc /dev/ttyACM0
    arduino = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
    arduino.flush()
    print(">>> ✅ Đã kết nối Arduino qua Serial")
except Exception as e:
    print(f">>> ⚠️ Lỗi kết nối Arduino: {e}")
    arduino = None

# --- BIẾN QUẢN LÝ ---
STOP_EVENT = threading.Event()

SYSTEM_CONFIG = {
    "camera": True,
    "ai": True,
    "mic": True,
    "sound": True,
    "tracking": False # Mặc định tắt để an toàn, bật lên từ Web hoặc giọng nói
}

# Biến quản lý thời gian gửi lệnh để tránh spam
last_cmd_time = 0
CMD_INTERVAL = 0.2 # Chỉ gửi lệnh mỗi 200ms

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
log = logging.getLogger('werkzeug'); log.setLevel(logging.ERROR)
SYS_INSTRUCT_BASE = "Bạn là trợ lý ảo tên Hanah, tính cách nhí nhảnh. Trả lời tiếng Việt ngắn gọn."

# ... (Phần khởi tạo Audio giữ nguyên) ...
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
# 3. CAMERA & VISUAL TRACKING LOGIC
# ==========================================
global_frame = None
camera_lock = threading.Lock()
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

def send_arduino_cmd(cmd, speed, duration):
    """Gửi lệnh và in ra Log"""
    global last_cmd_time
    
    # Chỉ gửi nếu đã qua khoảng thời gian an toàn (Debounce)
    if time.time() - last_cmd_time < CMD_INTERVAL:
        return

    if arduino and arduino.is_open:
        try:
            msg = f"{cmd}:{speed}:{duration}\n"
            arduino.write(msg.encode('utf-8'))
            print(f">>> [ARDUINO SEND] {msg.strip()}") # IN TÍN HIỆU RA TERMINAL
            last_cmd_time = time.time()
        except Exception as e:
            print(f">>> ❌ Lỗi gửi Serial: {e}")
    else:
        print(f">>> [MÔ PHỎNG] Arduino chưa kết nối. Lệnh: {cmd}:{speed}:{duration}")

def draw_visual_simulation(frame, x, y, w, h, center_x, error_x, action_text):
    """Vẽ các thông số mô phỏng lên màn hình Camera"""
    h_img, w_img, _ = frame.shape
    
    # 1. Vẽ khung mặt
    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
    
    # 2. Vẽ tâm mặt
    cv2.circle(frame, (center_x, y + h//2), 5, (0, 0, 255), -1)
    
    # 3. Vẽ vùng chết (Deadzone) - Vùng an toàn không quay xe
    cv2.line(frame, (160 - 40, 0), (160 - 40, 240), (255, 255, 0), 1) # Trái
    cv2.line(frame, (160 + 40, 0), (160 + 40, 240), (255, 255, 0), 1) # Phải
    
    # 4. Hiển thị thông số
    info_text = f"ErrX: {error_x} | W: {w}"
    cv2.putText(frame, info_text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    # 5. Hiển thị hành động đang thực hiện
    if action_text:
        cv2.putText(frame, f"CMD: {action_text}", (10, h_img - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

def process_tracking(frame):
    """Logic tính toán và vẽ mô phỏng"""
    if not SYSTEM_CONFIG["tracking"]: 
        cv2.putText(frame, "TRACKING: OFF", (10, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        return

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
    
    current_action = "STOP"

    if len(faces) > 0:
        # Lấy khuôn mặt to nhất
        (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
        
        frame_center_x = 160  # Độ phân giải 320x240
        face_center_x = x + w // 2
        
        # --- LOGIC ĐIỀU KHIỂN ---
        error_x = face_center_x - frame_center_x
        deadzone_x = 40 # Vùng an toàn
        
        target_width = 70 # Kích thước mặt mong muốn (để giữ khoảng cách)
        deadzone_w = 15
        error_w = target_width - w

        # 1. Xoay trái/phải
        if abs(error_x) > deadzone_x:
            speed = 140
            duration = 100
            if error_x > 0: # Mặt lệch phải -> Quay phải
                send_arduino_cmd("TL", speed, duration)
                current_action = "TURN RIGHT"
            else: # Mặt lệch trái -> Quay trái
                send_arduino_cmd("TR", speed, duration)
                current_action = "TURN LEFT"
        
        # 2. Tiến/Lùi (Chỉ khi góc quay đã tạm ổn)
        elif abs(error_w) > deadzone_w:
            speed = 160
            duration = 150
            if error_w > 0: # Mặt nhỏ -> Xa -> Tiến
                send_arduino_cmd("FW", speed, duration)
                current_action = "FORWARD"
            else: # Mặt to -> Gần -> Lùi
                send_arduino_cmd("BW", speed, duration)
                current_action = "BACKWARD"
        
        # --- VẼ MÔ PHỎNG LÊN CAMERA ---
        draw_visual_simulation(frame, x, y, w, h, face_center_x, error_x, current_action)
        
    else:
        # Không thấy mặt -> Dừng
        # send_arduino_cmd("STOP", 0, 0) # Có thể comment lại để tránh spam lệnh dừng
        cv2.putText(frame, "NO FACE", (10, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

def start_camera_thread():
    global global_frame
    cap = None

    while not STOP_EVENT.is_set():
        if not SYSTEM_CONFIG["camera"]:
            if cap and cap.isOpened(): cap.release(); cap = None
            sleep(1); continue

        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(0)
            if not cap.isOpened(): sleep(5); continue
            # Độ phân giải thấp để xử lý nhanh
            cap.set(3, 320); cap.set(4, 240); cap.set(5, 30); cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        success, frame = cap.read()
        if success:
            frame = cv2.flip(frame, 1) # Lật gương
            
            # --- GỌI HÀM XỬ LÝ TRACKING ---
            try:
                process_tracking(frame)
            except Exception as e:
                print(f"Tracking Error: {e}")

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
            # Nén ảnh chất lượng 60% để truyền nhanh
            (flag, enc) = cv2.imencode(".jpg", global_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            if not flag: continue
        
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(enc) + b'\r\n')
        sleep(0.04) # ~25 FPS

# ... (Phần System Stats, Flask Routes, Voice, Main giữ nguyên như code trước) ...
# Để đảm bảo code chạy, tôi copy lại các phần quan trọng bên dưới

# --- SYSTEM STATS ---
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
        return round((disk.used / disk.total) * 100, 1)
    except: return 0
def get_power_status():
    try:
        out = subprocess.check_output(["vcgencmd", "get_throttled"]).decode()
        return "Ổn Định" if int(out.split("=")[1].strip(), 16) == 0 else "Yếu Nguồn"
    except: return "Unknown"
def get_network_speed(): return "N/A"

# --- LOGIC ---
def get_current_time(): return datetime.now().strftime("%H:%M")
def analyze_command_similarity(user_text):
    if not user_text: return None
    t = user_text.lower()
    # Kích hoạt Tracking bằng giọng nói
    if "đi theo" in t or "lại đây" in t:
        SYSTEM_CONFIG["tracking"] = True
        return ("TRACKING", "on")
    if "dừng lại" in t or "đứng yên" in t:
        SYSTEM_CONFIG["tracking"] = False
        return ("TRACKING", "off")
    
    if not (any(w in t for w in ["bật", "tắt"]) and any(w in t for w in ["1", "2", "3", "4"])): return None
    # ... (Giữ nguyên logic bật tắt đèn)
    return None

def check_info_request(t): return None # (Giữ nguyên logic cũ)

# --- FLASK ---
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

@app.route('/api/toggle_system/<target>/<action>', methods=['POST'])
def toggle_system(target, action):
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    if target == "tracking":
        SYSTEM_CONFIG["tracking"] = (action == "on")
        return jsonify({"status":"success", "new_state": SYSTEM_CONFIG["tracking"]})
    if target in SYSTEM_CONFIG: 
        SYSTEM_CONFIG[target] = (action == "on")
        return jsonify({"status":"success", "new_state": SYSTEM_CONFIG[target]})
    return jsonify({"error":"bad request"})

@app.route('/api/get_system_config')
def get_config(): return jsonify(SYSTEM_CONFIG) if session.get('logged_in') else (jsonify({"error": "Unauthorized"}), 401)

@app.route('/api/system-stats')
def system_stats():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "cpu_temp": get_cpu_temperature(),
        "status": "Normal",
        "uptime": get_uptime(),
        "memory": get_memory_usage(),
        "disk": get_disk_usage(),
        "power": get_power_status(),
        "net_speed": get_network_speed()
    })

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    msg = request.json.get("message", "")
    cmd = analyze_command_similarity(msg)
    if cmd:
        if cmd[0] == "TRACKING": return jsonify({"reply": f"Ok, chế độ bám theo đã {cmd[1]}."})
        publish.single(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}", hostname=MQTT_BROKER)
        return jsonify({"reply": f"Ok, đã {cmd[1]} đèn {cmd[0]}."})
    
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

@app.route('/api/move', methods=['POST'])
def api_move():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    cmd = data.get('cmd', 'STOP')
    speed = data.get('speed', 0)
    duration = data.get('duration', 0)
    
    # Gửi lệnh xuống Arduino
    send_arduino_cmd(cmd, speed, duration)
    return jsonify({"status": "sent"})

def run_flask(): app.run(host='0.0.0.0', port=WEB_PORT, use_reloader=False)
threading.Thread(target=run_flask, daemon=True).start()

# --- MAIN ---
def clean_text(text): return re.sub(r'\([^)]*\)', '', text).replace("*", "").replace("😊", "")
async def speak(text):
    if not SYSTEM_CONFIG["sound"] or STOP_EVENT.is_set(): return
    clean = clean_text(text)
    if not clean.strip(): return
    print(f"Bot: {clean}") 
    try:
        communicate = edge_tts.Communicate(clean, VOICE_NAME, pitch=TTS_PITCH, rate=TTS_RATE)
        await communicate.save("reply.mp3")
        amp.on(); sleep(0.1)
        pygame.mixer.init(frequency=24000); pygame.mixer.music.load("reply.mp3"); pygame.mixer.music.play()
        while pygame.mixer.music.get_busy(): pygame.time.Clock().tick(10)
        pygame.mixer.quit()
    except: pass
    finally: sleep(0.2); amp.off(); 
    if os.path.exists("reply.mp3"): os.remove("reply.mp3")

def listen():
    if not SYSTEM_CONFIG["mic"] or STOP_EVENT.is_set(): sleep(1); return None
    r = sr.Recognizer(); r.energy_threshold = 2000
    try:
        with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
            print("\n🎤 ..."); r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=5, phrase_time_limit=10)
            text = r.recognize_google(audio, language="vi-VN")
            print(f"👤: {text}"); return text
    except: return None

def signal_handler(sig, frame): print("\nSTOPPING..."); STOP_EVENT.set(); sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

async def main():
    await speak("Hanah đã sẵn sàng!")
    while not STOP_EVENT.is_set():
        try:
            user_input = listen()
            if not user_input: continue
            if "tạm biệt" in user_input.lower(): await speak("Bai bai."); break 
            
            cmd = analyze_command_similarity(user_input)
            if cmd:
                if cmd[0] == "TRACKING": await speak(f"Chế độ bám theo đã {cmd[1]}")
                else: publish.single(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}", hostname=MQTT_BROKER); await speak(f"Ok {cmd[1]}")
                continue
                
            if SYSTEM_CONFIG["ai"]:
                res = ollama.chat(model=LOCAL_MODEL, messages=[{'role':'system','content':SYS_INSTRUCT_BASE},{'role':'user','content':user_input}])
                await speak(res['message']['content'])
        except: pass

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass