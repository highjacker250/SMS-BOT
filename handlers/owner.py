from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
import asyncio, time
import database as db
from utils.ui import sc, btn
from utils.helper import is_owner
from states import S

owner_router = Router()

@owner_router.message(Command("add_bot"))
async def cmd_add_bot(msg: Message):
    if not is_owner(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) != 2: return await msg.answer("Usage: /add_bot <token>")
    token = parts[1]
    
    d = db.load_data()
    if token not in d.setdefault("extra_tokens", []):
        d["extra_tokens"].append(token)
        db.save_data(d)
        
        from services.otp_service import start_scanner
        from aiogram import Bot, Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage
        from handlers.user import user_router
        from handlers.admin import admin_router
        from handlers.owner import owner_router
        
        new_bot = Bot(token=token)
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_routers(owner_router, admin_router, user_router)
        asyncio.create_task(dp.start_polling(new_bot))
        asyncio.create_task(start_scanner(new_bot))
        
        await msg.answer("✅ Bot added and running!")
    else:
        await msg.answer("Bot already exists.")

@owner_router.callback_query(F.data == "admin:analytics")
async def admin_analytics(cq: CallbackQuery):
    if not is_owner(cq.from_user.id): return
    d = db.load_data()
    leases = d.get("user_leases", {})
    text = "📊 <b>Active Leases</b>\n\n"
    count = 0
    for uid, l in leases.items():
        if time.time() < l["expire_at"]:
            text += f"👤 <code>{uid}</code> | 🆔 {l['dev_id'][:8]} | {l.get('base_idx')}\n"
            count += 1
    if count == 0: text += "No active leases."
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]), parse_mode="HTML")

@owner_router.callback_query(F.data == "admin:broadcast")
async def owner_broadcast_start(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id): return
    await state.set_state(S.broadcast)
    await cq.message.edit_text("Send message to broadcast:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:home", "❌")]]))

@owner_router.message(S.broadcast)
async def owner_broadcast_done(msg: Message, state: FSMContext):
    await state.clear()
    d = db.load_data()
    users = list(d.get("users", {}).keys())
    ok = 0
    for u in users:
        try:
            await msg.bot.copy_message(int(u), msg.chat.id, msg.message_id)
            ok += 1
            await asyncio.sleep(0.05)
        except: pass
    await msg.answer(f"✅ Sent to {ok} users.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]))
