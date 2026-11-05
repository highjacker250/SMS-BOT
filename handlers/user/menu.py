# handlers/user/menu.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
import time, logging
import database as db
from utils.ui import sc, btn
from utils.helper import clear_user_lease, is_owner, get_countries
import config

log = logging.getLogger("UserMenu")
user_router = Router()

def main_kb(uid):
    d = db.load_data()
    is_vip = uid in d.get("vip_users", []) or is_owner(uid)
    kb = [
        [btn("get number", "user:get_num", "📱"), btn("my numbers", "user:saved", "⭐")],
        [btn("otp history", "user:history", "📜"), btn("help/support", "user:support", "🆘")],
        [btn("new ai auto logger", "user:auto_logger", "🤖")] # 🚨 Naya Button
    ]
    if is_vip:
        kb.append([btn("upcoming ws otps", "user:upcoming", "📅")])
        kb.append([btn("vvip numbers", "vvip:home", "🌟")])
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

@user_router.callback_query(F.data == "user:main_menu")
async def user_main_menu_handler(cq: CallbackQuery):
    await cq.answer()
    clear_user_lease(cq.from_user.id)
    try:
        await cq.message.edit_text(
            f"👋 <b>{sc('main menu')}</b>\n\nWelcome {cq.from_user.first_name}!",
            reply_markup=main_kb(cq.from_user.id),
            parse_mode="HTML"
        )
    except: pass

@user_router.callback_query(F.data == "user:support")
async def user_support(cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        f"🆘 <b>{sc('help & support')}</b>\n\nContact Owner: <a href='tg://user?id={config.MAIN_OWNER}'>Click Here</a>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("main menu", "user:main_menu", "🏠")]]),
        parse_mode="HTML"
    )

@user_router.callback_query(F.data == "vvip:home")
async def vvip_home(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    countries = get_countries(d)
    kb = [[btn(c, f"vvip:country:{c}", "🌍")] for c in countries]
    kb.append([btn("main menu", "user:main_menu", "🏠")])
    await cq.message.edit_text("🌟 <b>VVIP NUMBERS</b>\n\nSelect Country:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("vvip:country:"))
async def vvip_country(cq: CallbackQuery):
    await cq.answer()
    country = cq.data.split(":")[2]
    kb = [
        [btn("whatsapp", f"user:service:{country}:whatsapp", "💬")],
        [btn("telegram", f"user:service:{country}:telegram", "✈️")],
        [btn("any service", f"user:service:{country}:any", "🌐")],
        [btn("back", "vvip:home", "🔙")]
    ]
    await cq.message.edit_text(f"🌟 {country} - <b>Select Service:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
