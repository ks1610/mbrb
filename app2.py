# -*- coding: utf-8 -*-
import asyncio
import sys
import os
import re
import threading
import logging
import time
import signal
from ctypes import *
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from queue import Queue
from time import sleep

# Third-party Libraries
import edge_tts
import pygame
import speech_recognition as sr
import ollama
import paho.mqtt.client as mqtt
import requests
import feedparser
import pytz
import psutil
import subprocess
import cv2
import numpy as np
import serial
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, Response
from dotenv import load_dotenv


# ==========================================
# SYSTEM INITIALIZATION
# ==========================================

def suppress_stderr():
    """Suppress stderr output to reduce console noise"""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)


suppress_stderr()
load_dotenv()


# ==========================================
# CONFIGURATION CONSTANTS
# ==========================================

# MQTT Configuration
MQTT_BROKER = os.getenv('MQTT_BROKER', 'broker.hivemq.com')
TOPIC_CMD = "raspi/esp32/relay"

# AI Configuration
LOCAL_MODEL = "qwen2.5:1.5b"

# Hardware Configuration
AMP_PIN = 4
WEB_PORT = 8080
MIC_DEVICE_INDEX = 0

# Voice Configuration
VOICE_NAME = "vi-VN-HoaiMyNeural"
TTS_PITCH = '+40Hz'
TTS_RATE = '+15%'

# System Configuration
SIMILARITY_THRESHOLD = 0.1
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')
WEB_PASSWORD = os.getenv('WEB_PASSWORD', '1')

# Vision Configuration
PID_KP_ROTATION = 0.5

# File Paths
PROTOTXT_PATH = "deploy.prototxt"
MODEL_PATH = "res10_300x300_ssd_iter_140000.caffemodel"


# ==========================================
# RSS FEEDS CONFIGURATION
# ==========================================
RSS_FEEDS = {
    "thời sự": "https://vnexpress.net/rss/thoi-su.rss",
    "thế giới": "https://vnexpress.net/rss/the-gioi.rss",
    "pháp luật": "https://vnexpress.net/rss/phap-luat.rss",
    "công nghệ": "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss",
    "kinh doanh": "https://vnexpress.net/rss/kinh-doanh.rss"
}


# ==========================================
# AI PROMPT CONFIGURATION
# ==========================================
SYS_INSTRUCT_BASE = (
    "Bạn là Hanah, một nữ robot trợ lý, tính cách nhí nhánh, đáng yêu."
    "QUAN TRỌNG: Câu trả lời phải cực kỳ ngắn gọn bằng tiếng Việt (không quá 10 câu), "
    "không sử dụng biểu tượng cảm xúc (emoji)."
)


# ==========================================
# GLOBAL VARIABLES
# ==========================================
# Frame Management
global_frame = None
frame_lock = threading.Lock()
frame_queue = Queue(maxsize=2)

# Thread Control
STOP_EVENT = threading.Event()

# System State
SYSTEM_CONFIG = {
    "camera": True,
    "ai": True,
    "mic": True,
    "sound": True,
    "tracking": False
}

# Network Session
weather_session = requests.Session()


# ==========================================
# GPIO SETUP
# ==========================================

os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'
from gpiozero import OutputDevice

try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    
    def py_error_handler(filename, line, function, err, fmt):
        pass
    
    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = cdll.LoadLibrary('libasound.so')
    asound.snd_lib_error_set_handler(c_error_handler)
except:
    pass

amp = OutputDevice(AMP_PIN, active_high=True, initial_value=False)


# ==========================================
# DNN MODEL INITIALIZATION
# ==========================================

net = None
try:
    net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, MODEL_PATH)
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    print("✅ Đã tải model nhận diện khuôn mặt DNN.")
except Exception as e:
    print(f"❌ Lỗi DNN: {e}. Camera vẫn sẽ chạy nhưng không Tracking được.")


# ==========================================
# MQTT CLIENT INITIALIZATION
# ==========================================

mqtt_client = mqtt.Client()
try:
    mqtt_client.connect(MQTT_BROKER, 1883, 60)
    mqtt_client.loop_start()
except:
    print("❌ Lỗi kết nối MQTT")


