import json
import psutil
import os
import subprocess
import time
from datetime import datetime

import globals
# from globals import BASE_DIR, CONFIG_FILE, LOG_FILE, file_lock, SYSTEM_CONFIG, SYSTEM_LOGS, STOP_EVENT

def load_system_config():
    """Đọc cấu hình từ file JSON"""
    default_config = {
        "camera": True,
        "ai": True,
        "mic": True,
        "sound": True,
        "tracking": False
    }
    if os.path.exists(globals.CONFIG_FILE):
        try:
            with open(globals.CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Lỗi đọc config: {e}")
            return default_config
    return default_config

def save_system_logs():
    """Lưu logs vào file JSON"""
    try:
        with globals.file_lock:
            with open(globals.LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(globals.SYSTEM_LOGS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Lỗi lưu logs: {e}")

def load_system_logs():
    """Đọc logs từ file JSON"""
    if os.path.exists(globals.LOG_FILE):
        try:
            with open(globals.LOG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_system_config():
    """Lưu cấu hình vào file JSON"""
    try:
        with globals.file_lock:
            with open(globals.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(globals.SYSTEM_CONFIG, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Lỗi lưu config: {e}")

def add_system_log(message, level="info", service="SYSTEM"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {"time": timestamp, "service": service, "message": message, "level": level}
    globals.SYSTEM_LOGS.append(log_entry)
    if len(globals.SYSTEM_LOGS) > 100: globals.SYSTEM_LOGS.pop(0) # Giữ tối đa 100 log
    
    save_system_logs()

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

# System State
SYSTEM_CONFIG = load_system_config()
print(f"Loaded Config: {SYSTEM_CONFIG}")

# System Logs
SYSTEM_LOGS = load_system_logs()
print(f"Loaded {len(SYSTEM_LOGS)} logs.")