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

# 🚨 FIXED: Real Online Lines logic
async def get_online_stats(firebases):
    total_online = 0
    total_devices = 0
    
    async def check_fb(fb):
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{fb['url']}/clients.json?shallow=true"
                if fb.get("auth"): url += f"&auth={fb['auth']}"
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, dict):
                            return len(data)
        except: pass
        return 0

    tasks = [check_fb(fb) for fb in firebases]
    results = await asyncio.gather(*tasks)
    
    for count in results:
        total_devices += count
        if count > 0: total_online += count
            
    return total_online, total_devices

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
    
    # 🚨 Calling fixed online stats
    online_cnt, total_lines = await get_online_stats(fbs)
    
    text = (
        f"👑 <b>{sc('admin dashboard')}</b>\n\n"
        f"🌍 {sc('countries')}: <b>{len(countries)}</b>\n"
        f"🔥 {sc('total servers')}: <b>{len(fbs)}</b>\n"
        f"📱 {sc('online lines')}: <b>{online_cnt}</b> / {total_lines}\n"
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
                text += f"👤 User: <code>{t['user_id']}</code>\n🆔 <code>{t['rent_id']}</code>\n📞 <code>{t['number']}</code>\n⏰ {get_ist_time_str(t['target_time'])}\n\n"
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "
