from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
import database as db
from utils.ui import sc, btn
from utils.helper import get_ist_time_str

admin_router = Router()

@admin_router.callback_query(F.data == "admin:users")
async def admin_users_list(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    users = d.get("users", {})
    if not users:
        return await cq.message.edit_text("👥 No users found.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]))
    text = f"👥 <b>Total Users: {len(users)}</b>\n\n"
    kb = []
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
