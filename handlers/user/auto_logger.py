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
from services.smart_otp_scraper import get_available_countries, select_country_and_get_numbers, wait_for_otp_from_bot
from services.browser_automation import login_paypal
from pyrogram import Client
import config

user_auto_router = Router()

@user_auto_router.callback_query(F.data == "user:auto_logger")
async def start_auto_logger(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    uid = cq.from_user.id
    d = db.load_data()
    
    user_data = d.get("users", {}).get(str(uid), {})
    user_sessions = user_data.get("auto_sessions", {})
    
    if user_sessions:
        kb = []
        for phone, session in user_sessions.items():
            display_phone = phone[:4] + "****" + phone[-4:] if len(phone) > 8 else phone
            kb.append([btn(f"Use {display_phone}", f"user:use_saved:{phone}", "✅")])
        kb.append([btn("Add New Telegram Account", "user:add_new_tg", "➕")])
        kb.append([btn("cancel", "user:main_menu", "❌")])
        
        await cq.message.edit_text(
            "🤖 <b>AI Auto Logger</b>\n\nAapke saved accounts ye hain. Select karein:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
        )
    else:
        await start_add_new_tg(cq.message, state)

@user_auto_router.callback_query(F.data == "user:add_new_tg")
async def add_new_tg_btn(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await start_add_new_tg(cq.message, state)

async def start_add_new_tg(msg, state: FSMContext):
    text = f"🤖 <b>{sc('add new telegram account')}</b>\n\n<b>Apna Telegram Number daalein (with +91):</b>"
    await state.set_state(S.user_auto_phone)
    await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]), parse_mode="HTML")

@user_auto_router.callback_query(F.data.startswith("user:use_saved:"))
async def use_saved_account(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    phone = cq.data.split(":")[2]
    uid = cq.from_user.id
    d = db.load_data()
    
    session = d["users"][str(uid)]["auto_sessions"].get(phone)
    if not session:
        return await cq.answer("Session not found!", show_alert=True)
        
    await state.update_data(phone=phone, session=session)
    await ask_bot_username(cq.message, state)

@user_auto_router.message(S.user_auto_phone)
async def get_phone(msg: Message, state: FSMContext):
    phone = msg.text.strip()
    if not phone.startswith("+"):
        return await msg.answer("❌ Number must start with +.")
    
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
    
    res = await complete_user_login(data['phone'], data['phone_hash'], otp)
    if res["status"] == "success":
        d = db.load_data()
        uid = msg.from_user.id
        user = d["users"].setdefault(str(uid), {})
        if "auto_sessions" not in user: user["auto_sessions"] = {}
        user["auto_sessions"][data['phone']] = res["session"]
        db.save_data(d)
        
        await state.update_data(session=res["session"])
        await ask_bot_username(status, state)
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
        user = d["users"].setdefault(str(uid), {})
        if "auto_sessions" not in user: user["auto_sessions"] = {}
        user["auto_sessions"][data['phone']] = res["session"]
        db.save_data(d)
        
        await state.update_data(session=res["session"])
        await ask_bot_username(status, state)
    else:
        await status.edit_text(f"❌ 2FA Failed: {res['reason']}")
        await state.clear()

async def ask_bot_username(target_msg, state: FSMContext):
    await state.set_state(S.user_auto_bot_username)
    await target_msg.edit_text(
        "✅ Account Connected!\n\nAb aap batayein kaunsa OTP bot use karna hai?\nJaise: <code>@Smartotpworkbot</code>"
    )

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
    
    data = await state.get_data()
    session = data.get('session')
    phone = data.get('phone', 'Saved')
    bot_username = data.get('bot_username')
    
    status = await cq.message.edit_text("🔄 Fetching available countries & prices...")
    
    app = Client(f"user_{cq.from_user.id}_{phone.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, session_string=session)
    await app.start()
    countries = await get_available_countries(app, bot_username, target)
    await app.stop()

    if not countries:
        return await status.edit_text("❌ No countries found or bot menu is broken.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]))

    await state.update_data(available_countries=countries)
    
    kb = []
    for i, c in enumerate(countries):
        # Button me name aur price dono dikhao
        btn_text = f"{c['name']} - {c['price']}"
        # Callback data me index bhejo taaki original text yaad rahe
        kb.append([btn(btn_text, f"user:sel_country_idx:{i}", "🌍")])
    kb.append([btn("cancel", "user:main_menu", "❌")])
    
    await state.set_state(S.user_select_country)
    await status.edit_text(
        f"🌍 <b>Available Countries for {target.upper()}</b>\n\nSelect a country to proceed (Price in brackets):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
    )

@user_auto_router.callback_query(S.user_select_country, F.data.startswith("user:sel_country_idx:"))
async def country_selected(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    idx = int(cq.data.split(":")[2])
    data = await state.get_data()
    countries = data.get('available_countries', [])
    
    if idx >= len(countries):
        return await cq.answer("Invalid selection.", show_alert=True)
        
    selected_country = countries[idx]
    await state.update_data(selected_country=selected_country)
    
    await state.set_state(S.user_auto_limit)
    await cq.message.edit_text(
        f"✅ Selected: {selected_country['name']} ({selected_country['price']})\n\n"
        f"Kitne accounts login karne hain? (Number daalein, e.g., 10):", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]), 
        parse_mode="HTML"
    )

@user_auto_router.message(S.user_auto_limit)
async def get_limit(msg: Message, state: FSMContext):
    try:
        limit = int(msg.text.strip())
    except:
        return await msg.answer("❌ Please enter a valid number.")
        
    data = await state.get_data()
    await state.clear()
    
    session = data.get('session')
    phone = data.get('phone', 'Saved')
    bot_username = data.get('bot_username')
    target = data.get('target')
    selected_country = data.get('selected_country')
    
    await msg.answer(f"🚀 AI Hunter Started! Targeting {limit} accounts in {selected_country['name']}...")
    asyncio.create_task(run_user_auto_hunter(msg.bot, msg.from_user.id, phone, session, bot_username, target, selected_country, limit))


# ==========================================
# 🚨 REAL HUNTER LOGIC
# ==========================================
async def run_user_auto_hunter(bot, user_id, phone, session, bot_username, target, selected_country, limit):
    app = Client(f"user_{user_id}_{phone.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, session_string=session)
    await app.start()
    
    success = 0
    for i in range(limit):
        try:
            # Select country (using original_text to ensure exact match)
            numbers = await select_country_and_get_numbers(app, bot_username, selected_country['original_text'])
            if not numbers:
                await bot.send_message(user_id, f"⚠️ No numbers found. Bot might be out of stock.")
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
                    "user_id": user_id, "platform": target, "country": selected_country['name'],
                    "otp": otp, "status": login_res["status"], "cookies": login_res.get("cookies", ""), "time": int(time.time())
                }
                db.save_data(d)
                
                if login_res["status"] == "success":
                    success += 1
                    await bot.send_message(user_id, f"✅ Success: {num} logged in!")
                else:
                    await bot.send_message(user_id, f"❌ Failed: {num} | {login_res.get('reason')}")
                
        except Exception as e:
            await bot.send_message(user_id, f"❌ Error: {str(e)[:50]}")
    
    await bot.send_message(user_id, f"🎉 Hunter Finished! Total Success: {success}/{limit}")
    await app.stop()
