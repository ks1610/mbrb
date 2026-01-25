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
       

// ---------- PARAMETERS ----------
const float RIGHT_COMP = 0.85f;     
const int BASE_SPEED = 200;          
const int TURN_SPEED = 200;          

// Thời gian quay
const unsigned long TURN_90_MS  = 1585; 
const unsigned long TURN_180_MS = 3048; 
const unsigned long DIAG_45_MS  = 9000; 

// ---------- Soft PWM settings ----------
const unsigned long SOFT_PWM_FREQ_HZ = 500UL; 
const unsigned long SOFT_PWM_PERIOD_US = 1000000UL / SOFT_PWM_FREQ_HZ;
volatile uint8_t leftDuty = 0;   
volatile uint8_t rightDuty = 0;  


// ---------- Sequence ----------
enum Action {
  FORWARD,
  BACKWARD,
  LEFT_TURN,
  RIGHT_TURN,
  TURN_180,
  DIAG_LEFT,
  DIAG_RIGHT,
  STOP_ACTION
};

struct Step {
  Action action;
  unsigned long duration; // ms
};

Step sequence[] = {
  { FORWARD, 12300 },         // 0
  { LEFT_TURN, TURN_90_MS },  // 1
  { FORWARD, 14500 },         // 2
  { RIGHT_TURN, TURN_90_MS }, // 3
  { FORWARD, 2600 },          // 5
  { BACKWARD, 3000 },         // 7
  { TURN_180, TURN_180_MS },  // 8
  { FORWARD, 9000 },          // 9
  { BACKWARD, 3000 },         //11
  { TURN_180, TURN_180_MS },  //12
  { DIAG_LEFT, DIAG_45_MS },  //13
  { BACKWARD, 5000 },         //15
  { TURN_180, TURN_180_MS },  //16
  { DIAG_LEFT, DIAG_45_MS },  //17
  { BACKWARD, 5000 },         //19
  { TURN_180, TURN_180_MS },  //20
  { DIAG_LEFT, DIAG_45_MS }   //21 
};
const int SEQ_COUNT = sizeof(sequence)/sizeof(sequence[0]);

// ---------- Global variables ----------
uint8_t seqIndex = 0;
unsigned long stepStart = 0;
bool seqRunning = false;

// ---------- Motor helpers ----------
void setLeftDirectionForward() {
  digitalWrite(L_IN1, 1); digitalWrite(L_IN2, 0);
  digitalWrite(L_IN3, 0); digitalWrite(L_IN4, 1);
}
void setRightDirectionForward() {
  digitalWrite(R_IN1, 1); digitalWrite(R_IN2, 0);
  digitalWrite(R_IN3, 0); digitalWrite(R_IN4, 1);
}
void setLeftDirectionBackward() {
  digitalWrite(L_IN1, 0); digitalWrite(L_IN2, 1);
  digitalWrite(L_IN3, 1); digitalWrite(L_IN4, 0);
}
void setRightDirectionBackward() {
digitalWrite(R_IN1, 0); digitalWrite(R_IN2, 1);
  digitalWrite(R_IN3, 1); digitalWrite(R_IN4, 0);
}
void stopLeftMotors() {
  digitalWrite(L_IN1, 0); digitalWrite(L_IN2, 0);
  digitalWrite(L_IN3, 0); digitalWrite(L_IN4, 0);
}

void stopRightMotors() {
  digitalWrite(R_IN1, 0); digitalWrite(R_IN2, 0);
  digitalWrite(R_IN3, 0); digitalWrite(R_IN4, 0);
}

// ---------- Set motors ----------
void setMotors(int leftSpeed, int rightSpeed) {
  if (leftSpeed > 0) {
    setLeftDirectionForward();
    leftDuty = constrain(leftSpeed, 0, 255);
  } else if (leftSpeed < 0) {
    setLeftDirectionBackward();
    leftDuty = constrain(-leftSpeed, 0, 255);
  } else {
    stopLeftMotors();
    leftDuty = 0;
  }

  float r = rightSpeed * RIGHT_COMP;
  if (r > 0.0f) {
    setRightDirectionForward();
    rightDuty = constrain((int)r, 0, 255);
  } else if (r < 0.0f) {
    setRightDirectionBackward();
    rightDuty = constrain((int)(-r), 0, 255);
  } else {
    stopRightMotors();
    rightDuty = 0;
  }
}

