import cv2
import numpy as np
import threading
from time import sleep
import os
import globals
from globals import BASE_DIR, STOP_EVENT, frame_lock
from uart_handle import robot
from system_logs import load_system_config, load_system_logs, SYSTEM_CONFIG, SYSTEM_LOGS

PID_KP_ROTATION = 0.5

ROOT_DIR = os.path.dirname(globals.BASE_DIR)

CASCADE_PATH = os.path.join(ROOT_DIR, "device-check", "face_recongnize", "haarcascade_frontalface_default.xml")
facedetect = cv2.CascadeClassifier(CASCADE_PATH)
TRAINER_PATH = os.path.join(ROOT_DIR, "device-check", "face_recongnize", "Trainer.yml")

name_list = ["Person0", "Person1", "Person2"]
recognizer = cv2.face.LBPHFaceRecognizer_create()
try: 
    recognizer.read(TRAINER_PATH)
except: pass

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
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    print(">>> 📸 Luồng Camera bắt đầu...")
    
    while not globals.STOP_EVENT.is_set():
        if not globals.SYSTEM_CONFIG.get("camera"):
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
        
        try:
            process_tracking_pid(frame)
        except Exception as e:
            print(f"Tracking Error: {e}")
        
        # CHÚ Ý: Phải gọi thông qua globals thì web mới nhận được ảnh
        with globals.frame_lock:
            globals.global_frame = frame.copy()
    
    cap.release()