# ==========================================
# FLASK APP INITIALIZATION
# ==========================================

app = Flask(__name__)
app.secret_key = "hanah_robot_key"
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


# ==========================================
# SERIAL COMMUNICATION CLASS
# ==========================================

class RobotSerial:
    """Manages serial communication with Arduino with auto-reconnect"""
    
    def __init__(self, port='/dev/ttyUSB0', baud=115200):
        self.port = port
        self.baud = baud
        self.ser = None
        self.last_cmd_time = 0
        self.cmd_interval = 0.15  # Command throttling interval
        self.connect()
    
    def connect(self):
        """Establish serial connection"""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            print(f">>> ✅ Arduino connected on {self.port}")
        except:
            self.ser = None
    
    def send(self, cmd, speed, duration, force=False):
        """Send command to Arduino with throttling"""
        current_time = time.time()
        
        # Prioritize STOP commands or forced commands
        if cmd != "STOP" and not force:
            if current_time - self.last_cmd_time < self.cmd_interval:
                return False
        
        # Reconnect if needed
        if not self.ser or not self.ser.is_open:
            self.connect()
        
        if self.ser:
            try:
                msg = f"{cmd}:{int(speed)}:{int(duration)}\n"
                self.ser.write(msg.encode())
                if cmd != "STOP":
                    print(f">>> [SERIAL] {msg.strip()}")
                self.last_cmd_time = current_time
                return True
            except:
                return False
        
        return False


# Initialize robot serial connection
robot = RobotSerial()


# ==========================================
# VISION PROCESSING FUNCTIONS
# ==========================================

def process_tracking_pid(frame):
    """Process face detection and PID control for tracking"""
    if not SYSTEM_CONFIG["tracking"] or net is None:
        return
    
    (h, w) = frame.shape[:2]
    
    # Create blob for DNN
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)),
        1.0,
        (300, 300),
        (104.0, 177.0, 123.0)
    )
    
    net.setInput(blob)
    detections = net.forward()
    
    # Find best detection
    best_box = None
    max_conf = 0
    
    for i in range(detections.shape[2]):
        conf = detections[0, 0, i, 2]
        if conf > 0.5 and conf > max_conf:
            max_conf = conf
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            best_box = box.astype("int")
    
    if best_box is not None:
        (startX, startY, endX, endY) = best_box
        face_center_x = (startX + endX) / 2 / w
        error_x = face_center_x - 0.5
        
        # Apply PID control
        if abs(error_x) > 0.06:
            turn_speed = abs(error_x) * 255 * PID_KP_ROTATION + 110
            turn_speed = min(230, turn_speed)
            cmd = "TL" if error_x > 0 else "TR"
            robot.send(cmd, turn_speed, 60, force=True)
            cv2.putText(frame, f"PID {cmd}", (10, 60), 1, 1, (0, 255, 0), 2)
        
        cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 255, 0), 2)
    else:
        cv2.putText(frame, "SEARCHING...", (10, 30), 1, 1, (0, 0, 255), 2)


def camera_thread():
    """Main camera capture and processing thread"""
    global global_frame
    
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    print(">>> 📸 Luồng Camera bắt đầu...")
    
    while not STOP_EVENT.is_set():
        if not SYSTEM_CONFIG["camera"]:
            sleep(1)
            continue
        
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Lỗi đọc camera, đang thử lại...")
            sleep(2)
            cap.release()
            cap = cv2.VideoCapture(0)
            continue
        
        frame = cv2.flip(frame, 1)
        
        # Process tracking
        try:
            process_tracking_pid(frame)
        except Exception as e:
            print(f"Tracking Error: {e}")
        
        with frame_lock:
            global_frame = frame.copy()
    
    cap.release()


# Start camera thread
threading.Thread(target=camera_thread, daemon=True).start()


# ==========================================
# SYSTEM MONITORING FUNCTIONS
# ==========================================

