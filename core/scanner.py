import asyncio, time, logging, random, re
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# 🚨 SMART IMPORT: Naya aur Purana dono system handle karega
try:
    from aiogram.types import CopyTextButton
    HAS_COPY_TEXT = True
except ImportError:
    HAS_COPY_TEXT = False

import database as db
import firebase_utils as fbu
from utils.ui import sc
from utils.helper import get_ist_time_str

log = logging.getLogger("Scanner")

async def send_otp_to_user(bot, uid, service, otp, msg_text, rent_id, phone_number):
    num_display = f"+91{phone_number}" if phone_number and phone_number != "Unknown" else "Unknown"
    otp_msg = (
        f"🔔 <b>{sc('otp received')}!</b>\n\n"
        f"📱 <b>{sc('service')}:</b> {service}\n"
        f"🔑 <b>{sc('otp')}:</b> <code>{otp}</code>\n\n"
        f"🆔 <b>{sc('rent id')}:</b> <code>{rent_id}</code>\n"
        f"📞 <b>{sc('number')}:</b> <code>{num_display}</code>\n"
        f"💬 <i>{msg_text[:60]}...</i>"
    )
    
    # 🚨 DONO SYSTEM: Agar naya aiogram hai toh Copy button, warna callback
    if HAS_COPY_TEXT:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Copy {otp}", copy_text=CopyTextButton(text=otp))]])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Copy {otp}", callback_data=f"copy_otp_{otp}")]])
    
    d = db.load_data()
    user = d["users"].get(str(uid))
    if user:
        hist = user.setdefault("otp_history", [])
        hist.insert(0, {"service": service, "otp": otp, "time": int(time.time()), "number": phone_number})
        user["otp_history"] = hist[:20]
        db.save_data(d)
    try: await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
    except Exception: pass

# 🚨 Callback handler (fallback ke liye)
@dp.callback_query(F.data.startswith("copy_otp_")) # type: ignore
async def copy_otp_callback(cq):
    otp = cq.data.split("_")[2]
    await cq.answer(f"📋 OTP: {otp}\n\n(Manually copy karein)", show_alert=True)

async def check_device(bot, fb_url, auth, dev_id, users, last_msg_id, phone_number, service_filter):
    db.set_bot_status("Fast Scanner", f"Checking messages for {dev_id[:8]}...")
    url = f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=5"
    msgs = await fbu.fetch_fb(url, auth)
    if not msgs: return last_msg_id
    
    highest_id = last_msg_id
    sorted_msgs = sorted(msgs.values(), key=lambda x: int(x.get("id", 0)))
    
    for msg in sorted_msgs:
        if not isinstance(msg, dict) or msg.get("type") != "incoming": continue
        current_id = int(msg.get("id", 0))
        text = msg.get("message", "")
        sender = msg.get("sender", "")
        
        if current_id > last_msg_id:
            otp = fbu.extract_otp(text)
            if otp:
                detected_service = fbu.extract_service_name(text, sender)
                text_lower = text.lower()
                
                if service_filter == "whatsapp":
                    if "whatsapp" not in text_lower and not re.search(r'code[:\s]+\d{3}-\d{3}', text_lower):
                        continue
                    detected_service = "WhatsApp"
                elif service_filter == "telegram":
                    if "telegram" not in text_lower:
                        continue
                    detected_service = "Telegram"
                
                db.set_bot_status("Fast Scanner", f"🚨 OTP Found! {detected_service} for {phone_number}")
                for uid in users:
                    await send_otp_to_user(bot, uid, detected_service, otp, text, dev_id, phone_number)
        
        if current_id > highest_id: highest_id = current_id
        
    return highest_id

async def start_scanner(bot):
    log.info("Fast Scanner Started...")
    while True:
        try:
            d = db.load_data()
            leases = d.get("user_leases", {})
            fbs = {f["url"]: f.get("auth") for f in d.get("firebases", [])}
            device_to_users = {}
            current_time = time.time()
            
            for uid, lease in leases.items():
                if current_time < lease["expire_at"]:
                    fb_url, dev_id = lease.get("fb_url"), lease.get("dev_id")
                    service = lease.get("service_filter", "any")
                    if fb_url and dev_id:
                        key = (fb_url, dev_id)
                        if key not in device_to_users:
                            device_to_users[key] = {"users": [], "last_msg_id": lease.get("last_msg_id", 0), "phone": lease.get("top_number", "Unknown"), "service": service}
                        device_to_users[key]["users"].append(uid)
            
            if device_to_users:
                tasks = []
                keys = list(device_to_users.keys())
                for key in keys:
                    tasks.append(check_device(bot, key[0], fbs.get(key[0], ""), key[1], device_to_users[key]["users"], device_to_users[key]["last_msg_id"], device_to_users[key]["phone"], device_to_users[key]["service"]))
                
                results = await asyncio.gather(*tasks)
                updated = False
                for idx, key in enumerate(keys):
                    if results[idx] > device_to_users[key]["last_msg_id"]:
                        for uid in device_to_users[key]["users"]:
                            if uid in leases: 
                                leases[uid]["last_msg_id"] = results[idx]
                                updated = True
                if updated: db.save_data(d)
            else:
                db.set_bot_status("Fast Scanner", "Idle (No active leases)")
                
            await asyncio.sleep(1.0)
        except Exception as e:
            db.set_bot_status("Fast Scanner", f"Error: {str(e)[:30]}")
            log.error(f"Scanner error: {e}")
            await asyncio.sleep(1.0)

