from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
import asyncio
import database as db
import firebase_utils as fbu
from utils.ui import sc, btn
from utils.helper import is_owner
from states import S

owner_router = Router()

# Add this state to states.py class S: track_query = State()

@owner_router.callback_query(F.data == "owner:track_start")
async def owner_track_start(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id): return await cq.answer("🚫")
    await state.set_state(S.track_query)
    await cq.message.edit_text("🔍 <b>Device Tracker</b>\n\nSend Rent ID or Mobile Number:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:home", "❌")]]))

@owner_router.message(S.track_query)
async def owner_track_done(msg: Message, state: FSMContext):
    await state.clear()
    query = msg.text.strip()
    status = await msg.answer(f"🔄 Searching for <code>{query}</code> across all servers...")
    
    d = db.load_data()
    fbs = d.get("firebases", [])
    
    found = []
    async def check_fb(fb):
        clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
        if not clients: return
        for dev_id, c in clients.items():
            match = False
            if query.lower() in dev_id.lower(): match = True
            if not match and isinstance(c, dict):
                raw = str(c).lower()
                if query in raw: match = True
            if match:
                found.append((fb, dev_id, c))
                
    tasks = [check_fb(fb) for fb in fbs]
    await asyncio.gather(*tasks)
    
    if not found:
        return await status.edit_text(f"❌ No device found for <code>{query}</code>.")
        
    text = f"🔍 <b>Tracker Result ({len(found)} found):</b>\n\n"
    for fb, dev_id, c in found[:5]:
        text += f"🆔 <code>{dev_id}</code>\n🔗 <code>{fb['url']}</code>\n🟢 {c.get('status')} | 🔋 {c.get('battery', '?')}\n\n"
        
    await status.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]), parse_mode="HTML")
