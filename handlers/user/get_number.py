from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
import random, time, asyncio, re
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import clear_user_lease, get_countries, get_servers_grouped, is_owner, is_admin
from services.ai_brain import get_best_number_with_ai

user_router = Router()

@user_router.callback_query(F.data == "user:get_num")
async def user_get_num(cq: CallbackQuery):
    await cq.answer()
    clear_user_lease(cq.from_user.id)
    d = db.load_data()
    countries = get_countries(d)
    if not countries: return await cq.message.edit_text("❌ No servers available.", parse_mode="HTML")
    kb = [[btn(c, f"user:country:{c}", "🌍")] for c in countries]
    kb.append([btn("main menu", "user:main_menu", "🏠")])
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
        # VIP: Service select (WhatsApp/Telegram/Any)
        kb = [
            [btn("whatsapp", f"user:service:{country}:whatsapp", "💬")],
            [btn("telegram", f"user:service:{country}:telegram", "✈️")],
            [btn("any service", f"user:service:{country}:any", "🌐")],
            [btn("back", "user:get_num", "🔙")]
        ]
        await cq.message.edit_text(f"🌍 {country} - <b>{sc('select service')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    else:
        # 🚨 NORMAL USER: Direct Server list (No service select)
        kb = []
        for i, srv in enumerate(servers):
            ping = await fbu.check_ping(srv[0]["url"], srv[0].get("auth"))
            kb.append([btn(f"server {i+1} ({ping})", f"user:server:{country}:{i}", "📁")])
        kb.append([btn("back", "user:get_num", "🔙")])
        await cq.message.edit_text(f"🌍 {country} - <b>{sc('servers')}:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

# Baaki functions (user_service, user_server, info, save, etc.) same rahenge.
# user_service sirf VIP ke liye call hoga ab.
