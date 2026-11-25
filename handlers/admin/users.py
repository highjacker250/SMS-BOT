# handlers/admin/users.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import time, asyncio
import database as db
from utils.ui import sc, btn
from utils.helper import get_ist_time_str, is_owner, is_admin
from states import S

admin_router = Router()

@admin_router.callback_query(F.data == "admin:users")
async def admin_users_list(cq: CallbackQuery):
    await cq.answer()
    d = db.load_data()
    users = d.get("users", {})
    if not users:
        return await cq.message.edit_text("👥 No users found.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:home", "🔙")]]))
    
    text = f"👥 <b>Total Users: {len(users)}</b>\n\n"
    kb = []
    # 🚨 Add Broadcast & Credits button (Owner only)
    if is_owner(cq.from_user.id):
        kb.append([btn("broadcast msg", "admin:broadcast_prompt", "📢")])
        
    for uid, u_data in list(users.items())[:20]:
        name = u_data.get("name", "Unknown")
        is_ban = uid in d.get("banned", [])
        status = "🚫" if is_ban else "✅"
        kb.append([btn(f"{status} {name[:15]}", f"admin:user_info:{uid}", "👤")])
        
    kb.append([btn("back", "admin:home", "🔙")])
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin:user_info:"))
async def admin_user_info(cq: CallbackQuery):
    await cq.answer()
    uid = cq.data.split(":")[2]
    d = db.load_data()
    u_data = d.get("users", {}).get(uid)
    if not u_data:
        return await cq.answer("User not found!", show_alert=True)
    
    is_ban = uid in d.get("banned", [])
    name = u_data.get("name", "Unknown")
    joined = get_ist_time_str(u_data.get("joined", 0))
    otp_count = len(u_data.get("otp_history", []))
    credits = u_data.get("credits", 0)
    
    text = (
        f"👤 <b>User Info</b>\n\n"
        f"🆔 <b>ID:</b> <code>{uid}</code>\n"
        f"📛 <b>Name:</b> {name}\n"
        f"📅 <b>Joined:</b> {joined}\n"
        f"📜 <b>Total OTPs:</b> {otp_count}\n"
        f"💰 <b>Credits:</b> {credits}\n"
        f"🚫 <b>Status:</b> {'BANNED' if is_ban else 'ACTIVE'}\n\n"
    )
    
    kb = []
    if is_ban:
        kb.append([btn("unban user", f"admin:unban:{uid}", "✅")])
    else:
        kb.append([btn("ban user", f"admin:ban:{uid}", "🚫")])
    
    # 🚨 Add Credits Button
    kb.append([btn("add credits", f"admin:add_cred:{uid}", "➕"), btn("deduct credits", f"admin:ded_cred:{uid}", "➖")])
    kb.append([btn("back", "admin:users", "🔙")])
    
    try:
        await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except:
        pass

@admin_router.callback_query(F.data.startswith("admin:ban:"))
async def admin_ban_user(cq: CallbackQuery):
    await cq.answer("User Banned!", show_alert=True)
    uid = cq.data.split(":")[2]
    d = db.load_data()
    banned = d.setdefault("banned", [])
    if uid not in banned: banned.append(uid)
    db.save_data(d, force=True)
    await admin_user_info(cq)

@admin_router.callback_query(F.data.startswith("admin:unban:"))
async def admin_unban_user(cq: CallbackQuery):
    await cq.answer("User Unbanned!", show_alert=True)
    uid = cq.data.split(":")[2]
    d = db.load_data()
    banned = d.setdefault("banned", [])
    if uid in banned: banned.remove(uid)
    db.save_data(d, force=True)
    await admin_user_info(cq)

# =====================================================
# CREDITS SYSTEM
# =====================================================

