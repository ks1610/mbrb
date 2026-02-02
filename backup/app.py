import asyncio
import edge_tts
import pygame
import speech_recognition as sr
import ollama  
import paho.mqtt.publish as publish
import sys
import os
import re
from time import sleep

# --- CẤU HÌNH GPIO ---
os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'
from gpiozero import OutputDevice

# ====== 1. CẤU HÌNH NGƯỜI DÙNG ======
MQTT_BROKER = "broker.hivemq.com"
TOPIC_CMD = "raspi/esp32/relay"

MIC_DEVICE_INDEX = 0 
AMP_PIN = 4 

LOCAL_MODEL = "qwen2.5:1.5b" 

VOICE_NAME = "vi-VN-HoaiMyNeural"
TTS_PITCH = '+40Hz'
TTS_RATE = '+15%'

SYS_INSTRUCT = """
Bạn là trợ lý ảo tên Hanh, tính cách nhí nhảnh, đáng yêu và rất quan tâm đến người dùng.

QUY TẮC XỬ LÝ TUYỆT ĐỐI:
1. NẾU LÀ LỆNH ĐIỀU KHIỂN (Bật/Tắt đèn):
   - CHỈ trả về mã lệnh duy nhất: [CMD:id:state]
   - Ví dụ: [CMD:1:on] hoặc [CMD:2:off]
   - Không nói thêm bất kỳ lời nào.

2. NẾU LÀ TRÒ CHUYỆN:
   - Trả lời bằng tiếng Việt, giọng điệu ngọt ngào, thân thiện.
   - KHÔNG dùng icon, emoji (😊, 👋,...) để tránh lỗi giọng đọc.
   - LUÔN KẾT THÚC bằng một câu hỏi mở liên quan đến chủ đề vừa nói để gợi mở câu chuyện tiếp theo.
   - Độ dài: Dưới 40 từ.

Ví dụ hội thoại mẫu:
- User: "Hôm nay trời nóng quá."
- Bot: "Dạ vâng, nóng thế này bạn nhớ uống nhiều nước nhé. Hay bạn có muốn bật quạt cho mát không?"
"""

# ====== 2. BỘ LỌC LỖI ALSA ======
from ctypes import *
try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    def py_error_handler(filename, line, function, err, fmt):
        pass
    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = cdll.LoadLibrary('libasound.so')
    asound.snd_lib_error_set_handler(c_error_handler)
except:
    pass

# ====== 3. KHỞI TẠO ======
try:
    print(f"\n>>> ⏳ Đang kết nối với Local AI ({LOCAL_MODEL})...")
    
    # Test thử kết nối Ollama
    try:
        ollama.chat(model=LOCAL_MODEL, messages=[{'role': 'user', 'content': 'hi'}])
        print(">>> ✅ KẾT NỐI LOCAL AI THÀNH CÔNG!")
    except Exception as e:
        print(f"❌ Không kết nối được Ollama. Hãy chạy 'ollama serve' trước. Lỗi: {e}")
        sys.exit(1)
    
    amp = OutputDevice(AMP_PIN, active_high=True, initial_value=False)
    pygame.mixer.init(frequency=24000)
    
except Exception as e:
    print(f"❌ Lỗi khởi tạo: {e}")
    sys.exit(1)

# ====== 4. HÀM CHỨC NĂNG ======

def clean_text(text):
    text = re.sub(r'\([^)]*\)', '', text)
    return text.replace("*", "").replace("#", "").replace("😊", "").replace("👋", "")

async def speak(text):
    clean_content = clean_text(text)
    # Nếu nội dung rỗng (do Local AI chỉ trả về lệnh CMD), thì không nói gì
    if not clean_content.strip(): 
        return

    print(f"Bot: {clean_content}") 
    file_path = "reply.mp3"
    try:
        communicate = edge_tts.Communicate(clean_content, VOICE_NAME, pitch=TTS_PITCH, rate=TTS_RATE)
        await communicate.save(file_path)
        
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=24000)
            
        amp.on()
        sleep(0.1)
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        pygame.mixer.quit()
    except Exception as e:
        print(f"Lỗi loa: {e}")
    finally:
        sleep(0.2)
        amp.off()
        if os.path.exists(file_path):
            os.remove(file_path)

def listen():
    r = sr.Recognizer()
    r.energy_threshold = 2000 
    r.dynamic_energy_threshold = True 
    try:
        with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
            print("\nBạn: ... (Đang nghe)")
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=8, phrase_time_limit=10)
            text = r.recognize_google(audio, language="vi-VN")
            print(f"Bạn: {text}")
            return text
    except:
        return None

async def ask_local_ai(prompt):
    """Hàm gửi câu hỏi sang Ollama chạy Local"""
    messages = [
        {'role': 'system', 'content': SYS_INSTRUCT},
        {'role': 'user', 'content': prompt}
    ]
    try:
        response = ollama.chat(model=LOCAL_MODEL, messages=messages)
        return response['message']['content']
    except Exception as e:
        print(f"Lỗi Ollama: {e}")
        return "tôi bị đau đầu quá."

async def process_ai_response(response_text):
    text = response_text.strip()
    
    # Tìm kiếm mã lệnh trong câu trả lời (Local AI hay nói dài dòng hơn Gemini)
    # Regex tìm chuỗi [CMD:...]
    match = re.search(r'\[CMD:(\d+):(on|off)\]', text)
    
    if match:
        dev_id = match.group(1)
        state = match.group(2)
        cmd_content = f"{dev_id}:{state}"
        
        try:
            print(f"⚡ Local Lệnh: {cmd_content}")
            publish.single(TOPIC_CMD, cmd_content, hostname=MQTT_BROKER)
            return "Dạ xong rồi ạ!"
        except:
            return "Tôi không kết nối được."
    
    # Nếu không phải lệnh, trả về nguyên văn để đọc
    return text

# ====== 5. MAIN ======
async def main():
    await speak("Xin chào, một ngày tốt lành!")
    
    while True:
        user_input = listen()
        if not user_input: continue
            
        if user_input.lower() in ["tạm biệt", "tắt máy", "thoát"]:
            await speak("Tạm biệt")
            break

        # Gửi sang Local AI
        ai_reply = await ask_local_ai(user_input)
        
        # Xử lý
        final_reply = await process_ai_response(ai_reply)
        await speak(final_reply)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nĐã dừng.")
        OutputDevice(AMP_PIN).off()
