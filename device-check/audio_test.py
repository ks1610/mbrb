from gpiozero import OutputDevice
import os
import time
import sys

# CẤU HÌNH
# Sử dụng GPIO 4 để điều khiển chân SD (Shutdown)
# active_high=True: Mức cao (High) là Bật, Mức thấp (Low) là Tắt
try:
    amp = OutputDevice(4, active_high=True, initial_value=False)
except Exception as e:
    print(f"LỖI GPIO: {e}")
    print("Gợi ý: Kiểm tra xem '1-Wire' có đang bật trong /boot/config.txt không?")
    sys.exit(1)

def main():
    print("="*40)
    print("   TEST ÂM THANH (GPIOZERO VERSION)")
    print("="*40)

    try:
        print("🔊 Đang kích hoạt Ampli (GPIO 4 lên High)...")
        amp.on() # Bật chân SD
        time.sleep(1) # Chờ 1s cho ampli khởi động (Pop-noise reduction)
        
        print("🎵 Đang phát âm thanh mẫu...")
        # Lệnh phát tiếng trái/phải
        result = os.system("speaker-test -c2 -t wav -l 2")
        
        if result == 0:
            print("\n✅ Đã phát xong lệnh test.")
        else:
            print("\n❌ Lỗi khi gọi speaker-test.")
            
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    finally:
        print("🔇 Đang tắt Ampli...")
        amp.off() # Tắt chân SD để tiết kiệm điện và tránh rè
        print("Đã tắt.")

if __name__ == "__main__":
    main()
