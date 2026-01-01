from flask import Flask, request, redirect, url_for, session, render_template, jsonify
import paho.mqtt.publish as publish
import paho.mqtt.client as mqtt
import threading

app = Flask(__name__)
app.secret_key = "mysecretkey"

# ====== MQTT SETUP ======
MQTT_BROKER = "broker.hivemq.com"
TOPIC_CMD = "raspi/esp32/relay"  # Updated topic (ESP32 should subscribe here)
TOPIC_DATA = "esp32/raspi/data"  # ESP32 publishes temperature/humidity

# Store latest readings
sensor_data = {"temperature": "--", "humidity": "--"}

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        temp, hum = payload.split(",")
        sensor_data["temperature"] = temp
        sensor_data["humidity"] = hum
    except Exception as e:
        print("Error parsing data:", e)

def mqtt_listener():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, 1883, 60)
    client.subscribe(TOPIC_DATA)
    client.loop_forever()

threading.Thread(target=mqtt_listener, daemon=True).start()

# ====== LOGIN SYSTEM ======
PASSWORD = "1"

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['password'] == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid password")
    return render_template('login.html', error=None)

# ====== DASHBOARD ======
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ====== CONTROL ENDPOINT ======
@app.route('/control/<relay>/<state>')
def control(relay, state):
    if relay not in ["1", "2", "3", "4"] or state not in ["on", "off"]:
        return "Invalid command"
    try:
        message = f"{relay}:{state}"  # Example: "1:on"
        publish.single(TOPIC_CMD, message, hostname=MQTT_BROKER)
        print(f"[MQTT] Published -> {message}")
        return f"Relay {relay} turned {state}"
    except Exception as e:
        print("Publish failed:", e)
        return "MQTT error"

@app.route('/data')
def get_data():
    return jsonify(sensor_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
