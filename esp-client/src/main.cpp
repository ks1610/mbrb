#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>

// ====== Wi-Fi Info ======
const char* ssid = "Hien-Khanh-Ha";
const char* password = "khanhha@123";

// ====== MQTT Broker ======
const char* mqtt_server = "broker.hivemq.com";
const char* topic_sub = "raspi/esp32/relay";   // Subscribe for relay commands
const char* topic_pub = "esp32/raspi/data";    // Publish temperature/humidity

// ====== Pin Setup ======
#define RELAY1_PIN 25
#define RELAY2_PIN 26
#define RELAY3_PIN 33
#define RELAY4_PIN 32  

#define DHT_PIN 27
#define DHT_TYPE DHT11

WiFiClient espClient;
PubSubClient client(espClient);
DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastPublish = 0;

// ====== Connect to Wi-Fi ======
void setup_wifi() {
  Serial.print("Connecting to WiFi: ");
  WiFi.begin(ssid, password);
  uint8_t tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 30) {
    delay(200);
    Serial.print(".");
    tries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi failed, restarting...");
    ESP.restart();
  }
}

// ====== MQTT Message Callback ======
void callback(char* topic, byte* payload, unsigned int length) {
  String msg;
  msg.reserve(length);
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  msg.trim();
  Serial.print("MQTT cmd received: ");
  Serial.println(msg);

  // Format expected: "relayNumber:state", e.g. "1:on"
  int sep = msg.indexOf(':');
  if (sep == -1) return;

  int relayNum = msg.substring(0, sep).toInt();
  String state = msg.substring(sep + 1);

  int pin = -1;
  if (relayNum == 1) pin = RELAY1_PIN;
  else if (relayNum == 2) pin = RELAY2_PIN;
  else if (relayNum == 3) pin = RELAY3_PIN;
  else if (relayNum == 4) pin = RELAY4_PIN;

  if (pin != -1) {
    if(pin == RELAY2_PIN){
      digitalWrite(pin, state == "on" ? LOW : HIGH);
      Serial.printf("Relay %d turned %s\n", relayNum, state.c_str());
    }
    else{
      digitalWrite(pin, state == "on" ? HIGH : LOW);
      Serial.printf("Relay %d turned %s\n", relayNum, state.c_str());
    }
  }
}

// ====== MQTT Reconnect ======
void reconnect() {
  while (!client.connected()) {
    if (client.connect("ESP32_Client")) {
      client.subscribe(topic_sub);
      Serial.println("MQTT connected & subscribed!");
      Serial.print("Subscribed to: ");
      Serial.println(topic_sub);
    } else {
      delay(1000);  
    }
  }
}

// ====== Setup ======
void setup() {
  Serial.begin(115200);

  // Setup relay pins
  pinMode(RELAY1_PIN, OUTPUT);
  pinMode(RELAY2_PIN, OUTPUT);
  pinMode(RELAY3_PIN, OUTPUT);
  pinMode(RELAY4_PIN, OUTPUT);
  digitalWrite(RELAY1_PIN, LOW);
  digitalWrite(RELAY2_PIN, LOW);
  digitalWrite(RELAY3_PIN, LOW);
  digitalWrite(RELAY4_PIN, LOW);

  dht.begin();
  setup_wifi();

  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
}

// ====== Main Loop ======
void loop() {
  if (!client.connected()) reconnect();
  client.loop();  // Keep MQTT alive

  // Publish temperature & humidity every 2 seconds
  unsigned long now = millis();
  if (now - lastPublish > 2000) {
    lastPublish = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();

    if (!isnan(t) && !isnan(h)) {
      String payload = String(t, 1) + "," + String(h, 1);
      client.publish(topic_pub, payload.c_str());
      Serial.println("Published: " + payload);
    }
  }
}
