import os
import time
import cv2
import logging
import numpy as np
import psutil      
import subprocess  
import threading
from datetime import timedelta
import ollama
import google.generativeai as genai
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, Response
from system_logs import get_cpu_temperature, get_power_status, get_disk_usage, add_system_log, save_system_config
from system_logs import load_system_config, load_system_logs, add_chat_log, load_chat_logs, SYSTEM_CONFIG, SYSTEM_LOGS
from uart_handle import robot
from mqtt_handler import mqtt_client, TOPIC_CMD
from ai_module import analyze_command_similarity, LOCAL_MODEL, SYS_INSTRUCT_BASE, GEMINI_API_KEY
import globals
from globals import BASE_DIR, CONFIG_FILE, LOG_FILE, file_lock, STOP_EVENT

try:
    from ai_module import _play_wav_blocking
except ImportError:
    # Hàm dự phòng nếu không import được
    def _play_wav_blocking(path):
        subprocess.run(['/usr/bin/aplay', '-D', 'plughw:2,0', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

ROOT_DIR = os.path.dirname(globals.BASE_DIR)

app = Flask(
    __name__,
    template_folder=os.path.join(ROOT_DIR, "templates"),
    static_folder=os.path.join(ROOT_DIR, "static")
)

app.secret_key = "hanah_robot_key"
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

WEB_PASSWORD = os.getenv('WEB_PASSWORD', '1')

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
            if not globals.SYSTEM_CONFIG.get("camera", True):
                blank_frame = np.zeros((240, 320, 3), np.uint8)
                cv2.putText(blank_frame, "CAMERA IS OFF", (70, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                ret, jpeg = cv2.imencode('.jpg', blank_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                if ret: yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                time.sleep(0.5)
                continue
                
            with globals.frame_lock:
                if globals.global_frame is None:
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
                    frame_to_send = globals.global_frame
                
                ret, jpeg = cv2.imencode(
                    '.jpg',
                    frame_to_send,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 65]
                )
                
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' +
                           jpeg.tobytes() + b'\r\n')
            
            time.sleep(0.05)  # ~20 FPS
    
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

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if not session.get('logged_in'): 
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # 1. Đảm bảo parse JSON an toàn
        if not request.is_json:
            return jsonify({"reply": "Lỗi định dạng dữ liệu (không phải JSON)."}), 400
            
        msg = request.json.get("message", "")
        
        if msg:
            add_chat_log("user", msg)
        if not msg:
            return jsonify({"reply": "Đang nghe"})

        # 2. Xử lý riêng cho lệnh TRACKING từ UI (Giữ lại logic cũ của bạn)
        if msg.startswith("TRACKING:") or msg == "TRACKING":
            # Xử lý theo format UI gửi lên, ví dụ UI gửi "TRACKING:on"
            state = msg.split(":")[1] if ":" in msg else "on"
            mqtt_client.publish(TOPIC_CMD, f"TRACKING:{state}")
            add_chat_log("bot", f"Đã gửi lệnh TRACKING {state} đến robot.")
            return jsonify({"reply": f"Ok, chế độ bám theo đã {state}."})
            
        # 3. Phân tích ngữ nghĩa yêu cầu (Thời tiết, đèn, tin tức)
        request_data = analyze_command_similarity(msg)
        
        if request_data:
            if request_data["type"] == "info":
                add_chat_log("bot", request_data["data"])
                return jsonify({"reply": request_data["data"]})
                
            elif request_data["type"] == "command":
                device_id, cmd_state = request_data["data"]
                
                try:
                    mqtt_client.publish(TOPIC_CMD, f"{device_id}:{cmd_state}")
                    action_vn = "bật" if cmd_state == "on" else "tắt"
                    add_system_log(f"Web Chat: Lệnh MQTT: Thiết bị {device_id} -> {cmd_state.upper()}", "info", "MQTT_CMD")
                    add_chat_log("bot", f"Đã gửi lệnh {action_vn} thiết bị {device_id}")
                    return jsonify({"reply": f"Dạ, đã {action_vn} đèn {device_id} rồi ạ."})
                except Exception as e:
                    print(f"Lỗi gửi MQTT: {e}")
                    add_chat_log("bot", f"Lỗi khi gửi lệnh {action_vn} đèn {device_id}")
                    return jsonify({"reply": "lỗi khi gửi lệnh đến công tắc ạ."})

        # 4. Nếu không phải lệnh mặc định, chuyển cho AI (Qwen/Ollama)
        if globals.SYSTEM_CONFIG.get("ai", False):
            # try:
            #     res = ollama.chat(
            #         model=LOCAL_MODEL, 
            #         messages=[
            #             {'role': 'system', 'content': SYS_INSTRUCT_BASE},
            #             {'role': 'user', 'content': msg}
            #         ]
            #     )
            #     add_chat_log("bot", res['message']['content'])
            #     return jsonify({"reply": res['message']['content']})
            # except Exception as ai_e: 
            #     print(f"Lỗi gọi Ollama AI: {ai_e}")
            #     return jsonify({"reply": "sự cố kết nối."})
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel(
                    model_name='gemini-2.5-flash',
                    system_instruction=SYS_INSTRUCT_BASE
                )
                response = model.generate_content(msg)
                
                if response and response.text:
                    ai_reply = response.text
                    add_chat_log("bot", ai_reply)
                    return jsonify({"reply": ai_reply})
            except Exception as e:
                print(f"Lỗi Gemini: {e}")
                return jsonify({"reply": "Lỗi kết nối AI."})
            except Exception as e:
                print(f"Lỗi cấu hình Gemini: {e}")
        return jsonify({"reply": "Chế độ AI đang được tắt."})
        
    except Exception as e:
        # Nếu có lỗi crash, sẽ in ra màn hình console và trả về giao diện chat thay vì lỗi 500 đỏ
        print(f"LỖI NGHIÊM TRỌNG TRONG API CHAT: {e}")
        return jsonify({"reply": f"Lỗi Server backend: {e}"})

# 2. Thêm Route để mở trang log
@app.route('/logs')
def log_page():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('log.html')

# 3. Thêm API lấy danh sách log
@app.route('/api/get_logs')
def get_logs():
    if not session.get('logged_in'): return jsonify({"error": "Auth"}), 401
    return jsonify(globals.SYSTEM_LOGS)

# 4. Thêm API xóa log
@app.route('/api/clear_logs', methods=['POST'])
def clear_logs_api():
    globals.SYSTEM_LOGS.clear()
    save_system_logs()
    
    return jsonify({"status": "success"})

@app.route('/api/get_system_config')
def get_config():
    """Get system configuration"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(globals.SYSTEM_CONFIG)


@app.route('/api/toggle_system/<target>/<action>', methods=['POST'])
def toggle_system(target, action):
    """Toggle system components and RECORD logs"""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    if target in globals.SYSTEM_CONFIG:
        state = (action == "on")
        globals.SYSTEM_CONFIG[target] = state

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
            "new_state": globals.SYSTEM_CONFIG[target]
        })
    
    return jsonify({"error": "Invalid target"}), 400

@app.route('/api/chat/history', methods=['GET'])
def get_chat_history():
    if not session.get('logged_in'): 
        return jsonify({"error": "Unauthorized"}), 401
    
    logs = load_chat_logs()
    return jsonify({"history": logs})

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
    # Đổi sang thư mục /tmp/ để không bị lỗi phân quyền ghi file
    raw_path = "/tmp/remote_raw.webm"
    conv_path = "/tmp/remote_final.wav"
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
            
            time.sleep(0.1)
            _play_wav_blocking(conv_path)
            
            if os.path.exists(raw_path):
                os.remove(raw_path)
            if os.path.exists(conv_path):
                os.remove(conv_path)
        except Exception as e:
            print(f"Lỗi play audio từ web: {e}")
            # Bỏ amp.off() đi vì amp không tồn tại trong file này
    
    threading.Thread(target=play_task, daemon=True).start()
    return jsonify({"status": "playing"})