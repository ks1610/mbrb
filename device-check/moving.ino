// ---------- PIN MAP ----------
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

void moveMotors(
  bool m1_in1, bool m1_in2, bool m2_in1, bool m2_in2,
  bool m1_in3, bool m1_in4, bool m2_in3, bool m2_in4,
  int speedA, int speedB
) {
  digitalWrite(L_IN1, m1_in1);
  digitalWrite(L_IN3, m1_in2);
  digitalWrite(L_IN2, m2_in1);
  digitalWrite(L_IN4, m2_in2);
  digitalWrite(R_IN1, m1_in3);
  digitalWrite(R_IN3, m1_in4);
  digitalWrite(R_IN2, m2_in3);
  digitalWrite(R_IN4, m2_in4);
  analogWrite(EN_LEFT, speedA);
  analogWrite(EN_RIGHT, speedB);
}

// ---------- Setup ----------
void setupPins() {
  pinMode(L_IN1, OUTPUT); pinMode(L_IN2, OUTPUT);
  pinMode(L_IN3, OUTPUT); pinMode(L_IN4, OUTPUT);
  pinMode(R_IN1, OUTPUT); pinMode(R_IN2, OUTPUT);
  pinMode(R_IN3, OUTPUT); pinMode(R_IN4, OUTPUT);
  pinMode(EN_LEFT, OUTPUT); pinMode(EN_RIGHT, OUTPUT);
}

void setup(){
  Serial.begin(115200);
  setupPins();
}

void loop(){

}

/*
  Serial.println(" -> Đi Thẳng");
  moveMotors(
    0, 1, 1, 0,  // L298N_no1
    0, 1, 1, 0,  // L298N_no2
    80, 80       // Speeds
  );

  Serial.println(" -> Quay Trái");
  moveMotors(
    0, 1, 0, 0,  // L298N_no1
    1, 0, 0, 0,  // L298N_no2
    200, 200       // Speeds
  );

  Serial.println(" -> QQuay Phải");
  moveMotors(
    1, 0, 0, 0,  // L298N_no1
    0, 1, 0, 0,  // L298N_no2
    200, 200       // Speeds
  );

  Serial.println(" -> Đi Lùi");
  moveMotors(
    1, 0, 0, 1,  // L298N_no1
    1, 0, 0, 1,  // L298N_no2
    80, 80       // Speeds
  );
  Serial.println(" -> Dừng");
  moveMotors(
    0, 0, 0, 0,  // L298N_no1
    0, 0, 0, 0,  // L298N_no2
    0, 0       // Speeds
  );

*/