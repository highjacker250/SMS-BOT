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
    try: await cq.message.edit_text("🔄 Refreshing...")
    except: pass
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

# ... (Baaki admin handlers: manage_fb, country, server, base, dev, rmmenu, rmdo, add_country, dead_filter, add_bulk same rahenge) ...
# Include the same code as previous version for these functions
