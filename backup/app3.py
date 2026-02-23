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
import socket

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

import wave
import tempfile
from pathlib import Path
import json

print("🔥 NEW VERSION LOADED @", time.strftime("%H:%M:%S"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(BASE_DIR, "system_logs.json")
CONFIG_FILE = os.path.join(BASE_DIR, "system_config.json")
file_lock = threading.Lock()

# ==========================================
# SYSTEM INITIALIZATION
# ==========================================

def suppress_stderr():
    """Suppress stderr output to reduce console noise"""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)


#suppress_stderr()
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
# PROTOTXT_PATH = "deploy.prototxt"
# MODEL_PATH = "res10_300x300_ssd_iter_140000.caffemodel"


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

audio_lock = threading.Lock()

# ==========================================
# FACE RECOGNITION MODEL CONFIGURATION
# ==========================================
facedetect = cv2.CascadeClassifier(r"device-check/face_recongnize/haarcascade_frontalface_default.xml")
recognizer = cv2.face.LBPHFaceRecognizer_create()
TRAINER_PATH = os.path.join(BASE_DIR, "device-check", "face_recongnize", "Trainer.yml")
recognizer.read(TRAINER_PATH)

name_list = ["Person0", "Person1", "Person2"]


# ==========================================
# DATA PERSISTENCE FUNCTIONS
# ==========================================

def load_system_config():
    """Đọc cấu hình từ file JSON"""
    default_config = {
        "camera": True,
        "ai": True,
        "mic": True,
        "sound": True,
        "tracking": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Lỗi đọc config: {e}")
            return default_config
    return default_config

def save_system_config():
    """Lưu cấu hình vào file JSON"""
    try:
        with file_lock:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(SYSTEM_CONFIG, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Lỗi lưu config: {e}")

def load_system_logs():
    """Đọc logs từ file JSON"""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_system_logs():
    """Lưu logs vào file JSON"""
    try:
        with file_lock:
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(SYSTEM_LOGS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Lỗi lưu logs: {e}")

def get_local_bdaddr():
    """Lấy địa chỉ MAC của Bluetooth Adapter (hci0)"""
    try:
        # Cách 1: Đọc từ file hệ thống (nhanh và chuẩn nhất trên Linux)
        with open('/sys/class/bluetooth/hci0/address', 'r') as f:
            return f.read().strip()
    except:
        try:
            # Cách 2: Dùng lệnh hciconfig nếu file không tồn tại
            res = subprocess.check_output("hciconfig hci0 | grep 'BD Address' | awk '{print $3}'", shell=True)
            return res.decode().strip()
        except:
            return None

# ==========================================
# GLOBAL VARIABLES
# ==========================================
LAST_TONE_TIME = 0

# Frame Management
global_frame = None
frame_lock = threading.Lock()
frame_queue = Queue(maxsize=2)

# Thread Control
STOP_EVENT = threading.Event()

# System State
SYSTEM_CONFIG = load_system_config()
print(f"Loaded Config: {SYSTEM_CONFIG}")

# System Logs
SYSTEM_LOGS = load_system_logs()
print(f"Loaded {len(SYSTEM_LOGS)} logs.")

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


try:
    cv2.setNumThreads(1)
except Exception:
    pass

# ---------- helper to play audio in a thread (blocking) ----------

def _play_wav_blocking(path):
    subprocess.run(
        ['/usr/bin/aplay', '-D', 'plughw:2,0', path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


# ==========================================
# DNN MODEL INITIALIZATION
# ==========================================

# net = None
# try:
#     net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, MODEL_PATH)
#     net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
#     net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
#     print("✅ Đã tải model nhận diện khuôn mặt DNN.")
# except Exception as e:
#     print(f"❌ Lỗi DNN: {e}. Camera vẫn sẽ chạy nhưng không Tracking được.")


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

# app = Flask(__name__)

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

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
    if not SYSTEM_CONFIG["tracking"]:
        return
    (h, w) = frame.shape[:2]
    
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    faces = facedetect.detectMultiScale(
        gray, 
        scaleFactor=1.2, 
        minNeighbors=5, 
        minSize=(30, 30)
    )
    best_box = None
    max_area = 0
    
    for (x, y, w_face, h_face) in faces:
        area = w_face * h_face
        if area > max_area:
            max_area = area
            best_box = (x, y, x + w_face, y + h_face) # (startX, startY, endX, endY)
    
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
        
        startX, startY = max(0, startX), max(0, startY)
        endX, endY = min(w, endX), min(h, endY)
        
        try:
            # Cắt khuôn mặt từ ảnh xám
            face_roi = gray[startY:endY, startX:endX]
            
            # Chỉ nhận diện nếu vùng cắt hợp lệ (không bị rỗng)
            if face_roi.shape[0] > 0 and face_roi.shape[1] > 0:
                serial, conf_recog = recognizer.predict(face_roi)
                
                # Cấu hình màu và tên
                if conf_recog > 40 and serial < len(name_list):
                    name = name_list[serial]
                    color = (0, 255, 0)  # Xanh lá cho người đã học
                else:
                    name = "Unknown"
                    color = (0, 0, 255)  # Đỏ cho người lạ

                # --- LOGIC HIỂN THỊ LABEL DYNAMICALLY ---
                text_size, _ = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                text_w = text_size[0]
                label_h = 30  # Chiều cao cố định của khung label
                
                bg_x = startX
                bg_y = startY - label_h
                
                # Va chạm viền
                if startX < 30:
                    bg_x = endX
                    bg_y = startY
                elif endX > w - text_w - 10:
                    bg_x = startX - text_w - 10
                    bg_y = startY
                elif startY < label_h:
                    bg_x = startX
                    bg_y = endY
                elif endY > h - label_h:
                    bg_x = startX
                    bg_y = startY - label_h
                
                bg_x = max(0, min(bg_x, w - text_w - 10))
                bg_y = max(0, min(bg_y, h - label_h))

                # Vẽ Box
                cv2.rectangle(frame, (startX, startY), (endX, endY), color, 2)
                cv2.rectangle(frame, (bg_x, bg_y), (bg_x + text_w + 10, bg_y + label_h), color, -1)
                cv2.putText(frame, name, (bg_x + 5, bg_y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
        except Exception as e:
            print(f"Lỗi nhận diện LBPH: {e}")
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
#threading.Thread(target=camera_thread, daemon=True).start()


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
# BLUETOOTH CONTROL SERVER 
# ==========================================

def bluetooth_server_thread():
    """Lắng nghe kết nối Bluetooth và duy trì trạng thái di chuyển"""
    server_sock = None
    try:
        # 1. Cấu hình Bluetooth
        os.system("sudo hciconfig hci0 up")
        os.system("sudo hciconfig hci0 piscan")
        os.system("sudo sdptool add SP")
        time.sleep(1)

        bd_addr = get_local_bdaddr()
        if not bd_addr:
            print("❌ Không tìm thấy địa chỉ MAC Bluetooth")
            add_system_log("Lỗi: Không tìm thấy Bluetooth MAC", "error", "BLUETOOTH")
            return

        print(f">>> 🔵 Bluetooth Server đang chạy tại {bd_addr} (Channel 1)")

        server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((bd_addr, 1)) 
        server_sock.listen(1)

        add_system_log(f"BT Server chạy tại {bd_addr}", "info", "BLUETOOTH")

        while not STOP_EVENT.is_set():
            try:
                client_sock, address = server_sock.accept()
                print(f">>> 🔵 Đã kết nối Bluetooth với {address}")
                add_system_log(f"Thiết bị {address} đã kết nối", "info", "BLUETOOTH")
                
                client_sock.settimeout(0.1) 
                
                try:
                    client_sock.send(b"Connected\r\n")
                except:
                    pass

                # Biến lưu trạng thái hiện tại (lastchar)
                # None = Đứng yên, 'F' = Tiến, 'B' = Lùi...
                current_state = None 

                while True:
                    try:
                        # 1. Cố gắng nhận dữ liệu mới
                        data = client_sock.recv(1024)
                        if not data:
                            break # Mất kết nối
                        
                        command_str = data.decode("utf-8").strip().upper()
                        
                        # 2. Cập nhật trạng thái (lastchar)
                        if 'S' in command_str:
                            print(">>> 🔵 BLE: STOP (S)")
                            robot.send("STOP", 0, 0, force=True)
                            current_state = None 
                        elif command_str:
                            # Lấy ký tự hợp lệ cuối cùng (F, B, L, R)
                            valid_cmds = [c for c in command_str if c in 'FBLR']
                            if valid_cmds:
                                current_state = valid_cmds[-1]
                                print(f">>> 🔵 BLE: Start State [{current_state}]")

                    except socket.timeout:
                        # Không có dữ liệu mới -> Không làm gì cả, giữ nguyên current_state
                        pass
                    except OSError:
                        break # Lỗi kết nối thực sự

                    if current_state:
                        speed = 200
                        cmd_arduino = None
                        duration = 100 

                        if current_state == 'F': cmd_arduino = "FW"
                        elif current_state == 'B': cmd_arduino = "BW"
                        elif current_state == 'L': cmd_arduino = "TL"; speed = 230
                        elif current_state == 'R': cmd_arduino = "TR"; speed = 230
                        
                        if cmd_arduino:
                            # Gửi lệnh duy trì chuyển động
                            robot.send(cmd_arduino, speed, duration, force=True)
                            add_system_log(f"BLE: {cmd_arduino} @ {speed}", "info", "BLUETOOTH")
                    else:
                        robot.send("STOP", 0, 0, force=True)
                    # Ngủ nhẹ để không chiếm 100% CPU
                    time.sleep(0.05)

            except Exception as e:
                print(f"❌ Lỗi kết nối Client: {e}")
            finally:
                try:
                    client_sock.close()
                    print(">>> 🔵 Client ngắt kết nối")
                except:
                    pass

    except Exception as e:
        print(f"❌ Lỗi Server: {e}")
    finally:
        if server_sock:
            server_sock.close()

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

def convert_wav_safe(src, dst):
    subprocess.run(
        [
            "/usr/bin/ffmpeg", "-y",
            "-i", src,
            "-ac", "1",             # Mono (loa robot thường là mono)
            "-ar", "44100",         # <--- ĐỔI THÀNH 44100 (Chuẩn nhất)
            "-acodec", "pcm_s16le", # 16-bit PCM
            dst
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

async def speak(text: str):
    if not SYSTEM_CONFIG.get("sound", True) or STOP_EVENT.is_set():
        return

    clean = re.sub(r"\([^)]*\)", "", text).replace("*", "").strip()
    if not clean:
        return

    print(f"Hanah: {clean}")

    raw_wav = f"/tmp/hanah_raw_{int(time.time()*1000)}.wav"
    final_wav = f"/tmp/hanah_{int(time.time()*1000)}.wav"

    try:
        communicate = edge_tts.Communicate(
            clean,
            VOICE_NAME,
            pitch=TTS_PITCH,
            rate=TTS_RATE
        )
        await communicate.save(raw_wav)

        # 🔥 THIS LINE FIXES THE GARBAGE SOUND
        convert_wav_safe(raw_wav, final_wav)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _play_wav_blocking, final_wav)

    except Exception as e:
        print(f"speak() error: {e}")
        amp.off()
    finally:
        for f in (raw_wav, final_wav):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except:
                pass

def listen():
    global LAST_TONE_TIME

    if not SYSTEM_CONFIG["mic"]:
        return None

    r = sr.Recognizer()
    r.energy_threshold = 2000

    try:
        with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
            r.adjust_for_ambient_noise(source, duration=0.5)

            now = time.time()
            if now - LAST_TONE_TIME > 3:   # 3s cooldown
                play_activation_sound()
                LAST_TONE_TIME = now

            audio = r.listen(source, timeout=5, phrase_time_limit=8)
            return r.recognize_google(audio, language="vi-VN")

    except sr.WaitTimeoutError:
        return None

    except sr.UnknownValueError:
        return None

    except sr.RequestError as e:
        print(f"Speech API error: {e}")
        return None

    except Exception as e:
        print(f"Listen error: {e}")
        return None


def play_activation_sound():
    """Non-blocking activation 'tinh' via temporary wav + aplay"""
    if not SYSTEM_CONFIG.get("sound", True):
        return

    try:
        duration = 0.12
        sample_rate = 24000
        n_samples = int(sample_rate * duration)
        t = np.linspace(0, duration, n_samples, False)
        tone = np.sin(880 * t * 2 * np.pi)
        fade_out = np.linspace(1, 0, n_samples)
        tone = (tone * fade_out)
        audio_data = (tone * 32767).astype(np.int16)

        # write temp wav
        tmp = tempfile.NamedTemporaryFile(prefix="hanah_tone_", suffix=".wav", delete=False)
        tmp_name = tmp.name
        tmp.close()
        with wave.open(tmp_name, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())

        # play in background thread so listen() is immediate
        _play_wav_blocking(tmp_name)

    except Exception as e:
        print(f"Lỗi âm thanh cue: {e}")
        try:
            amp.off()
        except:
            pass


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

@app.route('/health')
def health():
    return "OK", 200

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

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    msg = request.json.get("message", "")
    cmd = analyze_command_similarity(msg)
    if cmd:
        if cmd[0] == "TRACKING": return jsonify({"reply": f"Ok, chế độ bám theo đã {cmd[1]}."})
        try:
            # Dùng mqtt_client đã khởi tạo sẵn thay vì publish.single
            mqtt_client.publish(TOPIC_CMD, f"{cmd[0]}:{cmd[1]}")
            
            # Dịch trạng thái sang tiếng Việt cho câu trả lời tự nhiên
            action_vn = "bật" if cmd[1] == "on" else "tắt"
            add_system_log(f"Web Chat: Lệnh MQTT: Thiết bị {cmd[0]} -> {cmd[1].upper()}", "info", "MQTT_CMD")
            
            return jsonify({"reply": f"Dạ, em đã {action_vn} đèn {cmd[0]} rồi ạ."})
        except Exception as e:
            print(f"Lỗi gửi MQTT từ Web Chat: {e}")
            return jsonify({"reply": "Xin lỗi anh, em gặp lỗi khi gửi lệnh đến công tắc ạ."})
        # ------------------------
    
    if SYSTEM_CONFIG["ai"]:
        try:
            res = ollama.chat(model=LOCAL_MODEL, messages=[{'role':'system','content':SYS_INSTRUCT_BASE},{'role':'user','content':msg}])
            return jsonify({"reply": res['message']['content']})
        except: return jsonify({"reply": "Lỗi AI."})
    return jsonify({"reply": "AI đang tắt."})


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

def add_system_log(message, level="info", service="SYSTEM"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {"time": timestamp, "service": service, "message": message, "level": level}
    SYSTEM_LOGS.append(log_entry)
    if len(SYSTEM_LOGS) > 100: SYSTEM_LOGS.pop(0) # Giữ tối đa 100 log
    
    save_system_logs()

# 2. Thêm Route để mở trang log
@app.route('/logs')
def log_page():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('log.html')

# 3. Thêm API lấy danh sách log
@app.route('/api/get_logs')
def get_logs():
    if not session.get('logged_in'): return jsonify({"error": "Auth"}), 401
    return jsonify(SYSTEM_LOGS)

# 4. Thêm API xóa log
@app.route('/api/clear_logs', methods=['POST'])
def clear_logs_api():
    global SYSTEM_LOGS
    SYSTEM_LOGS = []
    save_system_logs()
    
    return jsonify({"status": "success"})

@app.route('/api/get_system_config')
def get_config():
    """Get system configuration"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(SYSTEM_CONFIG)


@app.route('/api/toggle_system/<target>/<action>', methods=['POST'])
def toggle_system(target, action):
    """Toggle system components and RECORD logs"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    if target in SYSTEM_CONFIG:
        state = (action == "on")
        SYSTEM_CONFIG[target] = state

        save_system_config()
        
        # --- HÀM GHI LOG ---
        log_msg = f"Đã { 'bật' if state else 'tắt' } dịch vụ {target.upper()}"
        level = "info"
        add_system_log(log_msg, level, target.upper())
        # ---------------------------------------------------

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

@app.route('/control/<int:relay>/<state>') # Route này xử lý GET từ device.html
def control_relay_web(relay, state):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    # 1. Gửi lệnh MQTT
    mqtt_client.publish(TOPIC_CMD, f"{relay}:{state}")
    
    # 2. Ghi System Log
    log_msg = f"Web UI: Đã { 'BẬT' if state == 'on' else 'TẮT' } thiết bị số {relay}"
    add_system_log(log_msg, "info", "DEVICE_WEB")
    
    return jsonify({"status": "success", "device": relay, "state": state})

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
                 '-ar', '24000', '-ac', '1',
                 conv_path
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            sleep(0.1)
            _play_wav_blocking(conv_path)
            
            if os.path.exists(raw_path):
                os.remove(raw_path)
            if os.path.exists(conv_path):
                os.remove(conv_path)
        except:
            amp.off()
    
    threading.Thread(target=play_task, daemon=True).start()
    return jsonify({"status": "playing"})

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

def run_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_loop())

def start_camera(delay=3):
    def _start():
        print(">>> ⏳ Waiting before starting camera...")
        time.sleep(delay)
        if SYSTEM_CONFIG["camera"]:
            threading.Thread(
                target=camera_thread,
                daemon=True
            ).start()
            print(">>> 📸 Camera thread started.")
    threading.Thread(target=_start, daemon=True).start()

async def main_loop():
    await asyncio.sleep(3)
    try:
        await speak("Hanah khởi động")
    except Exception as e:
        print(f"Greeting failed: {e}")

    loop = asyncio.get_event_loop()

    while not STOP_EVENT.is_set():
        try:
            # call blocking listen() in executor
            user_input = await loop.run_in_executor(None, listen)

            if not user_input:
                # small sleep to yield CPU
                await asyncio.sleep(0.1)
                continue

            print(f"👤: {user_input}")

            # exit phrase
            if "tạm biệt" in user_input.lower():
                await speak("Bai bai.")
                break

            # 1) Device control via language
            cmd = analyze_command_similarity(user_input)
            if cmd:
                device_id, cmd_state = cmd
                try:
                    # MQTT publish (paho is thread-safe for publish)
                    mqtt_client.publish(TOPIC_CMD, f"{device_id}:{cmd_state}")
                    add_system_log(f"Gửi lệnh MQTT: Thiết bị {device_id} -> {cmd_state.upper()}", "info", "MQTT_CMD")
                except Exception as e:
                    print(f"MQTT publish error: {e}")

                action_vn = 'bật' if cmd_state == 'on' else 'tắt'
                await speak(f"Đã {action_vn} đèn {device_id}!")
                continue

            # 2) Info requests (time/weather)
            info = check_info_request(user_input)
            if info:
                await speak(info)
                continue

            # 3) AI conversation (ollama.chat is blocking => run in executor)
            if SYSTEM_CONFIG.get("ai", True):
                try:
                    res = await loop.run_in_executor(None, lambda: ollama.chat(
                        model=LOCAL_MODEL,
                        messages=[
                            {'role': 'system', 'content': SYS_INSTRUCT_BASE},
                            {'role': 'user', 'content': user_input}
                        ]
                    ))
                    # extract text robustly
                    ai_text = None
                    try:
                        ai_text = res['message']['content']
                    except Exception:
                        if isinstance(res, str):
                            ai_text = res
                        elif isinstance(res, dict) and 'content' in res:
                            ai_text = res['content']
                    if ai_text:
                        await speak(ai_text)
                except Exception as e:
                    print(f"AI chat error: {e}")
                    await asyncio.sleep(0.5)

        except Exception as e:
            print(f"main_loop error: {e}")
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    # start async AI loop WITHOUT audio greeting
    threading.Thread(target=run_async_loop, daemon=True).start()

    # start camera later
    start_camera(delay=3)

    # start bluetooth server
    threading.Thread(target=bluetooth_server_thread, daemon=True).start()

    # start web server LAST
    app.run(
        host="0.0.0.0",
        port=WEB_PORT,
        use_reloader=False,
        threaded=True
    )