async def whatsapp_scanner(bot):
    log.info("WhatsApp Background Scanner Started...")
    while True:
        try:
            d = db.load_data()
            fbs = d.get("firebases", [])
            ready_lines = {}
            now = time.time()
            
            for i in range(0, len(fbs), 5):
                chunk = fbs[i:i+5]
                for fb in chunk:
                    db.set_bot_status("WA Scanner", f"Fetching clients from base...")
                    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                    if not clients or not isinstance(clients, dict): continue
                    
                    for dev_id, c in clients.items():
                        if not isinstance(c, dict): continue
                        is_online = c.get("status") is True or (c.get("ping", {}).get("ts", 0) > (now - 3600) * 1000)
                        
                        if is_online:
                            db.set_bot_status("WA Scanner", f"Checking {dev_id[:8]} for WhatsApp codes...")
                            msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=20", fb.get("auth"))
                            if not msgs_dict: continue
                            
                            msgs = [v for v in msgs_dict.values() if isinstance(v, dict) and v.get("type") == "incoming"]
                            
                            has_ws = False
                            latest_id = 0
                            for m in msgs:
                                txt = (m.get("message") or "").lower()
                                if "whatsapp" in txt or re.search(r'code[:\s]+\d{3}-\d{3}', txt):
                                    has_ws = True
                                    mid = int(m.get("id", 0))
                                    if mid > latest_id: latest_id = mid
                            
                            if has_ws:
                                best_nums = fbu.extract_best_numbers(c, msgs)
                                if best_nums:
                                    num = best_nums[0][0]
                                    real_battery = str(c.get("battery", "0")).replace("%", "")
                                    real_health = fbu.calculate_health(msgs)
                                    
                                    ready_lines[dev_id] = {
                                        "fb_url": fb['url'], "auth": fb.get("auth", ""),
                                        "number": num, "chance": 99, "health": real_health,
                                        "battery": real_battery,
                                        "time": int(now), "sort_id": latest_id
                                    }
            
            db.set_bot_status("WA Scanner", f"✅ Saved {len(ready_lines)} WA lines in DB. Sleeping 60s...")
            d = db.load_data()
            d["whatsapp_ready_lines"] = ready_lines
            db.save_data(d)
            log.info(f"Updated {len(ready_lines)} WhatsApp ready lines in DB.")
            
        except Exception as e:
            db.set_bot_status("WA Scanner", f"Error: {str(e)[:30]}")
            log.error(f"WA Scanner error: {e}")
        await asyncio.sleep(60)

async def backup_scanner(bot):
    log.info("Backup Scanner Started...")
    while True:
        try:
            d = db.load_data()
            fbs = d.get("firebases", [])
            if fbs:
                all_devs = []
                db.set_bot_status("Backup Scanner", "Fetching all devices...")
                for fb in fbs:
                    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json?shallow=true", fb.get("auth"))
                    if clients and isinstance(clients, dict):
                        for dev_id in clients.keys(): all_devs.append((fb, dev_id))
                
                now = int(time.time())
                missing = []
                for fb, dev_id in all_devs:
                    bkp = d.get("device_backups", {}).get(dev_id, {})
                    if not bkp.get("numbers") or (now - bkp.get("time", 0) > 172800): missing.append((fb, dev_id))
                
                random.shuffle(missing)
                for fb, dev_id in missing[:10]:
                    db.set_bot_status("Backup Scanner", f"Extracting number for {dev_id[:8]}...")
                    msgs = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=20", fb.get("auth"))
                    dev_data = await fbu.fetch_fb(f"{fb['url']}/clients/{dev_id}.json", fb.get("auth"))
                    if msgs and isinstance(msgs, dict) and dev_data and isinstance(dev_data, dict):
                        msgs_list = [v for k, v in msgs.items() if isinstance(v, dict) and v.get("type") == "incoming"]
                        best_nums = fbu.extract_best_numbers(dev_data, msgs_list)
                        if best_nums:
                            nums = [n for n, c in best_nums]
                            if "device_backups" not in d: d["device_backups"] = {}
                            d["device_backups"][dev_id] = {"numbers": nums, "time": int(time.time())}
                
                if "device_backups" in d:
                    for dev_id in list(d["device_backups"].keys()):
                        if now - d["device_backups"][dev_id].get("time", 0) > 172800: del d["device_backups"][dev_id]
                db.save_data(d)
                db.set_bot_status("Backup Scanner", "Backup loop done. Sleeping 10s...")

            timers = d.get("upcoming_timers", {})
            now = int(time.time())
            changed = False
            for key, t in list(timers.items()):
                if t.get("alert_5m") is False and (t["target_time"] - now) <= 300:
                    try: await bot.send_message(t["user_id"], f"⏰ <b>{sc('otp alert')}</b>\nAapka OTP aane wala hai (5 min baaki)!\n📞 <code>{t['number']}</code>", parse_mode="HTML")
                    except: pass
                    t["alert_5m"] = True
                    changed = True
                if t.get("alert_2m") is False and (t["target_time"] - now) <= 120:
                    try: await bot.send_message(t["user_id"], f"⏰ <b>{sc('otp alert')}</b>\nSirf 2 minute bache hain!\n📞 <code>{t['number']}</code>", parse_mode="HTML")
                    except: pass
                    t["alert_2m"] = True
                    changed = True
                if now >= t["target_time"] and t.get("alert_now") is False:
                    try: await bot.send_message(t["user_id"], f"🚀 <b>{sc('otp window open')}</b>\nAb try karein!\n📞 <code>{t['number']}</code>", parse_mode="HTML")
                    except: pass
                    t["alert_now"] = True
                    changed = True
            if changed: db.save_data(d)
            
            await asyncio.sleep(10)
        except Exception as e:
            db.set_bot_status("Backup Scanner", f"Error: {str(e)[:30]}")
            log.error(f"Backup Scanner error: {e}")
            await asyncio.sleep(10)
