from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
import time
import database as db
from utils.ui import sc, btn
from utils.helper import get_ist_time_str

user_router = Router()

@user_router.callback_query(F.data == "user:upcoming")
async def user_upcoming(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    timers = d.get("upcoming_timers", {})
    user_timers = {k: v for k, v in timers.items() if v.get("user_id") == cq.from_user.id}

    if not user_timers:
        return await cq.message.edit_text("📅 <b>Upcoming OTPs</b>\n\nKoi timer set nahi hai.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("main menu", "user:main_menu", "🏠")]]), parse_mode="HTML")

    sorted_timers = sorted(user_timers.items(), key=lambda kv: kv[1]["target_time"])

    kb = []
    for k, t in sorted_timers:
        kb.append([btn(f"+91{t['number']} | {get_ist_time_str(t['target_time'])}", f"user:click_timer:{k}", "⏰")])

    kb.append([btn("main menu", "user:main_menu", "🏠")])
    await cq.message.edit_text("📅 <b>Upcoming OTPs</b>\n\nNumber pe click karein details dekhne ke liye:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:click_timer:"))
async def user_click_timer(cq: CallbackQuery):
    await cq.answer()
    timer_id = cq.data.split(":")[2]
    d = db.load_data()
    timer = d.get("upcoming_timers", {}).get(timer_id)

    if not timer:
        return await cq.answer("❌ Timer expired or not found.", show_alert=True)
    if timer.get("user_id") != cq.from_user.id:
        return await cq.answer("❌ Ye aapka timer nahi hai!", show_alert=True)

    num = timer['number']
    rent_id = timer['rent_id']
    target_time = timer['target_time']

    text = (
        f"⏰ <b>{sc('timer details')}</b>\n\n"
        f"📞 <b>{sc('number')}:</b> <code>+91{num}</code>\n"
        f"🆔 <b>{sc('rent id')}:</b> <code>{rent_id}</code>\n"
        f"🕒 <b>{sc('target time')}:</b> {get_ist_time_str(target_time)}\n\n"
        f"<i>{sc('waiting for otp...')}</i>"
    )
    kb = [
        [InlineKeyboardButton(text=f"Copy +91{num}", copy_text=CopyTextButton(text=f"+91{num}"))],
        [btn("remove timer", f"user:remove_timer:{timer_id}", "🗑")],
        [btn("back", "user:upcoming", "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:remove_timer:"))
async def user_remove_timer(cq: CallbackQuery):
    timer_id = cq.data.split(":")[2]
    d = db.load_data()
    timer = d.get("upcoming_timers", {}).get(timer_id)

    if not timer:
        await cq.answer("❌ Timer pehle se hi hata diya gaya hai.", show_alert=True)
        return await user_upcoming(cq)
    if timer.get("user_id") != cq.from_user.id:
        return await cq.answer("❌ Ye aapka timer nahi hai!", show_alert=True)

    del d["upcoming_timers"][timer_id]
    db.save_data(d)
    await cq.answer("🗑 Timer removed!", show_alert=True)
    await user_upcoming(cq)1
