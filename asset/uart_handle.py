import serial
import time

class RobotSerial:
    """Manages serial communication with Arduino with auto-reconnect"""
    
    def __init__(self, port='/dev/ttyUSB0', baud=115200):
        self.port = port
        self.baud = baud
        self.ser = None
        self.last_cmd_time = 0
        self.cmd_interval = 0.15  # Command throttling interval
        self.connect()
    
    def connect(self):
        """Establish serial connection"""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            print(f">>> ✅ Arduino connected on {self.port}")
        except:
            self.ser = None
    
    def send(self, cmd, speed, duration, force=False):
        """Send command to Arduino with throttling"""
        current_time = time.time()
        
        # Prioritize STOP commands or forced commands
        if cmd != "STOP" and not force:
            if current_time - self.last_cmd_time < self.cmd_interval:
                return False
        
        # Reconnect if needed
        if not self.ser or not self.ser.is_open:
            self.connect()
        
        if self.ser:
            try:
                msg = f"{cmd}:{int(speed)}:{int(duration)}\n"
                self.ser.write(msg.encode())
                if cmd != "STOP":
                    print(f">>> [SERIAL] {msg.strip()}")
                self.last_cmd_time = current_time
                return True
            except:
                return False
        
        return False


# Initialize robot serial connection
robot = RobotSerial()