// ---------- PIN MAP (GIỮ NGUYÊN CỦA BẠN) ----------
const uint8_t EN_LEFT = 9;   
const uint8_t L_IN1 = 2;
const uint8_t L_IN2 = 3;
const uint8_t L_IN3 = 4;
const uint8_t L_IN4 = 5;

const uint8_t EN_RIGHT = 10; 
const uint8_t R_IN1 = 6;
const uint8_t R_IN2 = 7;
const uint8_t R_IN3 = 8;
const uint8_t R_IN4 = 11;

// Biến lưu trữ lệnh từ Serial
String commandString = "";
bool newCommand = false;

void setup() {
  Serial.begin(115200); // Tốc độ baud phải khớp với Raspberry Pi
  
  pinMode(EN_LEFT, OUTPUT);
  pinMode(L_IN1, OUTPUT); pinMode(L_IN2, OUTPUT);
  pinMode(L_IN3, OUTPUT); pinMode(L_IN4, OUTPUT);
  
  pinMode(EN_RIGHT, OUTPUT);
  pinMode(R_IN1, OUTPUT); pinMode(R_IN2, OUTPUT);
  pinMode(R_IN3, OUTPUT); pinMode(R_IN4, OUTPUT);
  
  stopMove(); // Dừng khi khởi động
}

void stopMove() {
  digitalWrite(R_IN1, 0); digitalWrite(R_IN2, 0);
  digitalWrite(R_IN3, 0); digitalWrite(R_IN4, 0);
  digitalWrite(L_IN1, 0); digitalWrite(L_IN2, 0);
  digitalWrite(L_IN3, 0); digitalWrite(L_IN4, 0);
  analogWrite(EN_LEFT, 0);
  analogWrite(EN_RIGHT, 0);
}

// Các hàm di chuyển (Đã sửa lại để nhận tham số linh hoạt)
void forward(int speed, int time){
  digitalWrite(R_IN1, 0); digitalWrite(R_IN2, 1);
  digitalWrite(R_IN3, 1); digitalWrite(R_IN4, 0);
  digitalWrite(L_IN1, 0); digitalWrite(L_IN2, 1);
  digitalWrite(L_IN3, 1); digitalWrite(L_IN4, 0);
  analogWrite(EN_LEFT, speed);
  analogWrite(EN_RIGHT, speed);
  delay(time);
  stopMove(); // Dừng lại sau khi hết thời gian delay
}


void backward(int speed, float time){
  digitalWrite(R_IN1, 1); digitalWrite(R_IN2, 0);
  digitalWrite(R_IN3, 0); digitalWrite(R_IN4, 1);
  digitalWrite(L_IN1, 1); digitalWrite(L_IN2, 0);
  digitalWrite(L_IN3, 0); digitalWrite(L_IN4, 1);
  digitalWrite(EN_LEFT, speed);
  digitalWrite(EN_RIGHT, speed);
  delay(time);
  stopMove();
}
void rightturn(int speed, float time){
  digitalWrite(R_IN1, 1); digitalWrite(R_IN2, 0);
  digitalWrite(R_IN3, 1); digitalWrite(R_IN4, 0);
  digitalWrite(L_IN1, 1); digitalWrite(L_IN2, 0);
  digitalWrite(L_IN3, 1); digitalWrite(L_IN4, 0);
  digitalWrite(EN_LEFT, speed);
  digitalWrite(EN_RIGHT, speed);
  delay(time);
  stopMove();
}
void leftturn(int speed, float time){
  digitalWrite(R_IN1, 0); digitalWrite(R_IN2, 1);
  digitalWrite(R_IN3, 0); digitalWrite(R_IN4, 1);
  digitalWrite(L_IN1, 0); digitalWrite(L_IN2, 1);
  digitalWrite(L_IN3, 0); digitalWrite(L_IN4, 1);
  digitalWrite(EN_LEFT, speed);
  digitalWrite(EN_RIGHT, speed);
  delay(time);
  stopMove();
}

void loop() {
  // Đọc dữ liệu từ Serial (Giao thức: CMD:SPEED:TIME\n)
  // Ví dụ: FW:150:200 (Tiến, tốc độ 150, trong 200ms)
  if (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    
    // Tách chuỗi
    int firstColon = data.indexOf(':');
    int secondColon = data.lastIndexOf(':');
    
    if (firstColon > 0) {
      String cmd = data.substring(0, firstColon);
      String s_speed = data.substring(firstColon + 1, secondColon);
      String s_time = data.substring(secondColon + 1);
      
      int speed = s_speed.toInt();
      int time = s_time.toInt();
      
      // Giới hạn tốc độ PWM (0-255)
      if (speed > 255) speed = 255;
      if (speed < 0) speed = 0;

      // Thực thi lệnh
      if (cmd == "FW") forward(speed, time);
      else if (cmd == "BW") backward(speed, time);
      else if (cmd == "TL") leftturn(speed, time);
      else if (cmd == "TR") rightturn(speed, time);
      else stopMove();
    }
  }
  // rightturn(180, 1000);
}