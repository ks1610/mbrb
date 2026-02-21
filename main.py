import threading
import asyncio
import time
import sys
import os
from dotenv import load_dotenv
import ollama

load_dotenv()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(CURRENT_DIR, "asset")
sys.path.append(ASSET_DIR)

import globals
from system_logs import load_system_config, load_system_logs, add_system_log
from ai_module import speak, listen, check_info_request, analyze_command_similarity, LOCAL_MODEL, SYS_INSTRUCT_BASE
from camera_tracking import camera_thread
from bluetooth_server import bluetooth_server_thread
from routes import app
from mqtt_handler import mqtt_client, TOPIC_CMD

print("🔥 NEW VERSION LOADED @", time.strftime("%H:%M:%S"))

WEB_PORT = 8080

def run_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_loop())

def start_camera(delay=3):
    def _start():
        print(">>> ⏳ Waiting before starting camera...")
        time.sleep(delay)
        if globals.SYSTEM_CONFIG["camera"]:
            threading.Thread(
                target=camera_thread,
                daemon=True
            ).start()
            print(">>> 📸 Camera thread started.")
    threading.Thread(target=_start, daemon=True).start()

async def main_loop():
    await asyncio.sleep(3)
    try:
        await speak("Hanah khởi động")
    except Exception as e:
        print(f"Greeting failed: {e}")

    loop = asyncio.get_event_loop()

    while not globals.STOP_EVENT.is_set():
        try:
            # call blocking listen() in executor
            user_input = await loop.run_in_executor(None, listen)

            if not user_input:
                # small sleep to yield CPU
                await asyncio.sleep(0.1)
                continue

            print(f"👤: {user_input}")

            # exit phrase
            if "tạm biệt" in user_input.lower():
                await speak("Bai bai.")
                break

            # 1) Device control via language
            cmd = analyze_command_similarity(user_input)
            if cmd:
                device_id, cmd_state = cmd
                try:
                    # MQTT publish (paho is thread-safe for publish)
                    mqtt_client.publish(TOPIC_CMD, f"{device_id}:{cmd_state}")
                    add_system_log(f"Gửi lệnh MQTT: Thiết bị {device_id} -> {cmd_state.upper()}", "info", "MQTT_CMD")
                except Exception as e:
                    print(f"MQTT publish error: {e}")

                action_vn = 'bật' if cmd_state == 'on' else 'tắt'
                await speak(f"Đã {action_vn} đèn {device_id}!")
                continue

            # 2) Info requests (time/weather)
            info = check_info_request(user_input)
            if info:
                await speak(info)
                continue

            # 3) AI conversation (ollama.chat is blocking => run in executor)
            if globals.SYSTEM_CONFIG.get("ai", True):
                try:
                    res = await loop.run_in_executor(None, lambda: ollama.chat(
                        model=LOCAL_MODEL,
                        messages=[
                            {'role': 'system', 'content': SYS_INSTRUCT_BASE},
                            {'role': 'user', 'content': user_input}
                        ]
                    ))
                    # extract text robustly
                    ai_text = None
                    try:
                        ai_text = res['message']['content']
                    except Exception:
                        if isinstance(res, str):
                            ai_text = res
                        elif isinstance(res, dict) and 'content' in res:
                            ai_text = res['content']
                    if ai_text:
                        await speak(ai_text)
                except Exception as e:
                    print(f"AI chat error: {e}")
                    await asyncio.sleep(0.5)

        except Exception as e:
            print(f"main_loop error: {e}")
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    globals.SYSTEM_CONFIG = load_system_config()
    globals.SYSTEM_LOGS = load_system_logs()

    # start async AI loop WITHOUT audio greeting
    threading.Thread(target=run_async_loop, daemon=True).start()

    # start camera later
    start_camera(delay=3)

    # start bluetooth server
    threading.Thread(target=bluetooth_server_thread, daemon=True).start()

    # start web server LAST
    app.run(
        host="0.0.0.0",
        port=WEB_PORT,
        use_reloader=False,
        threaded=True
    )