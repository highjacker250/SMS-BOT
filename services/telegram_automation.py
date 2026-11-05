# services/telegram_automation.py
import asyncio
import logging
import time
import random
import traceback
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait, PhoneCodeInvalid, RPCError
from pyrogram.enums import SentCodeType
import config
import database as db
import firebase_utils as fbu

log = logging.getLogger("TGAuto")

async def update_owner_progress(bot, text):
    try:
        await bot.send_message(config.MAIN_OWNER, f"🤖 <b>AI PROGRESS:</b>\n{text}", parse_mode="HTML")
    except:
        pass

# ... (wait_for_firebase_otp, get_proxy, auto_login_manual, auto_hunter_loop, reset_watchdog_loop purane wale same rahenge)

# 🚨 NAYE FUNCTIONS (User Login ke liye)
async def initiate_user_login(phone_number):
    app = None
    try:
        app = Client(f"temp_user_{phone_number.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, phone_number=phone_number, in_memory=True)
        await app.connect()
        sent_code = await app.send_code(phone_number)
        await app.disconnect()
        return {"status": "success", "hash": sent_code.phone_code_hash}
    except Exception as e:
        if app and app.is_connected: await app.disconnect()
        return {"status": "failed", "reason": str(e)}

async def complete_user_login(phone_number, phone_code_hash, otp=None, password=None):
    app = None
    try:
        app = Client(f"temp_user_{phone_number.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, phone_number=phone_number, in_memory=True)
        await app.connect()
        
        if otp:
            try:
                await app.sign_in(phone_number, phone_code_hash, otp)
            except SessionPasswordNeeded:
                await app.disconnect()
                return {"status": "failed", "reason": "2FA Password required"}
        elif password:
            await app.check_password(password)
            
        session = await app.export_session_string()
        await app.disconnect()
        return {"status": "success", "session": session}
    except Exception as e:
        if app and app.is_connected: await app.disconnect()
        return {"status": "failed", "reason": str(e)}