def get_cpu_temperature():
    """Get CPU temperature with fallback methods"""
    try:
        # Method 1: vcgencmd (most accurate on Pi)
        res = subprocess.run(
            ['vcgencmd', 'measure_temp'],
            capture_output=True,
            text=True,
            timeout=1
        )
        if res.returncode == 0:
            return float(res.stdout.replace("temp=", "").replace("'C\n", ""))
    except:
        pass
    
    try:
        # Method 2: Read thermal zone file
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return round(int(f.read()) / 1000.0, 1)
    except:
        return 0.0


def get_power_status():
    """Check power status without crashing"""
    try:
        res = subprocess.run(
            ['vcgencmd', 'get_throttled'],
            capture_output=True,
            text=True,
            timeout=1
        )
        if res.returncode == 0 and '=' in res.stdout:
            val = res.stdout.strip().split('=')[1]
            status = int(val, 16)
            return "Stable" if status == 0 else "Low Voltage"
    except:
        pass
    return "Stable"


def get_disk_usage():
    """Get disk usage percentage"""
    try:
        return round(psutil.disk_usage('/').percent, 1)
    except:
        return 0


# ==========================================
# WEATHER & INFO FUNCTIONS
# ==========================================

def get_weather(city):
    """Query weather for any location"""
    if not OPENWEATHER_API_KEY:
        return "Em chưa có chìa khóa API để xem thời tiết đâu ạ."
    
    url = (
        f"http://api.openweathermap.org/data/2.5/weather?"
        f"q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=vi"
    )
    
    try:
        res = weather_session.get(url, timeout=2).json()
        
        if res.get("cod") != 200:
            return f"Em không tìm thấy thông tin thời tiết của khu vực {city} rồi."
        
        temp = round(res['main']['temp'])
        desc = res['weather'][0]['description']
        return f"Thời tiết ở {city} hiện là {temp} độ, {desc} ạ."
    except Exception as e:
        print(f"Lỗi Weather API: {e}")
        return "Mạng bên em đang chậm, em chưa xem được thời tiết ạ."


def check_info_request(user_text):
    """Handle time and weather requests"""
    t = user_text.lower()
    
    # Time request
    if any(w in t for w in ["mấy giờ", "thời gian", "giờ rồi"]):
        now = datetime.now()
        return f"Dạ, bây giờ là {now.hour} giờ {now.minute} phút ạ."
    
    # Weather request
    if "thời tiết" in t:
        match = re.search(r"thời tiết (?:tại|ở|khu vực)?\s*([\w\s]+)", t)
        if match:
            city_name = match.group(1).strip()
            if not city_name or city_name in ["nhỉ", "thế nào", "sao"]:
                city_name = "Hanoi"
            return get_weather(city_name)
        return get_weather("Hanoi")
    
    return None


# ==========================================
# COMMAND ANALYSIS FUNCTIONS
# ==========================================

def analyze_command_similarity(user_text):
    """Analyze device control commands (lights)"""
    t = user_text.lower()
    
    # Check if command contains both action and device number
    if not (any(w in t for w in ["bật", "tắt"]) and 
            any(w in t for w in ["1", "2", "3", "4"])):
        return None
    
    actions = {"bật": "on", "tắt": "off"}
    best_score = 0
    best_cmd = None
    
    for dev in ["1", "2", "3", "4"]:
        for act, state in actions.items():
            phrase = f"{act} đèn {dev}"
            score = SequenceMatcher(None, t, phrase).ratio()
            if dev in t:
                score += 0.2
            if score > best_score:
                best_score = score
                best_cmd = (dev, state)
    
    return best_cmd if best_score >= SIMILARITY_THRESHOLD else None


# ==========================================
# AUDIO FUNCTIONS
# ==========================================
async def speak(text):
    """Text-to-speech output"""
    if not SYSTEM_CONFIG["sound"] or STOP_EVENT.is_set():
        return
    
    clean = re.sub(r'\([^)]*\)', '', text).replace("*", "")
    if not clean.strip():
        return
    
    print(f"Hanah: {clean}")
    
    try:
        communicate = edge_tts.Communicate(
            clean,
            VOICE_NAME,
            pitch=TTS_PITCH,
            rate=TTS_RATE
        )
        await communicate.save("reply.mp3")
        amp.on()
        sleep(0.1)
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=24000)
        
        pygame.mixer.music.load("reply.mp3")
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            sleep(0.05)
        
        pygame.mixer.quit()
        amp.off()
        
        if os.path.exists("reply.mp3"):
            os.remove("reply.mp3")
    except:
        amp.off()

