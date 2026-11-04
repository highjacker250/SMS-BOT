from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import database as db
from utils.ui import sc, btn
from utils.helper import is_owner
from states import S
from services.telegram_automation import auto_login_tg

admin_router = Router()

@admin_router.message(Command("tglogin"))
async def cmd_tg_login(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id): return
    await state.set_state(S.tg_login_phone)
    await msg.answer("📱 Enter phone number with country code (e.g., +919876543210):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:home", "❌")]]))

@admin_router.message(S.tg_login_phone)
async def process_tg_login(msg: Message, state: FSMContext):
    await state.clear()
    phone = msg.text.strip()
    if not phone.startswith("+"):
        return await msg.answer("❌ Must start with + (e.g., +919876543210).")
    
    status_msg = await msg.answer(f"🔄 Starting AI Auto-Login for {phone}...\nPlease wait.")
    
    # DB me save karo
    d = db.load_data()
    d["telegram_accounts"][phone] = {"status": "logging_in", "reset_time": 0, "session": ""}
    db.save_data(d)
    
    # Login trigger karo
    res = await auto_login_tg(phone)
    
    d = db.load_data()
    if res["status"] == "success":
        d["telegram_accounts"][phone] = {"status": "active", "session": res["session"], "reset_time": 0}
        db.save_data(d)
        await status_msg.edit_text(f"✅ <b>Login Successful!</b>\n\nSession saved to DB.\nAccess Panel: <code>{config.WEB_URL}/panel</code>", parse_mode="HTML")
    else:
        if "2FA" in res["reason"]:
            # 7 days wait
            d["telegram_accounts"][phone] = {"status": "waiting_7_days", "session": "", "reset_time": int(__import__('time').time()) + (7*24*3600)}
            db.save_data(d)
            await status_msg.edit_text(f"⚠️ <b>2FA Enabled by user.</b>\nAI will wait for 7 days for SMS reset, then try again.", parse_mode="HTML")
        else:
            d["telegram_accounts"][phone] = {"status": "failed", "reason": res["reason"]}
            db.save_data(d)
            await status_msg.edit_text(f"❌ <b>Login Failed:</b> {res['reason']}", parse_mode="HTML")

@admin_router.message(Command("tglist"))
async def cmd_tg_list(msg: Message):
    if not is_owner(msg.from_user.id): return
    d = db.load_data()
    accs = d.get("telegram_accounts", {})
    if not accs: return await msg.answer("No TG accounts added yet.")
    
    text = "📱 <b>TG Accounts:</b>\n\n"
    for phone, info in accs.items():
        text += f"📞 <code>{phone}</code> | Status: {info['status']}\n"
    await msg.answer(text, parse_mode="HTML")
