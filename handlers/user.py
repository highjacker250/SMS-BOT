from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
import random, time, asyncio, logging, re
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import clear_user_lease, get_countries, get_servers_grouped, is_owner, get_ist_time_str
from states import S
import config

log = logging.getLogger("UserHandler")
user_router = Router()

def main_kb(uid):
    d = db.load_data()
    is_vip = uid in d.get("vip_users", []) or is_owner(uid)
    kb = [
        [btn("get number", "user:get_num", "📱"), btn("my numbers", "user:saved", "⭐")],
        [btn("otp history", "user:history", "📜"), btn("help/support", "user:support", "🆘")]
    ]
    if is_vip:
        kb.append([btn("upcoming ws otps", "user:upcoming", "📅")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@user_router.message(CommandStart())
async def cmd_start(msg: Message):
    uid = msg.from_user.id
    d = db.load_data()
    clear_user_lease(uid)
    if str(uid) not in d["users"]:
        d["users"][str(uid)] = {"name": msg.from_user.full_name, "joined": int(time.time()), "otp_history": [], "saved_numbers": {}}
        db.save_data(d)

    if uid == config.MAIN_OWNER or is_owner(uid):
        from handlers.admin import admin_home_msg
        await admin_home_msg(msg)
        return

    await msg.answer(f"👋 <b>{sc('welcome to dark otp bot')}</b>\n{sc('select an option below')}:", reply_markup=main_kb(uid), parse_mode="HTML")

@user_router.callback_query(F.data == "user:home")
async def user_home(cq: CallbackQuery):
    await cq.answer()
    clear_user_lease(cq.from_user.id)
    try: await cq.message.edit_text(f"👋 <b>{sc('main menu')}</b>", reply_markup=main_kb(cq.from_user.id), parse_mode="HTML")
    except: pass

@user_router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    await cq.answer()
    clear_user_lease(cq.from_user.id)
    d = db.load_data()
    countries = get_countries(d)
    if not countries: return await cq.message.edit_text("❌ No servers available.", parse_mode="HTML")
    kb = [[btn(c, f"user:country:{c}", "🌍")] for c in countries]
    kb.append([btn("main menu", "user:home", "🏠")])
    await cq.message.edit_text(f"🌍 <b>{sc('select country')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("user:country:"))
async def user_country(cq: CallbackQuery):
    await cq.answer()
    country = cq.data.split(":")[2]
    d = db.load_data()
    servers = get_servers_grouped(d, country)
    if not servers: return await cq.message.edit_text("No servers in this country.")
    
    is_vip = cq.from_user.id in d.get("vip_users", []) or is_owner(cq.from_user.id)
    
    if is_vip:
        # VIP Flow: Service Selection
        kb = [[btn("whatsapp", f"user:service:{country}:whatsapp", "💬")]]
        kb.append([btn("telegram", f"user:service:{country}:telegram", "✈️")])
        kb.append([btn("any service", f"user:service:{country}:any", "🌐")])
        kb.append([btn("back", "user:get_num", "🔙")])
        await cq.message.edit_text(f"🌍 {country} - <b>{sc('select service')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    else:
        # Normal Flow: Direct Servers
        kb = []
        for i, srv in enumerate(servers):
            ping = await f
