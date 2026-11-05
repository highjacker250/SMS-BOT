# handlers/user/auto_logger.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import database as db
import asyncio
import time
from utils.ui import sc, btn
from states import S
from services.telegram_automation import initiate_user_login, complete_user_login
from services.smart_otp_scraper import scrape_numbers_from_bot, wait_for_otp_from_bot
from pyrogram import Client
import config

user_auto_router = Router()

@user_auto_router.callback_query(F.data == "user:auto_logger")
async def start_auto_logger(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    text = (
        f"🤖 <b>{sc('ai auto logger')}</b>\n\n"
        f"Bhai, ye AI aapke Telegram account se kaam karega.\n\n"
        f"<b>Kaise kaam karega?</b>\n"
        f"1. Aap apna TG number denge.\n"
        f"2. AI OTP bhejega (aapko phone pe aayega).\n"
        f"3. Aap OTP denge.\n"
        f"4. Phir aap batayenge kaunsa platform (PayPal/FB) aur kitne accounts.\n\n"
        f"<b>Apna Telegram Number daalein (with +91):</b>"
    )
    await state.set_state(S.user_auto_phone)
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]), parse_mode="HTML")

@user_auto_router.message(S.user_auto_phone)
async def get_phone(msg: Message, state: FSMContext):
    phone = msg.text.strip()
    if not phone.startswith("+"):
        return await msg.answer("❌ Number must start with + (e.g., +919876543210).")
    
    await state.update_data(phone=phone)
    status = await msg.answer("🔄 Connecting to Telegram...")
    
    res = await initiate_user_login(phone)
    if res["status"] == "success":
        await state.update_data(phone_hash=res["hash"])
        await state.set_state(S.user_auto_otp)
        await status.edit_text("✅ OTP bhej diya gaya! Apna OTP daalein:")
    else:
        await status.edit_text(f"❌ Failed: {res['reason']}")
        await state.clear()

@user_auto_router.message(S.user_auto_otp)
async def get_otp(msg: Message, state: FSMContext):
    otp = msg.text.strip()
    data = await state.get_data()
    status = await msg.answer("🔄 Verifying OTP...")
    
    res = await complete_user_login(data['phone'], data['phone_hash'], otp)
    if res["status"] == "success":
        d = db.load_data()
        uid = msg.from_user.id
        d["users"].setdefault(str(uid), {})["auto_session"] = res["session"]
        db.save_data(d)
        
        await state.set_state(S.user_auto_bot_username)
        await status.edit_text("✅ Account Connected!\n\nAb aap batayein kaunsa OTP bot use karna hai?\nJaise: <code>@Smartotpworkbot</code>")
    elif "2FA" in res["reason"]:
        await state.set_state(S.user_auto_2fa)
        await status.edit_text("🔐 2FA Password daalein:")
    else:
        await status.edit_text(f"❌ Failed: {res['reason']}")
        await state.clear()

@user_auto_router.message(S.user_auto_2fa)
async def get_2fa(msg: Message, state: FSMContext):
    pwd = msg.text.strip()
    data = await state.get_data()
    status = await msg.answer("🔄 Verifying 2FA...")
    
    res = await complete_user_login(data['phone'], data['phone_hash'], None, pwd)
    if res["status"] == "success":
        d = db.load_data()
        uid = msg.from_user.id
        d["users"].setdefault(str(uid), {})["auto_session"] = res["session"]
        db.save_data(d)
        
        await state.set_state(S.user_auto_bot_username)
        await status.edit_text("✅ 2FA Verified! Ab OTP bot ka username daalein (e.g., @Smartotpworkbot):")
    else:
        await status.edit_text(f"❌ 2FA Failed: {res['reason']}")
        await state.clear()

@user_auto_router.message(S.user_auto_bot_username)
async def get_bot_username(msg: Message, state: FSMContext):
    bot_user = msg.text.strip()
    if not bot_user.startswith("@"):
        bot_user = "@" + bot_user
    await state.update_data(bot_username=bot_user)
    
    kb = [
        [btn("PayPal", "user:target_paypal", "💳"), btn("Facebook", "user:target_fb", "📘")],
        [btn("Instagram", "user:target_insta", "📸"), btn("Twitter", "user:target_twitter", "🐦")],
        [btn("cancel", "user:main_menu", "❌")]
    ]
    await state.set_state(S.user_auto_target)
    await msg.answer(f"✅ Bot set: <code>{bot_user}</code>\n\nAb select karein kaunsa platform auto-login karna hai?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_auto_router.callback_query(S.user_auto_target, F.data.startswith("user:target_"))
async def select_target(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    target = cq.data.split("_")[1]
    await state.update_data(target=target)
    await state.set_state(S.user_auto_limit)
    await cq.message.edit_text(f"Target: {target.upper()}\n\nKitne accounts login karne hain? (Number daalein, e.g., 10):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]))

@user_auto_router.message(S.user_auto_limit)
async def get_limit(msg: Message, state: FSMContext):
    limit = int(msg.text.strip())
    data = await state.get_data()
    await state.clear()
    
    await msg.answer(f"🚀 AI Hunter Started! {limit} accounts target kiye gaye hain. Live updates aayenge.")
    
    # Background task chalu karo
    asyncio.create_task(run_user_auto_hunter(msg.bot, msg.from_user.id, data, limit))