void stopBoth() {
  leftDuty = 0; rightDuty = 0;
  stopLeftMotors();
  stopRightMotors();
  digitalWrite(EN_LEFT, 0);
  digitalWrite(EN_RIGHT, 0);
}

// ---------- Software PWM ----------
void softPwmUpdate() {
  unsigned long phase = micros() % SOFT_PWM_PERIOD_US;
  unsigned long left_on_us  = ((unsigned long)leftDuty  * SOFT_PWM_PERIOD_US) / 255UL;
  unsigned long right_on_us = ((unsigned long)rightDuty * SOFT_PWM_PERIOD_US) / 255UL;

  digitalWrite(EN_LEFT,  (leftDuty  > 0 && phase < left_on_us)  ? 1 : 0);
  digitalWrite(EN_RIGHT, (rightDuty > 0 && phase < right_on_us) ? 1 : 0);
}

// ---------- Run action ----------
void runAction(Action a) {
  switch (a) {
    case FORWARD:       setMotors(BASE_SPEED, BASE_SPEED); Serial.println("ACTION: FORWARD"); break;
    case BACKWARD:      setMotors(-BASE_SPEED, -BASE_SPEED); Serial.println("ACTION: BACKWARD"); break;
    case LEFT_TURN:     setMotors(-TURN_SPEED, TURN_SPEED); Serial.println("ACTION: LEFT_TURN (90°)"); break;
    case RIGHT_TURN:    setMotors(TURN_SPEED, -TURN_SPEED); Serial.println("ACTION: RIGHT_TURN (90°)"); break;
    case TURN_180:      setMotors(-TURN_SPEED, TURN_SPEED); Serial.println("ACTION: TURN_180 (180°)"); break;
    case DIAG_LEFT:     setMotors(BASE_SPEED * 0.7, BASE_SPEED); Serial.println("ACTION: DIAG_LEFT (45°)"); break;
    case DIAG_RIGHT:    setMotors(BASE_SPEED, BASE_SPEED * 0.7); Serial.println("ACTION: DIAG_RIGHT (45°)"); break;
    case STOP_ACTION:     stopBoth(); Serial.println("ACTION: STOP"); break;
    default: stopBoth(); break;
  }
}

// ---------- Setup ----------
void setupPins() {
  pinMode(L_IN1, OUTPUT); pinMode(L_IN2, OUTPUT);
  pinMode(L_IN3, OUTPUT); pinMode(L_IN4, OUTPUT);
  pinMode(R_IN1, OUTPUT); pinMode(R_IN2, OUTPUT);
  pinMode(R_IN3, OUTPUT); pinMode(R_IN4, OUTPUT);
  pinMode(EN_LEFT, OUTPUT); pinMode(EN_RIGHT, OUTPUT);
}

// ---------- Basic movement functions ----------
void moveForward(int speed = BASE_SPEED) {
  setMotors(speed, speed);
}

void moveBackward(int speed = BASE_SPEED) {
  setMotors(-speed, -speed);
}

void turnLeft(int speed = TURN_SPEED) {
  setMotors(-speed, speed);
}

void turnRight(int speed = TURN_SPEED) {
  setMotors(speed, -speed);
}

void stopMove() {
  stopBoth();
}

void setup() {
  Serial.begin(115200);
  setupPins();
  delay(500);

  seqIndex = 0;
  stepStart = millis();
  seqRunning = true;
  runAction(sequence[0].action);

  Serial.println("Sequence started.");
}

// ---------- Main loop ----------
void loop() {
  softPwmUpdate();

  if (!seqRunning) return;

  unsigned long now = millis();
  Step cur = sequence[seqIndex];

  if (cur.duration > 0 && now - stepStart >= cur.duration) {
    seqIndex++;
  } else if (cur.duration == 0) {
    seqIndex++;
  } else {
    return;
  }

  if (seqIndex >= SEQ_COUNT) {
    seqRunning = false;
    stopBoth();
    Serial.println("Sequence finished at step 21.");
  } else {
    stepStart = now;
    runAction(sequence[seqIndex].action);
  }
}