import serial
import time

# 🔧 CHỈNH LẠI CHO ĐÚNG
SERIAL_PORT = '/dev/ttyUSB0'   # Raspberry Pi: /dev/ttyUSB0 hoặc /dev/ttyACM0
# Windows: 'COM3', 'COM4', ...
BAUDRATE = 115200

# Mở UART
ser = serial.Serial(
    port=SERIAL_PORT,
    baudrate=BAUDRATE,
    timeout=1
)

time.sleep(2)  # Chờ Arduino reset

def send_command(cmd, speed, duration):
    """
    cmd: 'FW', 'BW', 'TL', 'TR'
    speed: 0-255
    duration: ms
    """
    command = f"{cmd}:{speed}:{duration}\n"
    ser.write(command.encode('utf-8'))
    print("Sent:", command.strip())

while True:
    # ---------- TEST ----------
    send_command("FW", 150, 500)   # Tiến 0.5s
    time.sleep(1)
    send_command("TR", 180, 300)   # Quay phải
    time.sleep(1)
    send_command("TL", 180, 300)   # Quay trái
    time.sleep(1)
    send_command("BW", 120, 400)   # Lùi
    ser.close()
