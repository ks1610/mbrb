import re
import json
import os
import threading
from datetime import datetime, timedelta

DAY_MAPPING = {
    "thứ 2": 0, "thứ hai": 0,
    "thứ 3": 1, "thứ ba": 1,
    "thứ 4": 2, "thứ tư": 2,
    "thứ 5": 3, "thứ năm": 3,
    "thứ 6": 4, "thứ sáu": 4,
    "thứ 7": 5, "thứ bảy": 5,
    "chủ nhật": 6
}

# Map ngược lại để in ra tin nhắn cho đẹp
REVERSE_DAY_MAPPING = {0: "Thứ 2", 1: "Thứ 3", 2: "Thứ 4", 3: "Thứ 5", 4: "Thứ 6", 5: "Thứ 7", 6: "Chủ nhật"}

ROUTINE_FILE = "routines.json"

# Lưu trữ các timer đang chạy để sau này có thể can thiệp (hủy, sửa)
active_timers = {}

def calculate_delay(target_time_str, target_days):
    """Tính số giây từ hiện tại đến mốc thời gian mục tiêu (HH:MM)."""

    now = datetime.now()
    
    # Tạo đối tượng datetime cho thời gian mục tiêu trong ngày hôm nay
    target_time = datetime.strptime(target_time_str, "%H:%M").replace(
        year=now.year, month=now.month, day=now.day, second=0, microsecond=0
    )

    # Nếu thời gian mục tiêu bé hơn hoặc bằng hiện tại -> tức là giờ đó đã qua, lên lịch cho ngày mai
    if target_time <= now:
        target_time += timedelta(days=1)

    while target_time.weekday() not in target_days: 
        target_time += timedelta(days=1)

    # Tính độ trễ bằng giây
    delta = target_time - now
    return delta.total_seconds()

