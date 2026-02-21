import os
import time
import socket
import subprocess
from globals import STOP_EVENT
from system_logs import add_system_log
from uart_handle import robot

def get_local_bdaddr():
    """Lấy địa chỉ MAC của Bluetooth Adapter (hci0)"""
    try:
        # Đọc từ file hệ thống (nhanh và chuẩn nhất trên Linux)
        with open('/sys/class/bluetooth/hci0/address', 'r') as f:
            return f.read().strip()
    except:
        try:
            # Dùng lệnh hciconfig nếu file không tồn tại
            res = subprocess.check_output("hciconfig hci0 | grep 'BD Address' | awk '{print $3}'", shell=True)
            return res.decode().strip()
        except:
            return None

def bluetooth_server_thread():
    """Lắng nghe kết nối Bluetooth và duy trì trạng thái di chuyển"""
    server_sock = None
    try:
        # 1. Cấu hình Bluetooth
        os.system("sudo hciconfig hci0 up")
        os.system("sudo hciconfig hci0 piscan")
        os.system("sudo sdptool add SP")
        time.sleep(1)

        bd_addr = get_local_bdaddr()
        if not bd_addr:
            print("❌ Không tìm thấy địa chỉ MAC Bluetooth")
            add_system_log("Lỗi: Không tìm thấy Bluetooth MAC", "error", "BLUETOOTH")
            return

        print(f">>> 🔵 Bluetooth Server đang chạy tại {bd_addr} (Channel 1)")

        server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((bd_addr, 1)) 
        server_sock.listen(1)

        add_system_log(f"BT Server chạy tại {bd_addr}", "info", "BLUETOOTH")

        while not STOP_EVENT.is_set():
            try:
                client_sock, address = server_sock.accept()
                print(f">>> 🔵 Đã kết nối Bluetooth với {address}")
                add_system_log(f"Thiết bị {address} đã kết nối", "info", "BLUETOOTH")
                
                client_sock.settimeout(0.1) 
                
                try:
                    client_sock.send(b"Connected\r\n")
                except:
                    pass

                # Biến lưu trạng thái hiện tại (lastchar)
                # None = Đứng yên, 'F' = Tiến, 'B' = Lùi...
                current_state = None 

                while True:
                    try:
                        # 1. Cố gắng nhận dữ liệu mới
                        data = client_sock.recv(1024)
                        if not data:
                            break # Mất kết nối
                        
                        command_str = data.decode("utf-8").strip().upper()
                        
                        # 2. Cập nhật trạng thái (lastchar)
                        if 'S' in command_str:
                            print(">>> 🔵 BLE: STOP (S)")
                            robot.send("STOP", 0, 0, force=True)
                            current_state = None 
                        elif command_str:
                            # Lấy ký tự hợp lệ cuối cùng (F, B, L, R)
                            valid_cmds = [c for c in command_str if c in 'FBLR']
                            if valid_cmds:
                                current_state = valid_cmds[-1]
                                print(f">>> 🔵 BLE: Start State [{current_state}]")

                    except socket.timeout:
                        # Không có dữ liệu mới -> Không làm gì cả, giữ nguyên current_state
                        pass
                    except OSError:
                        break # Lỗi kết nối thực sự

                    if current_state:
                        speed = 200
                        cmd_arduino = None
                        duration = 100 

                        if current_state == 'F': cmd_arduino = "FW"
                        elif current_state == 'B': cmd_arduino = "BW"
                        elif current_state == 'L': cmd_arduino = "TL"; speed = 230
                        elif current_state == 'R': cmd_arduino = "TR"; speed = 230
                        
                        if cmd_arduino:
                            # Gửi lệnh duy trì chuyển động
                            robot.send(cmd_arduino, speed, duration, force=True)
                            add_system_log(f"BLE: {cmd_arduino} @ {speed}", "info", "BLUETOOTH")
                    else:
                        robot.send("STOP", 0, 0, force=True)
                    # Ngủ nhẹ để không chiếm 100% CPU
                    time.sleep(0.05)

            except Exception as e:
                print(f"❌ Lỗi kết nối Client: {e}")
            finally:
                try:
                    client_sock.close()
                    print(">>> 🔵 Client ngắt kết nối")
                except:
                    pass

    except Exception as e:
        print(f"❌ Lỗi Server: {e}")
    finally:
        if server_sock:
            server_sock.close()