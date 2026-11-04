from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import time
import database as db
import config
from utils.ui import sc, btn
from utils.helper import is_owner
from states import S
from services.telegram_automation import auto_login_tg

admin_router = Router()

@admin_router.message(Command("tglogin"))
async def cmd_tg_login(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id): return
    await state.set_state(S.tg_login_phone)
    await msg.answer(
        "📱 <b>Enter phone number with country code</b>\n"
        "Example: <code>+919876543210</code>\n\n"
        "<i>AI will trigger login and wait for Email OTP.</i>", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:home", "❌")]]),
        parse_mode="HTML"
    )

@admin_router.message(S.tg_login_phone)
async def process_tg_login(msg: Message, state: FSMContext):
    await state.clear()
    phone = msg.text.strip()
    
    if not phone.startswith("+"):
        return await msg.answer("❌ Number must start with + (e.g., +919876543210).")
    
    status_msg = await msg.answer(f"🔄 <b>Starting AI Auto-Login for {phone}...</b>\nPlease wait, fetching Email OTP.", parse_mode="HTML")
    
    d = db.load_data()
    d["telegram_accounts"][phone] = {"status": "logging_in", "reset_time": 0, "session": ""}
    db.save_data(d)
    
    res = await auto_login_tg(phone)
    
    d = db.load_data()
    if res["status"] == "success":
        d["telegram_accounts"][phone] = {"status": "active", "session": res["session"], "reset_time": 0}
        db.save_data(d)
        await status_msg.edit_text(
            f"✅ <b>Login Successful!</b>\n\n"
            f"📞 Number: <code>{phone}</code>\n"
            f"🔑 Session saved to DB.\n"
            f"🌐 Panel: <code>{config.WEB_URL}/panel</code>", 
            parse_mode="HTML"
        )
    else:
        if "2FA" in res["reason"]:
            reset_time = int(time.time()) + (7 * 24 * 3600)
            d["telegram_accounts"][phone] = {"status": "waiting_7_days", "session": "", "reset_time": reset_time}
            db.save_data(d)
            await status_msg.edit_text(
                f"⚠️ <b>2FA is Enabled!</b>\n\n"
                f"AI cannot login without the 2FA password. It will wait for <b>7 days</b> for the SMS reset option to unlock, then try again automatically.\n"
                f"🕒 Reset Timer Set: 7 Days", 
                parse_mode="HTML"
            )
        else:
            d["telegram_accounts"][phone] = {"status": "failed", "reason": res["reason"]}
            db.save_data(d)
            await status_msg.edit_text(f"❌ <b>Login Failed:</b> {res['reason']}", parse_mode="HTML")

# 🚨 NAYA: Telegram Login Stats command
@admin_router.message(Command("tgstats"))
async def cmd_tg_stats(msg: Message):
    if not is_owner(msg.from_user.id): return
    d = db.load_data()
    accs = d.get("telegram_accounts", {})
    
    total = len(accs)
    active = sum(1 for a in accs.values() if a.get("status") == "active")
    waiting = sum(1 for a in accs.values() if a.get("status") == "waiting_7_days")
    failed = sum(1 for a in accs.values() if a.get("status") == "failed")
    
    text = (
        f"📊 <b>Telegram Login Stats</b>\n\n"
        f"📱 Total Accounts: <b>{total}</b>\n"
        f"✅ Active (Logged In): <b>{active}</b>\n"
        f"⏳ Waiting (7 Days): <b>{waiting}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n\n"
        f"<i>Use /tglist to see detailed status of each account.</i>"
    )
    await msg.answer(text, parse_mode="HTML")