@admin_router.callback_query(F.data.startswith("admin:add_cred:"))
async def admin_add_cred_prompt(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    uid = cq.data.split(":")[2]
    await state.update_data(cred_uid=uid, cred_action="add")
    await state.set_state(S.add_credits_amt)
    await cq.message.edit_text(
        f"💰 <b>Add Credits</b>\n\nUser: <code>{uid}</code>\nKitne credits add karne hain? (Number bhejo)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", f"admin:user_info:{uid}", "❌")]]),
        parse_mode="HTML"
    )

@admin_router.callback_query(F.data.startswith("admin:ded_cred:"))
async def admin_ded_cred_prompt(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    uid = cq.data.split(":")[2]
    await state.update_data(cred_uid=uid, cred_action="deduct")
    await state.set_state(S.deduct_credits_amt)
    await cq.message.edit_text(
        f"📉 <b>Deduct Credits</b>\n\nUser: <code>{uid}</code>\nKitne credits deduct karne hain? (Number bhejo)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", f"admin:user_info:{uid}", "❌")]]),
        parse_mode="HTML"
    )

@admin_router.message(S.add_credits_amt)
async def admin_add_cred_amt_done(msg: Message, state: FSMContext):
    try:
        amt = int(msg.text.strip())
        if amt <= 0: raise ValueError
    except:
        return await msg.answer("❌ Invalid amount. Positive number daalein.")
    
    data = await state.get_data()
    await state.clear()
    uid = data.get("cred_uid")
    d = db.load_data()
    user = d.get("users", {}).get(str(uid))
    
    if not user:
        return await msg.answer("❌ User not found.")
        
    user["credits"] = user.get("credits", 0) + amt
    db.save_data(d, force=True)
    
    await msg.answer(f"✅ Added <b>{amt}</b> credits to <code>{uid}</code>.\nNew Balance: {user['credits']}", parse_mode="HTML")
    try: await msg.bot.send_message(int(uid), f"💰 Aapko <b>{amt}</b> credits mile hain!\nNew balance: {user['credits']}", parse_mode="HTML")
    except: pass

@admin_router.message(S.deduct_credits_amt)
async def admin_ded_cred_amt_done(msg: Message, state: FSMContext):
    try:
        amt = int(msg.text.strip())
        if amt <= 0: raise ValueError
    except:
        return await msg.answer("❌ Invalid amount. Positive number daalein.")
    
    data = await state.get_data()
    await state.clear()
    uid = data.get("cred_uid")
    d = db.load_data()
    user = d.get("users", {}).get(str(uid))
    
    if not user:
        return await msg.answer("❌ User not found.")
        
    user["credits"] = max(0, user.get("credits", 0) - amt)
    db.save_data(d, force=True)
    
    await msg.answer(f"✅ Deducted <b>{amt}</b> credits from <code>{uid}</code>.\nNew Balance: {user['credits']}", parse_mode="HTML")

# =====================================================
# BROADCAST
# =====================================================

@admin_router.callback_query(F.data == "admin:broadcast_prompt")
async def admin_broadcast_prompt(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    if not is_owner(cq.from_user.id): return
    await state.set_state(S.broadcast)
    await cq.message.edit_text(
        "📢 <b>Broadcast Message</b>\n\nSabhi users ko bhejne ke liye message type karein:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:users", "❌")]]),
        parse_mode="HTML"
    )

@admin_router.message(S.broadcast)
async def admin_broadcast_done(msg: Message, state: FSMContext):
    await state.clear()
    if not is_owner(msg.from_user.id): return
    d = db.load_data()
    users = list(d.get("users", {}).keys())
    
    status = await msg.answer(f"📢 Broadcasting to {len(users)} users...")
    success = 0
    failed = 0
    
    for uid in users:
        try:
            await msg.bot.send_message(int(uid), msg.text)
            success += 1
            await asyncio.sleep(0.05) # Prevent flood
        except:
            failed += 1
            
    await status.edit_text(f"📢 <b>Broadcast Complete</b>\n\n✅ Sent: {success}\n❌ Failed: {failed}", parse_mode="HTML")
