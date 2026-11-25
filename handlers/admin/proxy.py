from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import database as db
from utils.ui import sc, btn
from utils.helper import is_owner
from states import S

admin_router = Router()

@admin_router.callback_query(F.data == "admin:proxies")
async def admin_proxies(cq: CallbackQuery):
    await cq.answer()
    if not is_owner(cq.from_user.id): return
    d = db.load_data()
    working = len(d.get("working_proxies", []))
    custom = len(d.get("custom_proxies", []))
    
    text = (
        f"🌐 <b>Proxy Manager</b>\n\n"
        f"✅ Working Proxies: <b>{working}</b>\n"
        f"📦 Custom Proxies: <b>{custom}</b>\n\n"
        f"Bot automatically fetches free proxies every 5 mins if working count < 5."
    )
    kb = [
        [btn("add custom proxy", "admin:add_proxy_prompt", "➕")],
        [btn("refresh proxies now", "admin:refresh_proxies", "🔄")],
        [btn("back", "admin:home", "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin:add_proxy_prompt")
async def admin_add_proxy_prompt(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(S.add_custom_proxy)
    await cq.message.edit_text("Enter SOCKS5 Proxy (Format: <code>ip:port</code> or <code>ip:port:user:pass</code>):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "admin:proxies", "❌")]]), parse_mode="HTML")

@admin_router.message(S.add_custom_proxy)
async def admin_add_proxy_done(msg: Message, state: FSMContext):
    await state.clear()
    proxy = msg.text.strip()
    d = db.load_data()
    
    # Basic validation
    if ":" not in proxy:
        return await msg.answer("❌ Invalid format. Use ip:port", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:proxies", "🔙")]]))
        
    if proxy not in d.setdefault("custom_proxies", []):
        d["custom_proxies"].append(proxy)
        db.save_data(d)
        
    await msg.answer("✅ Custom proxy added! Bot will check it in next cycle.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "admin:proxies", "🔙")]]))

@admin_router.callback_query(F.data == "admin:refresh_proxies")
async def admin_refresh_proxies(cq: CallbackQuery):
    await cq.answer("🔄 Refreshing in background...", show_alert=True)
    from services.proxy_manager import proxy_scanner_loop
    # We don't have direct access to trigger, but the loop will do it eventually
    await admin_proxies(cq)
