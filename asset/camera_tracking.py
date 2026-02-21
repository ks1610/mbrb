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

PROTOTXT_PATH = os.path.join(ROOT_DIR, "deploy.prototxt")
MODEL_PATH = os.path.join(ROOT_DIR, "res10_300x300_ssd_iter_140000.caffemodel")
CASCADE_PATH = os.path.join(ROOT_DIR, "device-check", "face_recongnize", "haarcascade_frontalface_default.xml")
TRAINER_PATH = os.path.join(ROOT_DIR, "device-check", "face_recongnize", "Trainer.yml")

name_list = ["Person0", "Person1", "Person2"]
recognizer = cv2.face.LBPHFaceRecognizer_create()
try: 
    recognizer.read(TRAINER_PATH)
except: pass

net = None
try:
    net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, MODEL_PATH)
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
except Exception as e:
    print(f"❌ Lỗi DNN: {e}")

def process_tracking_pid(frame):
    """Process face detection and PID control for tracking"""
    if not globals.SYSTEM_CONFIG["tracking"] or net is None:
        return
    (h, w) = frame.shape[:2]
    
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

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
        
        # --- BẢO VỆ CHỐNG CRASH KHI MẶT CHẠM VIỀN ---
        startX, startY = max(0, startX), max(0, startY)
        endX, endY = min(w, endX), min(h, endY)
        
        try:
            # Cắt khuôn mặt từ ảnh xám dựa trên tọa độ DNN
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
                
                # 1. Tính toán kích thước khối Text để làm nền chuẩn xác
                text_size, _ = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                text_w = text_size[0]
                label_h = 30  # Chiều cao cố định của khung label
                
                # 2. Đặt tọa độ mặc định (Nằm bên trên frame)
                bg_x = startX
                bg_y = startY - label_h
                
                # 3. Tính toán va chạm viền (ưu tiên Trái/Phải trước)
                if startX < 30:  # Chạm cạnh trái -> Ném label sang phải frame
                    bg_x = endX
                    bg_y = startY
                elif endX > w - text_w - 10:  # Chạm cạnh phải -> Ném label sang trái frame
                    bg_x = startX - text_w - 10
                    bg_y = startY
                elif startY < label_h:  # Chạm cạnh trên -> Ném label xuống dưới frame
                    bg_x = startX
                    bg_y = endY
                elif endY > h - label_h:  # Chạm cạnh dưới -> Giữ nguyên bên trên
                    bg_x = startX
                    bg_y = startY - label_h
                
                # 4. Bẫy lỗi an toàn: Không cho label rớt ra khỏi góc màn hình
                bg_x = max(0, min(bg_x, w - text_w - 10))
                bg_y = max(0, min(bg_y, h - label_h))

                # Vẽ Box khuôn mặt
                cv2.rectangle(frame, (startX, startY), (endX, endY), color, 2)
                
                # Vẽ Box nền cho chữ (sử dụng tọa độ bg_x, bg_y đã tính)
                cv2.rectangle(frame, (bg_x, bg_y), (bg_x + text_w + 10, bg_y + label_h), color, -1)
                
                # In chữ vào giữa nền
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
