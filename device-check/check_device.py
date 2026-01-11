import pyaudio

p = pyaudio.PyAudio()

print("="*40)
print("DANH SÁCH THIẾT BỊ ÂM THANH")
print("="*40)

for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    # Chỉ hiện thiết bị có khả năng thu âm (Input Channels > 0)
    if info['maxInputChannels'] > 0:
        print(f"ID: {i} - Tên: {info['name']} - Input Channels: {info['maxInputChannels']}")

p.terminate()
