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

# 🚨 REAL ONLINE STATS FIX
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
        except: pass
        return 0, 0

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
        [btn("manage users", "admin:users", "👥")], # 🚨 NAYA BUTTON
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

# ... (Baaki admin code same rahega, bas 'admin:users' ka naya section add karna hai)

@admin_router.callback_query(F.data == "admin:users")
async def admin_users_list(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    users = d.get("users", {})
    
    if not users:
        return await cq.message.edit_text("👥 No users found.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]))
        
    text = f"👥 <b>Total Users: {len(users)}</b>\n\n"
    kb = []
    
    # Sirf top 20 users dikhayenge
    for uid, u_data in list(users.items())[:20]:
        name = u_data.get("name", "Unknown")
        is_ban = uid in d.get("banned", [])
        status = "🚫" if is_ban else "✅"
        kb.append([btn(f"{status} {name[:15]}", f"admin:user_info:{uid}", "👤")])
        
    kb.append([btn("back", "admin:home", "🔙")])
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:user_info:"))
async def admin_user_info(cq: CallbackQuery):
    await cq.answer()
    uid = cq.data.split(":")[2]
    d = db.load_data()
    u_data = d.get("users", {}).get(uid)
    
    if not u_data:
        return await cq.answer("User not found!", show_alert=True)
        
    is_ban = uid in d.get("banned", [])
    name = u_data.get("name", "Unknown")
    joined = get_ist_time_str(u_data.get("joined", 0))
    otp_count = len(u_data.get("otp_history", []))
    
    text = (
        f"👤 <b>User Info</b>\n\n"
        f"🆔 <b>ID:</b> <code>{uid}</code>\n"
        f"📛 <b>Name:</b> {name}\n"
        f"📅 <b>Joined:</b> {joined}\n"
        f"📜 <b>Total OTPs:</b> {otp_count}\n"
        f"🚫 <b>Status:</b> {'BANNED' if is_ban else 'ACTIVE'}\n\n"
    )
    
    kb = []
    if is_ban:
        kb.append([btn("unban user", f"admin:unban:{uid}", "✅")])
    else:
        kb.append([btn("ban user", f"admin:ban:{uid}", "🚫")])
        
    kb.append([btn("back", "admin:users", "🔙")])
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:ban:"))
async def admin_ban_user(cq: CallbackQuery):
    await cq.answer("User Banned!", show_alert=True)
    uid = cq.data.split(":")[2]
    d = db.load_data()
    banned = d.setdefault("banned", [])
    if uid not in banned: banned.append(uid)
    db.save_data(d)
    await admin_user_info(cq)

@admin_router.callback_query(F.data.startswith("admin:unban:"))
async def admin_unban_user(cq: CallbackQuery):
    await cq.answer("User Unbanned!", show_alert=True)
    uid = cq.data.split(":")[2]
    d = db.load_data()
    banned = d.setdefault("banned", [])
    if uid in banned: banned.remove(uid)
    db.save_data(d)
    await admin_user_info(cq)

# ... (Baaki admin.py ka code same rahega, bas admin_kb me "manage users" ka button add kar diya hai)
