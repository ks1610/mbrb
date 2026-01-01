import speech_recognition as sr
import google.generativeai as genai
import asyncio
import edge_tts
import pygame
import os
import paho.mqtt.publish as publish # Thư viện gửi MQTT

# ====== CẤU HÌNH MQTT (Giống hệt bên Flask) ======
MQTT_BROKER = "broker.hivemq.com"
TOPIC_CMD = "raspi/esp32/relay"  # Topic gửi lệnh xuống ESP32

# ====== CẤU HÌNH AI ======
GEMINI_API_KEY = "DÁN_API_KEY_CỦA_BẠN_VÀO_ĐÂY"
VOICE = "vi-VN-HoaiMyNeural" 

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# --- Hàm nói (Text to Speech) ---
async def speak(text):
    print(f"Bot: {text}")
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save("response.mp3")
    pygame.mixer.init()
    pygame.mixer.music.load("response.mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    pygame.mixer.quit()
    if os.path.exists("response.mp3"):
        os.remove("response.mp3")

# --- Hàm nghe (Speech to Text) ---
def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n--- Đang nghe lệnh... ---")
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            text = r.recognize_google(audio, language="vi-VN")
            print(f"Bạn nói: {text}")
            return text.lower()
        except:
            return None

# --- Hàm xử lý lệnh điều khiển thiết bị (Smart Home) ---
def process_smarthome_command(text):
    """
    Hàm này kiểm tra xem người dùng có muốn bật tắt thiết bị không.
    Trả về True nếu đã xử lý lệnh, False nếu không phải lệnh điều khiển.
    """
    cmd_msg = None
    response_text = ""

    # Logic xử lý đơn giản dựa trên từ khóa
    if "bật" in text and "đèn 1" in text:
        cmd_msg = "1:on"
        response_text = "Đã bật đèn số 1"
    elif "tắt" in text and "đèn 1" in text:
        cmd_msg = "1:off"
        response_text = "Đã tắt đèn số 1"
        
    elif "bật" in text and "đèn 2" in text:
        cmd_msg = "2:on"
        response_text = "Đã bật đèn số 2"
    elif "tắt" in text and "đèn 2" in text:
        cmd_msg = "2:off"
        response_text = "Đã tắt đèn số 2"

    # Nếu phát hiện lệnh điều khiển
    if cmd_msg:
        try:
            print(f"[MQTT] Gửi lệnh: {cmd_msg} tới {TOPIC_CMD}")
            publish.single(TOPIC_CMD, cmd_msg, hostname=MQTT_BROKER)
            return response_text
        except Exception as e:
            print(f"Lỗi MQTT: {e}")
            return "Có lỗi khi kết nối với thiết bị."
            
    return None # Không tìm thấy lệnh điều khiển

# --- Vòng lặp chính ---
async def main():
    await speak("Hệ thống đã sẵn sàng. Bạn muốn bật tắt gì không?")
    
    while True:
        user_input = listen()
        
        if user_input:
            # 1. Kiểm tra xem có phải lệnh điều khiển Relay không
            smarthome_response = process_smarthome_command(user_input)
            
            if smarthome_response:
                # Nếu là lệnh bật tắt, thực hiện ngay và báo cáo
                await speak(smarthome_response)
            
            # 2. Kiểm tra lệnh dừng
            elif "tạm biệt" in user_input or "dừng lại" in user_input:
                await speak("Chào tạm biệt.")
                break
                
            # 3. Nếu không phải lệnh điều khiển, hỏi Gemini (Chat GPT)
            else:
                try:
                    prompt = f"Trả lời cực ngắn gọn (dưới 20 từ) bằng tiếng Việt: {user_input}"
                    response = model.generate_content(prompt)
                    await speak(response.text)
                except:
                    await speak("Tôi đang mất kết nối với não bộ.")

if __name__ == "__main__":
    asyncio.run(main())import speech_recognition as sr
import google.generativeai as genai
import asyncio
import edge_tts
import pygame
import os
import paho.mqtt.publish as publish # Thư viện gửi MQTT

# ====== CẤU HÌNH MQTT (Giống hệt bên Flask) ======
MQTT_BROKER = "broker.hivemq.com"
TOPIC_CMD = "raspi/esp32/relay"  # Topic gửi lệnh xuống ESP32

# ====== CẤU HÌNH AI ======
GEMINI_API_KEY = "DÁN_API_KEY_CỦA_BẠN_VÀO_ĐÂY"
VOICE = "vi-VN-HoaiMyNeural" 

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# --- Hàm nói (Text to Speech) ---
async def speak(text):
    print(f"Bot: {text}")
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save("response.mp3")
    pygame.mixer.init()
    pygame.mixer.music.load("response.mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    pygame.mixer.quit()
    if os.path.exists("response.mp3"):
        os.remove("response.mp3")

# --- Hàm nghe (Speech to Text) ---
def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n--- Đang nghe lệnh... ---")
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            text = r.recognize_google(audio, language="vi-VN")
            print(f"Bạn nói: {text}")
            return text.lower()
        except:
            return None

# --- Hàm xử lý lệnh điều khiển thiết bị (Smart Home) ---
def process_smarthome_command(text):
    """
    Hàm này kiểm tra xem người dùng có muốn bật tắt thiết bị không.
    Trả về True nếu đã xử lý lệnh, False nếu không phải lệnh điều khiển.
    """
    cmd_msg = None
    response_text = ""

    # Logic xử lý đơn giản dựa trên từ khóa
    if "bật" in text and "đèn 1" in text:
        cmd_msg = "1:on"
        response_text = "Đã bật đèn số 1"
    elif "tắt" in text and "đèn 1" in text:
        cmd_msg = "1:off"
        response_text = "Đã tắt đèn số 1"
        
    elif "bật" in text and "đèn 2" in text:
        cmd_msg = "2:on"
        response_text = "Đã bật đèn số 2"
    elif "tắt" in text and "đèn 2" in text:
        cmd_msg = "2:off"
        response_text = "Đã tắt đèn số 2"

    # Nếu phát hiện lệnh điều khiển
    if cmd_msg:
        try:
            print(f"[MQTT] Gửi lệnh: {cmd_msg} tới {TOPIC_CMD}")
            publish.single(TOPIC_CMD, cmd_msg, hostname=MQTT_BROKER)
            return response_text
        except Exception as e:
            print(f"Lỗi MQTT: {e}")
            return "Có lỗi khi kết nối với thiết bị."
            
    return None # Không tìm thấy lệnh điều khiển

# --- Vòng lặp chính ---
async def main():
    await speak("Hệ thống đã sẵn sàng. Bạn muốn bật tắt gì không?")
    
    while True:
        user_input = listen()
        
        if user_input:
            # 1. Kiểm tra xem có phải lệnh điều khiển Relay không
            smarthome_response = process_smarthome_command(user_input)
            
            if smarthome_response:
                # Nếu là lệnh bật tắt, thực hiện ngay và báo cáo
                await speak(smarthome_response)
            
            # 2. Kiểm tra lệnh dừng
            elif "tạm biệt" in user_input or "dừng lại" in user_input:
                await speak("Chào tạm biệt.")
                break
                
            # 3. Nếu không phải lệnh điều khiển, hỏi Gemini
            else:
                try:
                    prompt = f"Trả lời cực ngắn gọn (dưới 20 từ) bằng tiếng Việt: {user_input}"
                    response = model.generate_content(prompt)
                    await speak(response.text)
                except:
                    await speak("Tôi đang mất kết nối với não bộ.")

if __name__ == "__main__":
    asyncio.run(main())
