import asyncio, time, logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
import database as db
import firebase_utils as fbu
from utils.ui import sc

log = logging.getLogger("Scanner")

async def send_otp_to_user(bot, uid, service, otp, msg_text, rent_id):
    otp_msg = (
        f"🔔 <b>{sc('otp received')}!</b>\n\n"
        f"📱 <b>{sc('service')}:</b> {service}\n"
        f"🔑 <b>{sc('otp')}:</b> <code>{otp}</code>\n\n"
        f"🆔 <b>{sc('rent id')}:</b> <code>{rent_id}</code>\n"
        f"💬 <i>{msg_text[:60]}...</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{otp}", copy_text=CopyTextButton(text=otp))]])
    
    d = db.load_data()
    user = d["users"].get(str(uid))
    if user:
        hist = user.setdefault("otp_history", [])
        hist.insert(0, {"service": service, "otp": otp, "time": int(time.time())})
        user["otp_history"] = hist[:20]
        db.save_data(d)
        
    try: await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
    except Exception: pass

async def check_device(bot, fb_url, auth, dev_id, users, last_msg_id):
    url = f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=1"
    msgs = await fbu.fetch_fb(url, auth)
    if not msgs: return last_msg_id
    
    msg_id, msg = list(msgs.items())[0]
    if not isinstance(msg, dict) or msg.get("type") != "incoming": return last_msg_id
    
    current_id = int(msg.get("id", 0))
    if current_id > last_msg_id:
        text = msg.get("message", "")
        otp = fbu.extract_otp(text)
        if otp:
            service = fbu.extract_service_name(text, msg.get("sender", ""))
            for uid in users:
                await send_otp_to_user(bot, uid, service, otp, text, dev_id)
        return current_id
    return last_msg_id

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
                    fb_url = lease.get("fb_url")
                    dev_id = lease.get("dev_id")
                    if fb_url and dev_id:
                        key = (fb_url, dev_id)
                        if key not in device_to_users:
                            device_to_users[key] = {"users": [], "last_msg_id": lease.get("last_msg_id", 0)}
                        device_to_users[key]["users"].append(uid)
            
            if device_to_users:
                tasks = []
                keys = list(device_to_users.keys())
                for key in keys:
                    fb_url, dev_id = key
                    auth = fbs.get(fb_url, "")
                    tasks.append(check_device(bot, fb_url, auth, dev_id, device_to_users[key]["users"], device_to_users[key]["last_msg_id"]))
                
                results = await asyncio.gather(*tasks)
                
                updated = False
                for idx, key in enumerate(keys):
                    new_id = results[idx]
                    if new_id > device_to_users[key]["last_msg_id"]:
                        for uid in device_to_users[key]["users"]:
                            if uid in leases: 
                                leases[uid]["last_msg_id"] = new_id
                                updated = True
                if updated: db.save_data(d)

            await asyncio.sleep(1.5)
        except Exception as e:
            log.error(f"Scanner error: {e}")
            await asyncio.sleep(3)
