import speech_recognition as sr

# ID Micro của bạn (Lấy từ bước check_device trước đó, thường là 0)
MIC_ID = 0 

def test_google_stt():
    r = sr.Recognizer()
    
    # Tinh chỉnh ngưỡng nghe
    r.energy_threshold = 2000
    r.dynamic_energy_threshold = True
    
    with sr.Microphone(device_index=MIC_ID) as source:
        print("="*40)
        print("🎤 Mời bạn nói gì đó (5 giây)...")
        print("="*40)
        
        # Lọc ồn
        r.adjust_for_ambient_noise(source, duration=1)
        
        try:
            # Nghe
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            print("⏳ Đang gửi lên Google...")
            
            # Dịch
            text = r.recognize_google(audio, language="vi-VN")
            print(f"✅ KẾT QUẢ: {text}")
            
        except sr.UnknownValueError:
            print("❌ Google không hiểu bạn nói gì (Có thể do ồn hoặc nói quá nhỏ).")
        except sr.RequestError as e:
            print(f"❌ Lỗi kết nối mạng: {e}")
        except Exception as e:
            print(f"❌ Lỗi khác: {e}")

if __name__ == "__main__":
    test_google_stt()
