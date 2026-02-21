import paho.mqtt.client as mqtt
import os

MQTT_BROKER = os.getenv('MQTT_BROKER', 'broker.hivemq.com')
TOPIC_CMD = "raspi/esp32/relay"

mqtt_client = mqtt.Client()

try:
    mqtt_client.connect(MQTT_BROKER, 1883, 60)
    mqtt_client.loop_start()
except:
    print("❌ Lỗi kết nối MQTT")