def listen():
    """Speech recognition input"""
    if not SYSTEM_CONFIG["mic"]:
        return None
    
    r = sr.Recognizer()
    r.energy_threshold = 2000
    
    try:
        with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
            # 1. Lọc nhiễu (Robot đang chuẩn bị)
            r.adjust_for_ambient_noise(source, duration=0.5)
            
            # 2. Phát tiếng "Tinh" báo hiệu sẵn sàng
            play_activation_sound()
            print("\n>>> 👂 Đang lắng nghe...") # In log để bạn dễ debug
            
            # 3. Bắt đầu thu âm giọng nói
            audio = r.listen(source, timeout=5, phrase_time_limit=8)
            return r.recognize_google(audio, language="vi-VN")
    except sr.WaitTimeoutError:
        return None # Không nói gì thì bỏ qua
    except Exception as e:
        # print(f"Lỗi mic: {e}") 
        return None

def play_activation_sound():
    """Tạo âm thanh 'Tinh' ngắn gọn để báo hiệu bắt đầu nghe"""
    if not SYSTEM_CONFIG["sound"]: return

    try:
        # Bật Amply
        amp.on()
        sleep(0.05)

        # Khởi tạo mixer nếu chưa có
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=24000, size=-16, channels=1)

        # TẠO ÂM THANH BẰNG NUMPY (Sine wave 880Hz - Nốt La cao)
        duration = 0.15  # Độ dài 0.15 giây
        sample_rate = 24000
        n_samples = int(sample_rate * duration)
        
        # Tạo sóng âm
        t = np.linspace(0, duration, n_samples, False)
        # Tần số 880Hz tạo tiếng "Tinh" trong trẻo
        tone = np.sin(880 * t * 2 * np.pi) 
        
        # Làm dịu âm thanh ở cuối để không bị "bụp" (Fade out)
        fade_out = np.linspace(1, 0, n_samples)
        tone = tone * fade_out

        # Chuyển đổi sang định dạng 16-bit cho Pygame
        audio_data = (tone * 32767).astype(np.int16)
        
        # Phát âm thanh
        sound = pygame.sndarray.make_sound(audio_data)
        sound.play()
        
        # Đợi phát xong
        sleep(duration + 0.05)
        
    except Exception as e:
        print(f"Lỗi âm thanh cue: {e}")
    finally:
        # Tắt Amply ngay lập tức để tiết kiệm điện
        amp.off()
# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        user_pass = request.form.get('password')
        if user_pass == WEB_PASSWORD:
            session['logged_in'] = True
            session.permanent = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Sai mật khẩu!")
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    """Main dashboard"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html')


@app.route('/device')
def device_page():
    """Device control page"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('device.html')


@app.route('/hanah')
def chat_page():
    """Chat interface page"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('chat.html')


@app.route('/camera')
def camera_page():
    """Camera view page"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('camera.html')


@app.route('/control')
def control_page():
    """Robot control page"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('control.html')


@app.route('/video_feed')
def video_feed():
    """Video stream endpoint"""
    def generate():
        while True:
            with frame_lock:
                if global_frame is None:
                    # Send loading frame
                    blank_frame = np.zeros((240, 320, 3), np.uint8)
                    cv2.putText(
                        blank_frame,
                        "Initialing Camera...",
                        (50, 120),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (255, 255, 255),
                        2
                    )
                    frame_to_send = blank_frame
                else:
                    frame_to_send = global_frame
                
                ret, jpeg = cv2.imencode(
                    '.jpg',
                    frame_to_send,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 65]
                )
                
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' +
                           jpeg.tobytes() + b'\r\n')
            
            sleep(0.05)  # ~20 FPS
    
    if not session.get('logged_in'):
        return "Unauthorized", 401
    
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/system-stats')
def system_stats():
    """System statistics API"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        disk = psutil.disk_usage('/')
        mem = psutil.virtual_memory()
        
        return jsonify({
            "cpu_temp": get_cpu_temperature(),
            "memory_usage": mem.percent,
            "disk_usage": disk.percent,
            "power_draw": get_power_status(),
            "uptime": str(timedelta(seconds=int(time.time() - psutil.boot_time())))
        })
    except Exception as e:
        print(f"Stats Error: {e}")
        return jsonify({"error": "Internal Error"}), 500


