import asyncio
import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_owner, is_admin, get_countries

admin_router = Router()

# Helper for real online stats
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

@admin_router.message(F.text == "/start")
async def admin_start(message: Message):
    uid = message.from_user.id
    if not is_admin(uid): return # User router will handle
    
    d = db.load_data()
    fbs = d.get("firebases", [])
    online, total = await get_online_stats(fbs)
    
    text = (
        f"👑 <b>{sc('admin dashboard')}</b>\n\n"
        f"🌍 <b>{sc('countries')}:</b> {len(get_countries(d))}\n"
        f"🔥 <b>{sc('total servers')}:</b> {len(fbs)}\n"
        f"📱 <b>{sc('online lines')}:</b> <code>{online}</code> / {total}\n"
        f"👥 <b>{sc('total users')}:</b> {len(d.get('users', {}))}\n\n"
        f"<i>{sc('select an option below')}</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("enter as user", "admin_as_user", "👤"), btn("manage servers", "admin_servers", "🔥")],
        [btn("track device", "admin_track", "🔍"), btn("manage vips", "admin_vips", "⭐")],
        [btn("active timers", "admin_timers", "⏰")],
        [btn("refresh panel", "admin_refresh", "🔄")],
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
