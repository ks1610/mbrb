# -*- coding: utf-8 -*-
import socket
import os
import time
import subprocess
import sys

def get_local_bdaddr():
    """Lấy địa chỉ MAC của Bluetooth Adapter (hci0)"""
    try:
        # Cách 1: Đọc từ file hệ thống (Nhanh và chuẩn nhất trên Pi)
        with open('/sys/class/bluetooth/hci0/address', 'r') as f:
            return f.read().strip()
    except:
        try:
            # Cách 2: Dùng lệnh hciconfig
            res = subprocess.check_output("hciconfig hci0 | grep 'BD Address' | awk '{print $3}'", shell=True)
            return res.decode().strip()
        except:
            return None

def setup_bluetooth_hardware():
    """Cấu hình phần cứng Bluetooth"""
    print(">>> ⚙️ Đang cấu hình Bluetooth...")
    os.system("sudo hciconfig hci0 down")
    os.system("sudo hciconfig hci0 up")
    os.system("sudo hciconfig hci0 piscan") # Cho phép tìm thấy (Discoverable)
    os.system("sudo sdptool add SP")        # Đăng ký Serial Port Profile
    time.sleep(1)
    print(">>> ✅ Cấu hình xong.")

def main():
    setup_bluetooth_hardware()

    bd_addr = get_local_bdaddr()
    if not bd_addr:
        print("❌ LỖI: Không tìm thấy địa chỉ MAC Bluetooth.")
        print("   Hãy kiểm tra lại xem Pi có Bluetooth không hoặc đã bật chưa.")
        return

    port = 1
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    
    # Cho phép sử dụng lại cổng ngay lập tức nếu code bị tắt đột ngột
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        print(f">>> 🔵 Đang khởi tạo Server tại: {bd_addr} (Channel {port})")
        sock.bind((bd_addr, port))
        sock.listen(1)
        print(">>> ⏳ Đang chờ kết nối từ điện thoại...")
        print("   (Hãy mở App và kết nối tới Raspberry Pi ngay bây giờ)")

        while True:
            client_sock, address = sock.accept()
            print(f"\n>>> ✅ ĐÃ KẾT NỐI VỚI: {address}")
            print(">>> 📡 Đang lắng nghe tín hiệu (Nhấn Ctrl+C để thoát)...\n")

            # Gửi tin nhắn chào mừng (để test chiều gửi đi)
            try:
                client_sock.send(b"Hello from Pi!\r\n")
            except:
                pass

            try:
                while True:
                    data = client_sock.recv(1024)
                    if not data:
                        break
                    
                    raw_data = data.decode("utf-8").strip() # Giữ nguyên cả chuỗi để xem
                    upper_data = raw_data.upper()
                    
                    # Mô phỏng logic xử lý
                    print(f"📩 Nhận: '{raw_data}'", end=" | ")
                    print("") # Xuống dòng

            except OSError:
                print("\n>>> ⚠️ Mất kết nối đột ngột.")
            
            client_sock.close()
            print("\n>>> ⏳ Đang chờ kết nối lại...")

    except KeyboardInterrupt:
        print("\n>>> 🛑 Đã dừng chương trình.")
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
    finally:
        sock.close()
        print(">>> Đã đóng Socket.")

if __name__ == "__main__":
    main()