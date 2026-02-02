import os
import time
from gpiozero import OutputDevice

# Nếu bạn dùng GPIO 17 cho chân SD của Ampli thì sửa thành 17
AMP_PIN = 4 

def test_system():
    # 1. Bật Ampli
    try:
        amp = OutputDevice(AMP_PIN, active_high=True, initial_value=False)
        amp.on()
        print(f"✅ Đã bật Ampli (GPIO {AMP_PIN})")
        time.sleep(1)
    except:
        print("⚠️ Cảnh báo: Không điều khiển được GPIO Ampli (có thể do lỗi config), nhưng vẫn sẽ thử test âm thanh.")

    # 2. Ghi âm
    print("\n🎤 BẮT ĐẦU GHI ÂM 5 GIÂY...")
    print("Hãy nói to vào Mic: 'Alo 1 2 3 4'...")
    # -D default: dùng thiết bị mặc định ta vừa cấu hình trong asound.conf
    os.system("arecord -D default -f S16_LE -r 16000 -d 5 test_voice.wav")
    
    # 3. Phát lại
    print("\n🔊 ĐANG PHÁT LẠI...")
    os.system("aplay -D default test_voice.wav")
    
    # 4. Dọn dẹp
    print("\n✅ Test xong.")
    # amp.off() # Tắt dòng này nếu muốn Ampli vẫn bật

if __name__ == "__main__":
    test_system()