@app.route('/api/get_system_config')
def get_config():
    """Get system configuration"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(SYSTEM_CONFIG)


@app.route('/api/toggle_system/<target>/<action>', methods=['POST'])
def toggle_system(target, action):
    """Toggle system components"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    if target in SYSTEM_CONFIG:
        state = (action == "on")
        SYSTEM_CONFIG[target] = state
        
        status_msg = "STARTED" if state else "STOPPED"
        print(f">>> ⚙️ Service {target.upper()} is {status_msg}")
        
        return jsonify({
            "status": "success",
            "new_state": SYSTEM_CONFIG[target]
        })
    
    return jsonify({"error": "Invalid target"}), 400


@app.route('/api/move', methods=['POST'])
def api_move():
    """Robot movement API"""
    data = request.json
    robot.send(
        data.get('cmd'),
        data.get('speed'),
        data.get('duration')
    )
    return jsonify({"status": "sent"})


@app.route('/api/play-remote-audio', methods=['POST'])
def play_remote_audio():
    """Play audio from web interface"""
    if 'audio' not in request.files:
        return "No audio", 400
    
    audio_blob = request.files['audio']
    raw_path = "remote_raw.webm"
    conv_path = "remote_final.wav"
    audio_blob.save(raw_path)
    
    def play_task():
        try:
            subprocess.run(
                [
                    'ffmpeg', '-y', '-i', raw_path,
                    '-acodec', 'pcm_s16le',
                    '-ar', '44100', '-ac', '1',
                    conv_path
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            amp.on()
            sleep(0.1)
            pygame.mixer.init()
            pygame.mixer.music.load(conv_path)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                sleep(0.1)
            
            pygame.mixer.quit()
            amp.off()
            
            if os.path.exists(raw_path):
                os.remove(raw_path)
            if os.path.exists(conv_path):
                os.remove(conv_path)
        except:
            amp.off()
    
    threading.Thread(target=play_task, daemon=True).start()
    return jsonify({"status": "playing"})


# ==========================================
# MAIN ASYNC LOOP
# ==========================================

async def main_loop():
    """Main voice assistant loop"""
    await speak("Hanah khởi động xong rồi nè!")
    
    while not STOP_EVENT.is_set():
        try:
            user_input = listen()
            if not user_input:
                continue
            
            print(f"👤: {user_input}")
            
            if "tạm biệt" in user_input.lower(): await speak("Bai bai."); break 
            
            # 1. Check device commands
            cmd = analyze_command_similarity(user_input)
            if cmd:
                mqtt_client.publish(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}")
                action = 'bật' if cmd[1] == 'on' else 'tắt'
                await speak(f"Dạ, em đã {action} đèn {cmd[0]} rồi ạ!")
                continue
            
            # 2. Check info requests
            info = check_info_request(user_input)
            if info:
                await speak(info)
                continue
            
            # 3. AI conversation
            if SYSTEM_CONFIG["ai"]:
                res = ollama.chat(
                    model=LOCAL_MODEL,
                    messages=[
                        {'role': 'system', 'content': SYS_INSTRUCT_BASE},
                        {'role': 'user', 'content': user_input}
                    ]
                )
                await speak(res['message']['content'])
        
        except Exception as e:
            print(f"Lỗi vòng lặp: {e}")
            sleep(1)


# ==========================================
# FLASK SERVER RUNNER
# ==========================================

def run_flask():
    """Run Flask web server"""
    app.run(
        host='0.0.0.0',
        port=WEB_PORT,
        use_reloader=False,
        threaded=True
    )


# ==========================================
# MAIN ENTRY POINT
# ==========================================
if __name__ == "__main__":
    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, lambda s, f: STOP_EVENT.set())
    
    # Start Flask server in background thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Run main async loop
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        pass