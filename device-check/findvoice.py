import asyncio
import edge_tts
import pygame
import os
import sys
from time import sleep

# --- CẤU HÌNH GPIO (Để bật Ampli) ---
os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'
from gpiozero import OutputDevice

# ====== KHU VỰC CHỈNH GIỌNG (SỬA Ở ĐÂY) ======
# 1. Tên giọng (vi-VN-HoaiMyNeural hoặc vi-VN-NamMinhNeural)
VOICE_NAME = "vi-VN-HoaiMyNeural"

# 2. Cao độ (Pitch): 
#    - Tăng: '+10Hz', '+20Hz'... (Giọng cao, trẻ con)
#    - Giảm: '-10Hz', '-20Hz'... (Giọng trầm, ồm)
TTS_PITCH = '+90Hz' 

# 3. Tốc độ (Rate):
#    - Tăng: '+10%', '+20%'... (Nói nhanh)
#    - Giảm: '-10%', '-20%'... (Nói chậm)
TTS_RATE = '+20%' 

# Cấu hình chân Ampli (4 hoặc 17)
AMP_PIN = 4
# =============================================

# --- BỘ LỌC LỖI ALSA (Cho sạch màn hình) ---
from ctypes import *
try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    def py_error_handler(filename, line, function, err, fmt):
        pass
    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = cdll.LoadLibrary('libasound.so')
    asound.snd_lib_error_set_handler(c_error_handler)
except:
    pass

# --- KHỞI TẠO PHẦN CỨNG ---
try:
    amp = OutputDevice(AMP_PIN, active_high=True, initial_value=False)
    pygame.mixer.init(frequency=24000)
    print("\n>>> 🛠️ CÔNG CỤ TEST GIỌNG NÓI <<<")
    print(f"⚙️ Cấu hình hiện tại: Pitch={TTS_PITCH} | Rate={TTS_RATE}")
except Exception as e:
    print(f"Lỗi khởi tạo: {e}")
    sys.exit(1)

async def test_speak(text):
    print(f"🔊 Đang đọc: '{text}'")
    file_path = "test_audio.mp3"
    
    try:
        # Tạo file âm thanh với tham số Pitch/Rate
        communicate = edge_tts.Communicate(text, VOICE_NAME, pitch=TTS_PITCH, rate=TTS_RATE)
        await communicate.save(file_path)
        
        # Init lại mixer để đảm bảo tần số đúng
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=24000)
            
        # Bật Ampli
        amp.on()
        sleep(0.1)
        
        # Phát
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
            
        pygame.mixer.quit()
        
    except Exception as e:
        print(f"❌ Lỗi: {e}")
    finally:
        sleep(0.2)
        amp.off()
        if os.path.exists(file_path):
            os.remove(file_path)

async def main():
    print("👉 Gõ văn bản rồi Enter để nghe thử.")
    print("👉 Gõ 'exit' để thoát và sửa code nếu chưa ưng ý.\n")
    
    while True:
        try:
            user_text = "xin chào"
            if user_text.lower() in ['exit', 'thoát']:
                break
            if not user_text.strip():
                continue
                
            await test_speak(user_text)
            print("-" * 30)
            
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nĐã thoát.")
        amp.off()
