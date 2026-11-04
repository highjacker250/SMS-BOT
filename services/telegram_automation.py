import asyncio
import logging
import time
import random
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait, PhoneCodeInvalid
import config
import database as db
from services.email_parser import get_telegram_email_otp

log = logging.getLogger("TGAuto")

async def auto_login_tg(phone_number):
    log.info(f"Starting Auto-Login for {phone_number}")
    
    d = db.load_data()
    if not d.get("hunting_enabled", True):
        return {"status": "failed", "reason": "Hunting is disabled by Owner"}

    # Get Proxy
    proxies = d.get("working_proxies", [])
    proxy_dict = None
    if proxies:
        p = random.choice(proxies)
        ip, port = p.split(":")
        proxy_dict = {"scheme": "socks5", "hostname": ip, "port": int(port)}
        log.info(f"Using proxy: {ip}:{port}")

    app = Client(
        name=f"temp_{phone_number.replace('+', '')}",
        api_id=config.TG_API_ID,
        api_hash=config.TG_API_HASH,
        phone_number=phone_number,
        in_memory=True,
        proxy=proxy_dict
    )

    try:
        await app.connect()
        try:
            sent_code = await app.send_code(phone_number)
        except FloodWait as e:
            await app.disconnect()
            return {"status": "failed", "reason": f"FloodWait: {e.value} seconds"}
            
        log.info(f"Code sent. Waiting for Email OTP for {phone_number}...")
        email_otp = await get_telegram_email_otp(timeout=90) 
        
        if not email_otp:
            await app.disconnect()
            return {"status": "failed", "reason": "Email OTP timeout (Check Gmail)"}

        try:
            await app.sign_in(phone_number, sent_code.phone_code_hash, email_otp)
        except SessionPasswordNeeded:
            await app.disconnect()
            return {"status": "failed", "reason": "2FA Password Enabled"}
        except PhoneCodeInvalid:
            await app.disconnect()
            return {"status": "failed", "reason": "Invalid OTP passed"}

        session_string = await app.export_session_string()
        await app.disconnect()

        return {"status": "success", "session": session_string, "phone": phone_number}

    except Exception as e:
        log.error(f"Login failed for {phone_number}: {e}")
        if app.is_connected: await app.disconnect()
        return {"status": "failed", "reason": str(e)}

async def reset_watchdog_loop():
    while True:
        d = db.load_data()
        if not d.get("hunting_enabled", True):
            await asyncio.sleep(3600)
            continue
            
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
                    else:
                        acc["status"] = "failed"
                        acc["reason"] = res["reason"]
                    updated = True
        
        if updated: db.save_data(d)
        await asyncio.sleep(3600)
