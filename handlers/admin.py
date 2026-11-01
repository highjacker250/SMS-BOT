from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
import time
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_admin, get_countries, get_servers_grouped
from states import S

admin_router = Router()

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("enter as user", "user:home", "👤"), btn("analytics", "admin:analytics", "📊")],
        [btn("manage servers", "admin:manage_fb", "🔥"), btn("manage bots", "admin:bots", "🤖")],
        [btn("manage admins", "admin:admins", "🛡"), btn("broadcast", "admin:broadcast", "📢")],
        [btn("view users", "admin:users", "👥"), btn("refresh panel", "admin:home", "🔄")]
    ])

async def admin_home_msg(msg: Message):
    d = db.load_data()
    fbs = d.get("firebases", [])
    countries = get_countries(d)
    users_count = len(d.get("users", {}))
    total_servers = sum(len(get_servers_grouped(d, c)) for c in countries)
        
    text = (
        f"👑 <b>{sc('admin dashboard')}</b>\n\n"
        f"🌍 {sc('countries')}: <b>{len(countries)}</b>\n"
        f"🔥 {sc('total servers')}: <b>{total_servers}</b>\n"
        f"📱 {sc('total bases')}: <b>{len(fbs)}</b>\n"
        f"👥 {sc('total users')}: <b>{users_count}</b>\n\n"
        f"<i>{sc('select an option below to manage the bot')}</i>"
    )
    try: await msg.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    except: pass

@admin_router.message(Command("admin"))
async def admin_panel_cmd(msg: Message):
    if not is_admin(msg.from_user.id): return
    await admin_home_msg(msg)

@admin_router.callback_query(F.data == "admin:home")
async def admin_home(cq: CallbackQuery):
    await cq.answer()
    if not is_admin(cq.from_user.id): return
    await admin_home_msg(cq.message)

@admin_router.callback_query(F.data == "admin:manage_fb")
async def admin_manage_fb(cq: CallbackQuery):
    await cq.answer()
    if not is_admin(cq.from_user.id): return
    d = db.load_data()
    countries = get_countries(d)
    kb = [[btn(c, f"admin:country:{c}", "🌍")] for c in countries]
    kb.append([btn("add country", "admin:add_country", "➕")])
    kb.append([btn("dead filter", "admin:dead_filter", "☠️")])
    kb.append([btn("add bulk urls", "admin:add_bulk", "➕")])
    kb.append([btn("back", "admin:home", "🔙")])
    await cq.message.edit_text(f"🔥 <b>{sc('manage servers')}</b>\n\n{sc('select a country or add new urls')}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin:add_country")
async def admin_add_country(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    if not is_admin(cq.from_user.id): return
    await state.set_state(S.add_country)
    await cq.message.edit_text("Enter Country Name (e.g. USA, UK):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:manage_fb", "❌")]]))

@admin_router.message(S.add_country)
async def admin_add_country_done(msg: Message, state: FSMContext):
    await state.clear()
    country = msg.text.strip().title()
    d = db.load_data()
    if country not in get_countries(d):
        d.setdefault("custom_countries", []).append(country)
        db.save_data(d)
    await msg.answer(f"✅ Country {country} added!", reply_markup=admin_kb())

@admin_router.callback_query(F.data == "admin:dead_filter")
async def admin_dead_filter(cq: CallbackQuery):
    await cq.answer()
    if not is_admin(cq.from_user.id): return
    d = db.load_data()
    fbs = d.get("firebases", [])
    try: await cq.message.edit_text("🔄 Checking dead bases...")
    except: pass
    
    dead_fbs = []
    for i, fb in enumerate(fbs):
        ping = await fbu.check_ping(fb["url"], fb.get("auth"))
        if "Timeout" in ping:
            dead_fbs.append((i, fb))
            
    if not dead_fbs:
        return await cq.message.edit_text("✅ No dead bases found!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:manage_fb", "🔙")]]))
        
    kb = []
    for i, fb in dead_fbs:
        kb.append([btn(f"delete {fb.get('label', 'Base')}", f"admin:rmdo_global:{i}", "🗑")])
    kb.append([btn("back", "admin:manage_fb", "🔙")])
    await cq.message.edit_text(f"☠️ <b>Dead Bases Found: {len(dead_fbs)}</b>\nRemove them to clean up:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:rmdo_global:"))
async def admin_rmdo_global(cq: CallbackQuery):
    await cq.answer("✅ Removed!")
    idx = int(cq.data.split(":")[2])
    d = db.load_data()
    if 0 <= idx < len(d["firebases"]):
        del d["firebases"][idx]
        db.save_data(d)
    await admin_manage_fb(cq)

@admin_router.callback_query(F.data == "admin:add_bulk")
async def admin_bulk_start(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    if not is_admin(cq.from_user.id): return
    await state.set_state(S.add_bulk_urls)
    text = (
        "Send URLs one per line:\n\n"
        "<code>URL</code>\n"
        "<code>URL | AuthKey</code>\n"
        "<code>URL | AuthKey | Secret</code> (Only Owner/VIP can see)"
    )
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:manage_fb", "❌")]]), parse_mode="HTML")

@admin_router.message(S.add_bulk_urls)
async def admin_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    d = db.load_data()
    added = 0
    country = "India"
    
    for line in msg.text.strip().split("\n"):
        if not line.strip(): continue
        
        parts = [p.strip() for p in line.split("|")]
        url = parts[0]
        auth_key = parts[1] if len(parts) > 1 else ""
        is_secret = True if len(parts) > 2 and parts[2].lower() == "secret" else False
        
        if "#DARKs=" in url or "?s=" in url:
            dec = fbu.decode_panel_url(url)
            if dec: url = dec[0]
                
        if url.startswith("http"):
            d["firebases"].append({"url": url, "label": "Base ?", "country": country, "auth": auth_key, "secret": is_secret})
            added += 1
            
    curr = 1
    for f in d["firebases"]:
        if f.get("country") == country:
            f["label"] = f"Base {curr}"
            curr += 1
    db.save_data(d)
    await msg.answer(f"✅ {added} Bases added!", reply_markup=admin_kb())1