def schedule_routine(routine, execution_callback):
    """Lên lịch đếm ngược cho một Routine"""
    target_days = routine.get('days', [0, 1, 2, 3, 4, 5, 6])

    delay = calculate_delay(routine['time'], target_days)
    name = routine['name']
    
    def task_wrapper():
        print(f"\n[ROUTINE KÍCH HOẠT] Tới giờ thực hiện: {name}")
        # Thực thi công việc
        execution_callback(routine['work'])
        
        # Vì Routine lặp lại mỗi ngày, sau khi chạy xong, ta lên lịch lại cho chính nó vào ngày mai
        print(f"[ROUTINE] Đang lên lịch lại cho {name} vào ngày mai...")
        schedule_routine(routine, execution_callback)

    # Khởi tạo Timer chạy ngầm
    t = threading.Timer(delay, task_wrapper)
    t.daemon = True
    t.start()
    active_timers[name] = t
    
    hours, remainder = divmod(delay, 3600)
    minutes, _ = divmod(remainder, 60)
    days = int(hours // 24)
    rem_hours = int(hours % 24)
    print(f"[ROUTINE] Đã lên lịch '{name}'. Sẽ chạy sau {days} ngày {rem_hours} giờ {int(minutes)} phút.")

def load_and_schedule_all(execution_callback):
    """Hàm này chỉ gọi 1 lần khi khởi động hệ thống để nạp lại toàn bộ Routine cũ"""
    if not os.path.exists(ROUTINE_FILE):
        return
        
    with open(ROUTINE_FILE, "r", encoding="utf-8") as f:
        try: 
            routines = json.load(f)
        except: 
            routines = []
            
    for r in routines:
        schedule_routine(r, execution_callback)

def parse_and_save_routine(prompt, execution_callback):
    if ":" not in prompt:
        return False, "Vui lòng dùng dấu ':' để ngăn cách tên và nội dung. VD: 'Chế độ xem phim: Bật đèn 2 thứ 7 lúc 23:00'"

    name_part, content_part = prompt.split(":", 1)
    name = name_part.strip()
    content = content_part.strip()

    time_pattern = r'(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?'
    match = re.search(time_pattern, content)
    
    if not match:
        return False, "Em không tìm thấy thời gian cụ thể (VD: 11:00 hoặc 08:00 AM) trong câu lệnh của anh."
    
    time_str = match.group(1)
    ampm = match.group(2)
    
    try:
        if ampm:
            parsed_time = datetime.strptime(f"{time_str} {ampm}", "%I:%M %p")
        else:
            parsed_time = datetime.strptime(time_str, "%H:%M")
        cron_time = parsed_time.strftime("%H:%M")
    except ValueError:
        return False, "Định dạng thời gian không hợp lệ."

    # --- ĐOẠN MỚI: TÌM CÁC THỨ TRONG TUẦN ---
    found_days = []
    content_lower = content.lower()
    for key, val in DAY_MAPPING.items():
        if key in content_lower and val not in found_days:
            found_days.append(val)
            
    # Nếu không tìm thấy thứ nào, mặc định là chạy mỗi ngày
    if not found_days:
        found_days = [0, 1, 2, 3, 4, 5, 6]
        day_reply_str = "mỗi ngày"
    else:
        found_days.sort() # Sắp xếp lại thứ tự từ T2 đến CN cho đẹp
        day_reply_str = ", ".join([REVERSE_DAY_MAPPING[d] for d in found_days])
    # ----------------------------------------

    # Lọc phần nội dung công việc (cắt bỏ phần thời gian để câu lệnh gọn gàng)
    work = re.sub(r'(vào\s+)?(mỗi\s+)?(tối\s+|sáng\s+|trưa\s+|chiều\s+)?(thứ\s+\d+|chủ nhật\s+)?(lúc\s+)?' + match.group(0), '', content, flags=re.IGNORECASE).strip()

    routine_data = {
        "name": name,
        "time": cron_time,
        "days": found_days, # Lưu mảng các ngày vào JSON
        "work": work,
        "raw": prompt
    }

    routines = []
    if os.path.exists(ROUTINE_FILE):
        with open(ROUTINE_FILE, "r", encoding="utf-8") as f:
            try: routines = json.load(f)
            except: pass
            
    # Xóa routine cũ nếu trùng tên (để ghi đè)
    routines = [r for r in routines if r['name'] != name]
    routines.append(routine_data)
    
    with open(ROUTINE_FILE, "w", encoding="utf-8") as f:
        json.dump(routines, f, ensure_ascii=False, indent=4)

    # Khởi động ngay Timer
    schedule_routine(routine_data, execution_callback)

    return True, f"✅ Đã thiết lập Routine: <b>{name}</b>.<br>Hệ thống sẽ thực hiện: <i>'{work}'</i> vào lúc {cron_time} ({day_reply_str})."


def get_all_routines():
    """Lấy danh sách Routine và tính toán lại thời gian còn lại (để hiển thị lên Web)"""
    if not os.path.exists(ROUTINE_FILE):
        return []
        
    with open(ROUTINE_FILE, "r", encoding="utf-8") as f:
        try: routines = json.load(f)
        except: routines = []
        
    for r in routines:
        # Lấy ngày mục tiêu, mặc định 7 ngày nếu không có
        target_days = r.get('days', [0, 1, 2, 3, 4, 5, 6])
        
        # Gọi lại hàm tính độ trễ
        delay_seconds = calculate_delay(r['time'], target_days)
        r['remaining_seconds'] = delay_seconds
        
        # Làm đẹp chuỗi ngày hiển thị
        if len(target_days) == 7:
            r['days_display'] = "Mỗi ngày"
        else:
            r['days_display'] = ", ".join([REVERSE_DAY_MAPPING.get(d, "") for d in sorted(target_days)])
            
    return routines

def delete_routine(name):
    """Hủy bộ hẹn giờ đang chạy và xóa khỏi file JSON"""
    # 1. Tắt Timer đang chạy ngầm
    if name in active_timers:
        active_timers[name].cancel()
        del active_timers[name]
        print(f"[ROUTINE] Đã hủy hẹn giờ cho Routine: {name}")

    # 2. Xóa khỏi JSON
    if not os.path.exists(ROUTINE_FILE):
        return False
        
    with open(ROUTINE_FILE, "r", encoding="utf-8") as f:
        try: routines = json.load(f)
        except: return False

    new_routines = [r for r in routines if r['name'] != name]
    
    with open(ROUTINE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_routines, f, ensure_ascii=False, indent=4)
        
    return True