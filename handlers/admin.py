from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import time
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_admin, get_countries, get_servers_grouped
from states import S

admin_router = Router()

# ... (admin_kb, admin_home, admin_manage_fb, admin_country, admin_server, admin_base, admin_device, admin_rmmenu, admin_rmdo same rahenge) ...

@admin_router.callback_query(F.data == "admin:add_bulk")
async def admin_bulk_start(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return
    await state.set_state(S.add_bulk_urls)
    await cq.message.edit_text("Send URLs one per line (Panel link or Firebase URL):\nFormat:\n<code>URL</code>\nOR\n<code>URL | AuthKey</code>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:manage_fb", "❌")]]), parse_mode="HTML")

@admin_router.message(S.add_bulk_urls)
async def admin_bulk_done(msg: Message, state: FSMContext):
    await state.clear()
    d = db.load_data()
    added = 0
    country = "India"
    
    for line in msg.text.strip().split("\n"):
        if not line.strip(): continue
        
        parts = line.split("|")
        url = parts[0].strip()
        auth_key = parts[1].strip() if len(parts) > 1 else ""
        
        if "#DARKs=" in url or "?s=" in url:
            dec = fbu.decode_panel_url(url)
            if dec: 
                url = dec[0]
                if not auth_key and dec[1]: auth_key = dec[1]
                
        if url.startswith("http"):
            d["firebases"].append({"url": url, "label": "Base ?", "country": country, "auth": auth_key})
            added += 1
            
    curr = 1
    for f in d["firebases"]:
        if f.get("country") == country:
            f["label"] = f"Base {curr}"
            curr += 1
    db.save_data(d)
    await msg.answer(f"✅ {added} Bases added with Auth Keys!", reply_markup=admin_kb())w
