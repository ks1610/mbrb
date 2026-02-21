import asyncio
import re
import time
import subprocess
import tempfile
import wave
import numpy as np
import edge_tts
import speech_recognition as sr
import requests
import os
from datetime import datetime
import globals
from globals import BASE_DIR, CONFIG_FILE, LOG_FILE, file_lock, STOP_EVENT
from difflib import SequenceMatcher
from system_logs import load_system_config, load_system_logs, SYSTEM_CONFIG, SYSTEM_LOGS
from gpiozero import OutputDevice

# AI Configuration
LOCAL_MODEL = "qwen2.5:1.5b"
MIC_DEVICE_INDEX = 0
AMP_PIN = 4
SIMILARITY_THRESHOLD = 0.1

# Voice Configuration
VOICE_NAME = "vi-VN-HoaiMyNeural"
TTS_PITCH = '+40Hz'
TTS_RATE = '+15%'

# System Configuration
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')
amp = OutputDevice(AMP_PIN, active_high=True, initial_value=False)

# ==========================================
# AI PROMPT CONFIGURATION
# ==========================================
SYS_INSTRUCT_BASE = (
    "Bạn là Hanah, một nữ robot trợ lý, tính cách nhí nhánh, đáng yêu."
    "QUAN TRỌNG: Câu trả lời phải cực kỳ ngắn gọn bằng tiếng Việt (không quá 10 câu), "
    "không sử dụng biểu tượng cảm xúc (emoji)."
)

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

weather_session = requests.Session()

# ---------- helper to play audio in a thread (blocking) ----------
def _play_wav_blocking(path):
    subprocess.run(
        ['/usr/bin/aplay', '-D', 'plughw:2,0', path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

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
    if not globals.SYSTEM_CONFIG.get("sound", True) or STOP_EVENT.is_set():
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

def play_activation_sound():
    """Non-blocking activation 'tinh' via temporary wav + aplay"""
    if not globals.SYSTEM_CONFIG.get("sound", True):
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

def listen():
    # global globals.LAST_TONE_TIME

    if not globals.SYSTEM_CONFIG["mic"]:
        return None

    r = sr.Recognizer()
    r.energy_threshold = 2000

    try:
        with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
            r.adjust_for_ambient_noise(source, duration=0.5)

            now = time.time()
            if now - globals.LAST_TONE_TIME > 3: 
                play_activation_sound()
                globals.LAST_TONE_TIME = now

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