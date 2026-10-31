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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("OTP-Bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = 8480878371
PORT = int(os.getenv("PORT", 8080))

router = Router()
running_bots = {}
active_scans = {}
scraper_leases = {} # user_id: {"url":, "phone":, "last_sms": "..."}

class AdminStates(StatesGroup):
    add_bulk_urls = State()

async def get_owner_stats():
    # (Same as previous code, returns total, online, fbs)
    pass 

async def background_global_scanner():
    log.info("Global Scanner Started...")
    while True:
        try:
            data = db.load_data()
            fbs = data.get("firebases", [])
            leases = data.get("user_leases", {})
            
            # --- 1. Firebase Scanner ---
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

            # --- 2. Scraper (smstome) Scanner ---
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

            await asyncio.sleep(3) # Fast polling
        except Exception as e:
            log.error(f"Scanner Error: {e}")
            await asyncio.sleep(5)

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

# --- HANDLERS ---
@router.message(CommandStart())
async def cmd_start(msg: Message):
    # Same as before
    pass

@router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    # Now show Countries (Firebase + Scrapers)
    data = db.load_data()
    fb_countries = list(set([fb["label"] for fb in data.get("firebases", [])]))
    
    # Add scraper countries (we can just use popular ones or fetch dynamically)
    scraper_countries = ["United Kingdom", "United States", "Sweden", "Netherlands", "Canada"] 
    all_countries = list(set(fb_countries + scraper_countries))
    
    kb = [[InlineKeyboardButton(text=f"🏳️ {c}", callback_data=f"country:{c}")] for c in all_countries]
    kb.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")])
    await cq.message.edit_text("🌍 <b>Select a Country:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("country:"))
async def user_country_selected(cq: CallbackQuery):
    country = cq.data.split(":")[1]
    data = db.load_data()
    servers = [fb for fb in data.get("firebases", []) if fb["label"] == country]
    
    kb = []
    # Add Firebase Servers
    for i, srv in enumerate(servers):
        short_url = srv["url"].split("//")[-1][:20]
        kb.append([InlineKeyboardButton(text=f"🔥 Firebase {i+1}: {short_url}", callback_data=f"server:fb:{srv['url']}")])
        
    # Add Scraper Servers
    kb.append([InlineKeyboardButton(text=f"🌐 smstome (Free)", callback_data=f"server:scr:smstome:{country}")])
    
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="user:get_num")])
    await cq.message.edit_text(f"🌍 {country} - Select a Server:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@router.callback_query(F.data.startswith("server:"))
async def user_server_selected(cq: CallbackQuery):
    parts = cq.data.split(":")
    srv_type = parts[1]
    uid = cq.from_user.id
    
    if srv_type == "fb":
        server_url = parts[2]
        # (Existing Firebase logic here...)
        pass
        
    elif srv_type == "scr":
        source = parts[2]
        country = parts[3]
        
        await cq.message.edit_text(f"🔄 Fetching free numbers for {country} from {source}...")
        
        # Get country URL
        countries_map = await scr.get_smstome_countries()
        country_url = countries_map.get(country)
        if not country_url:
            return await cq.answer("❌ Country not found on scraper.", show_alert=True)
            
        numbers = await scr.get_smstome_numbers(country_url)
        if not numbers:
            return await cq.answer("❌ No numbers available right now.", show_alert=True)
            
        kb = []
        for num in numbers[:5]: # Show top 5
            kb.append([InlineKeyboardButton(text=f"📞 {num}", callback_data=f"scr_sel:{num}:{country_url}")])
        
        kb.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"country:{country}")])
        await cq.message.edit_text("Select a number to receive OTP:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

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
        "expire_at": int(time.time()) + 1200 # 20 mins
    }
    
    text = (
        f"📱 <b>Number Selected (Free)</b>\n"
        f"🆔 <b>Number:</b> <code>{number}</code>\n\n"
        f"⌛ <i>Waiting for OTP (20 Mins)...</i>"
    )
    kb = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="user:home")]]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

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
