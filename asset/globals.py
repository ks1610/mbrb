import os
import threading
from queue import Queue

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "system_logs.json")
CONFIG_FILE = os.path.join(BASE_DIR, "system_config.json")

# State & Locks
file_lock = threading.Lock()
frame_lock = threading.Lock()
audio_lock = threading.Lock()
STOP_EVENT = threading.Event()

# Variables
global_frame = None
frame_queue = Queue(maxsize=2)
LAST_TONE_TIME = 0

SYSTEM_CONFIG = {}
SYSTEM_LOGS = []

# WEB_PORT = 8080
