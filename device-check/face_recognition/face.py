import cv2
from deepface import DeepFace
import os

def recognize_from_webcam(db_path, model_name='VGG-Face'):
    # 1. Khởi tạo Webcam
    cap = cv2.VideoCapture(0)
    
    print(f"Đang sử dụng model: {model_name}. Nhấn 'q' để thoát.")

    while True:
        # Đọc từng khung hình từ webcam
        ret, frame = cap.read()
        if not ret:
            break

        try:
            # 2. Nhận diện khuôn mặt trong frame
            # Chúng ta dùng enforce_detection=False để tránh crash khi không thấy mặt
            results = DeepFace.find(img_path=frame, 
                                    db_path=db_path, 
                                    model_name=model_name, 
                                    enforce_detection=False,
                                    silent=True) # Ẩn các log thừa

            if len(results) > 0 and not results[0].empty:
                # Lấy thông tin người khớp nhất
                result_df = results[0]
                matched_path = result_df.iloc[0]['identity']
                
                # Trích xuất tên từ đường dẫn (ví dụ: db/person1/img.jpg -> person1)
                name = matched_path.split(os.sep)[-2] 
                
                # Lấy tọa độ khuôn mặt để vẽ khung (DeepFace trả về x, y, w, h)
                source_x = result_df.iloc[0]['source_x']
                source_y = result_df.iloc[0]['source_y']
                source_w = result_df.iloc[0]['source_w']
                source_h = result_df.iloc[0]['source_h']

                # Vẽ hình chữ nhật và tên lên màn hình
                cv2.rectangle(frame, (source_x, source_y), (source_x + source_w, source_y + source_h), (0, 255, 0), 2)
                cv2.putText(frame, name, (source_x, source_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (36, 255, 12), 2)

        except Exception as e:
            print(f"Lỗi xử lý: {e}")

        # 3. Hiển thị kết quả
        cv2.imshow("Face Recognition - Press 'q' to quit", frame)

        # Nhấn 'q' để thoát
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

# Chạy function
if __name__ == "__main__":
    # Đảm bảo đường dẫn db/ của bạn đã có ảnh mẫu
    recognize_from_webcam(db_path="db/")