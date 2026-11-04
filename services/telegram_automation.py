import asyncio
import logging
import time
import random
import traceback # 🚨 Naya import
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait, PhoneCodeInvalid, RPCError
import config
import database as db
from services.email_parser import get_telegram_email_otp
from services.warp_manager import get_warp_proxy, start_warp

log = logging.getLogger("TGAuto")
_WARP_READY = False

async def ensure_warp():
    global _WARP_READY
    if not _WARP_READY:
        log.info("WARP not ready. Attempting to start...")
        _WARP_READY = await start_warp()
    return _WARP_READY

async def auto_login_tg(phone_number):
    log.info(f"Starting Auto-Login for {phone_number}")
    
    d = db.load_data()
    if not d.get("hunting_enabled", True):
        return {"status": "failed", "reason": "Hunting is disabled by Owner"}

    # 🚨 PRIORITY 1: Cloudflare WARP
    proxy_dict = None
    if await ensure_warp():
        proxy_dict = get_warp_proxy()
        log.info("Using Cloudflare WARP Proxy.")
    
    # 🚨 PRIORITY 2: Fallback to Custom/Free Proxies
    if not proxy_dict:
        proxies = d.get("working_proxies", [])
        if proxies:
            p = random.choice(proxies)
            ip, port = p.split(":")[:2]
            proxy_dict = {"scheme": "socks5", "hostname": ip, "port": int(port)}
            log.info(f"Using Fallback Proxy: {ip}:{port}")

    app = Client(
        name=f"temp_{phone_number.replace('+', '')}",
        api_id=config.TG_API_ID,
        api_hash=config.TG_API_HASH,
        phone_number=phone_number,
        in_memory=True,
        proxy=proxy_dict
    )

    try:
        log.info("Connecting to Telegram...")
        await app.connect()
        log.info("Connected. Sending code request...")
        
        try:
            sent_code = await app.send_code(phone_number)
            log.info("Code request sent successfully.")
        except FloodWait as e:
            await app.disconnect()
            return {"status": "failed", "reason": f"FloodWait: {e.value} seconds. Try after {e.value/60} mins."}
        except RPCError as e:
            await app.disconnect()
            return {"status": "failed", "reason": f"Telegram API Error: {str(e)}"}
            
        log.info(f"Waiting for Email OTP for {phone_number}...")
        email_otp = await get_telegram_email_otp(timeout=90) 
        
        if not email_otp:
            await app.disconnect()
            return {"status": "failed", "reason": "Email OTP timeout. Check Gmail (iamnotready171@gmail.com) for OTP."}

        log.info(f"Email OTP received: {email_otp}. Trying to sign in...")
        
        try:
            await app.sign_in(phone_number, sent_code.phone_code_hash, email_otp)
        except SessionPasswordNeeded:
            await app.disconnect()
            return {"status": "failed", "reason": "2FA Password is enabled on this account."}
        except PhoneCodeInvalid:
            await app.disconnect()
            return {"status": "failed", "reason": "Invalid OTP passed."}

        session_string = await app.export_session_string()
        await app.disconnect()

        log.info(f"Login Successful for {phone_number}!")
        return {"status": "success", "session": session_string, "phone": phone_number}

    except Exception as e:
        # 🚨 Print full traceback for debugging
        error_details = traceback.format_exc()
        log.error(f"Login failed for {phone_number}:\n{error_details}")
        
        if app.is_connected: 
            await app.disconnect()
            
        # Get specific error if possible
        error_str = str(e) if str(e) else error_details.split("\n")[-2]
        return {"status": "failed", "reason": error_str}

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
