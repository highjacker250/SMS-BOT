import asyncio
import logging
import time
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait, PhoneCodeInvalid
import config
import database as db
from services.email_parser import get_telegram_email_otp

log = logging.getLogger("TGAuto")

async def auto_login_tg(phone_number):
    log.info(f"Starting Auto-Login for {phone_number}")
    
    # In-memory client banayenge taaki session string generate kar sakein
    app = Client(
        name=f"temp_{phone_number.replace('+', '')}",
        api_id=config.TG_API_ID,
        api_hash=config.TG_API_HASH,
        phone_number=phone_number,
        in_memory=True
    )

    try:
        await app.connect()
        
        # 1. Send Code Request
        try:
            sent_code = await app.send_code(phone_number)
        except FloodWait as e:
            await app.disconnect()
            return {"status": "failed", "reason": f"FloodWait: {e.value} seconds"}
            
        # 2. Wait for Email OTP (since 7-day SMS is not available immediately)
        log.info(f"Code sent. Waiting for Email OTP for {phone_number}...")
        email_otp = await get_telegram_email_otp(timeout=90) 
        
        if not email_otp:
            await app.disconnect()
            return {"status": "failed", "reason": "Email OTP timeout (Check Gmail)"}

        # 3. Sign in with Email OTP
        try:
            await app.sign_in(phone_number, sent_code.phone_code_hash, email_otp)
        except SessionPasswordNeeded:
            # Agar 2FA (Cloud Password) on hai
            await app.disconnect()
            return {"status": "failed", "reason": "2FA Password Enabled"}
        except PhoneCodeInvalid:
            await app.disconnect()
            return {"status": "failed", "reason": "Invalid OTP passed"}

        # 4. Success! Export Session String
        session_string = await app.export_session_string()
        await app.disconnect()

        return {
            "status": "success",
            "session": session_string,
            "phone": phone_number
        }

    except Exception as e:
        log.error(f"Login failed for {phone_number}: {e}")
        if app.is_connected:
            await app.disconnect()
        return {"status": "failed", "reason": str(e)}

async def reset_watchdog_loop():
    """Ye loop har 1 ghante me check karega ki kiska 7-day wait pura hua hai kya."""
    while True:
        d = db.load_data()
        tg_accounts = d.get("telegram_accounts", {})
        now = int(time.time())
        updated = False
        
        for phone, acc in tg_accounts.items():
            if acc.get("status") == "waiting_7_days":
                if now >= acc.get("reset_time", 0):
                    log.info(f"7 Days over for {phone}. Triggering Re-login...")
                    res = await auto_login_tg(phone)
                    if res["status"] == "success":
                        acc["session"] = res["session"]
                        acc["status"] = "active"
                        log.info(f"Re-login successful for {phone}")
                    else:
                        acc["status"] = "failed"
                        acc["reason"] = res["reason"]
                        log.error(f"Re-login failed for {phone}: {res['reason']}")
                    updated = True
        
        if updated:
            db.save_data(d)
            
        await asyncio.sleep(3600) # 1 hour
