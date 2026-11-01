from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
import time, asyncio, logging
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_admin, get_countries, get_servers_grouped, get_ist_time_str
from states import S

log = logging.getLogger("Admin")
admin_router = Router()

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("enter as user", "user:home", "👤"), btn("manage servers", "admin:manage_fb", "🔥")],
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
    text = (
        f"👑 <b>{sc('admin dashboard')}</b>\n\n"
        f"🌍 {sc('countries')}: <b>{len(countries)}</b>\n"
        f"🔥 {sc('total servers')}: <b>{total_servers}</b>\n"
        f"📱 {sc('total bases')}: <b>{len(fbs)}</b>\n"
        f"👥 {sc('total users')}: <b>{users_count}</b>\n\n"
        f"<i>{sc('select an option below to manage the bot')}</i>"
    )
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
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
                text += f"👤 User: <code>{t['user_id']}</code>\n🆔 <code>{t['rent_id'][:10]}...</code>\n📞 <code>{t['number']}</code>\n⏰ {get_ist_time_str(t['target_time'])}\n\n"
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]), parse_mode="HTML")

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
    text = f"
