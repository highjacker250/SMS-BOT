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
from services.browser_automation import login_paypal_browser # 🚨 Naya import
from pyrogram import Client
import config

user_auto_router = Router()

# ... (start_auto_logger, add_new_tg, get_phone, get_otp, get_2fa, ask_bot_username, get_bot_username same rahenge)

# ... (select_target, country_selected same rahenge)

# 🚨 Final Hunter Logic
async def run_user_auto_hunter(bot, user_id, phone, session, bot_username, target, selected_country, limit):
    app = Client(f"user_{user_id}_{phone.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, session_string=session)
    await app.start()
    
    success = 0
    for i in range(limit):
        try:
            # 🚨 1. Numbers fetch karo
            numbers = await select_country_and_get_numbers(app, bot_username, selected_country['original_text'])
            if not numbers:
                await bot.send_message(user_id, f"⚠️ No numbers found. Trying again...")
                # Agar number nahi mila toh Refresh button click karo
                # (Ye logic scraper me add hoga)
                break
            
            for num in numbers:
                await bot.send_message(user_id, f"📱 Trying: {num} on {target.upper()}")
                
                # 🚨 2. OTP Wait karo
                otp = await wait_for_otp_from_bot(app, bot_username)
                if not otp:
                    await bot.send_message(user_id, f"❌ OTP not received for {num}")
                    continue
                
                # 🚨 3. Real Login (Browser)
                if target.lower() == "paypal":
                    login_res = await login_paypal_browser(num, otp)
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
