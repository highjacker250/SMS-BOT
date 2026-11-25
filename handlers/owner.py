from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
import database as db
from utils.helper import is_owner

owner_router = Router()

@owner_router.message(Command("addvip"))
async def cmd_add_vip(msg: Message):
    if not is_owner(msg.from_user.id): return
    parts = msg.text.split()
    if len(parts) != 2: return await msg.answer("Usage: /addvip <user_id>")
    try:
        uid = int(parts[1])
        d = db.load_data()
        if uid not in d.setdefault("vip_users", []):
            d["vip_users"].append(uid)
            db.save_data(d)
            await msg.answer(f"✅ <code>{uid}</code> is now a VIP user!", parse_mode="HTML")
    except: await msg.answer("Invalid ID.")
