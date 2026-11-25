# handlers/user/urllogin.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import uuid
import time
import config
from utils.ui import sc, btn
from states import S
from services.browser import get_login_automation

urllogin_router = Router()

# Platform URL mapping (matching constants.py)
PLATFORM_LOGIN_URLS = {
    "instagram": "https://www.instagram.com/accounts/login/",
    "facebook": "https://www.facebook.com/login",
    "paypal": "https://www.paypal.com/in/signin",
    "telegram": "https://web.telegram.org/k/",
    "google": "https://accounts.google.com/signin",
    "x": "https://twitter.com/i/flow/login",
    "github": "https://github.com/login",
}

# --- Dashboard ---
@urllogin_router.callback_query(F.data == "user:acc_login")
async def start_acc_login(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    panel_url = f"{config.WEB_URL}/user_panel/{cq.from_user.id}"
    kb = [
        [btn("Open My App Dashboard", f"user:open_panel", "🌐")],
        [btn("login via URL", "user:url_login", "🔗")],
        [btn("cancel", "user:main_menu", "❌")]
    ]
    await state.set_state(S.user_manual_login_platform)
    await cq.message.edit_text(
        f"🔐 <b>Account Logger</b>\n\n"
        f"Apna personal Dashboard kholo aur wahan se koi bhi platform select karo.\n\n"
        f"🔗 <b>Dashboard Link:</b>\n<a href='{panel_url}'>{panel_url}</a>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )

@urllogin_router.callback_query(F.data == "user:open_panel")
async def open_panel(cq: CallbackQuery):
    await cq.answer("Open the link sent above!", show_alert=True)

# --- Direct Platform Login (button click se) ---
@urllogin_router.callback_query(F.data.startswith("login_platform:"))
async def platform_login(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    platform = cq.data.split(":")[1]

    if platform == "custom":
        await state.set_state(S.url_login_input)
        await cq.message.edit_text(
            f"🔗 <b>Custom URL Login</b>\n\nLogin page ka URL bhejo:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:acc_login", "❌")]]),
            parse_mode="HTML"
        )
        return

    login_url = PLATFORM_LOGIN_URLS.get(platform, "")
    if not login_url:
        return await cq.answer("Platform not supported yet.", show_alert=True)

    await state.update_data(login_url=login_url, platform=platform.capitalize())
    await state.set_state(S.url_login_phone)
    await cq.message.edit_text(
        f"✅ <b>Platform:</b> {platform.upper()}\n\nAb apna <b>mobile number / email</b> daalo jo login page mein fill karna hai:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:acc_login", "❌")]]),
        parse_mode="HTML"
    )

# --- URL Login (custom) ---
@urllogin_router.callback_query(F.data == "user:url_login")
async def start_url_login(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(S.url_login_input)
    await cq.message.edit_text(
        f"🔗 <b>{sc('url login')}</b>\n\n"
        f"Login page ka URL bhejo (e.g., <code>https://instagram.com/accounts/login</code>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]),
        parse_mode="HTML"
    )

@urllogin_router.message(S.url_login_input)
async def receive_url(msg: Message, state: FSMContext):
    raw_url = msg.text.strip()
    if not raw_url.startswith("http"):
        raw_url = "https://" + raw_url

    # Use the new browser service's detection
    automation = await get_login_automation()
    platform = automation._detect_platform(raw_url)

    if platform == "Unknown":
        return await msg.answer(f"❌ Platform detect nahi hua URL se: <code>{raw_url}</code>", parse_mode="HTML")

    await state.update_data(login_url=raw_url, platform=platform)
    await state.set_state(S.url_login_phone)
    await msg.answer(f"✅ <b>Detected:</b> {platform}\n\nAb apna <b>mobile number / email</b> daalo:")

@urllogin_router.message(S.url_login_phone)
async def receive_phone(msg: Message, state: FSMContext):
    phone = msg.text.strip()
    await state.update_data(phone=phone)
    await state.set_state(S.url_login_password)
    await msg.answer(f"📞 Phone set: <code>{phone}</code>\n\nAb <b>password</b> daalo (ya <code>/skip</code> bhejo agar OTP flow hai):")

@urllogin_router.message(S.url_login_password)
async def receive_password(msg: Message, state: FSMContext):
    password = None if msg.text.strip().lower() == "/skip" else msg.text.strip()
    data = await state.get_data()
    await state.clear()

    login_url = data.get("login_url")
    platform = data.get("platform")
    phone = data.get("phone")

    status = await msg.answer(
        f"🔄 <b>Logging in via AI Browser...</b>\n\n"
        f"Platform: {platform}\n\n"
        f"<i>Live view panel me dekho:</i> <a href='{config.WEB_URL}/'>Web Panel</a>",
        parse_mode="HTML"
    )

    # Use the new LoginAutomation service
    automation = await get_login_automation()
    res = await automation.login_with_url(login_url, phone, password=password)

    # Use the new database service
    from services.database import get_db, database_transaction
    async with database_transaction() as db_data:
        if "target_accounts" not in db_data:
            db_data["target_accounts"] = {}
        acc_id = str(uuid.uuid4())[:8]
        db_data["target_accounts"][acc_id] = {
            "user_id": msg.from_user.id,
            "platform": platform,
            "phone": phone,
            "status": res.get("status", "failed"),
            "time": int(time.time()),
        }

    panel_url = f"{config.WEB_URL}/user_panel/{msg.from_user.id}"

    if res["status"] == "success":
        await status.edit_text(
            f"✅ <b>Login Successful!</b>\n\n"
            f"Platform: {platform}\n"
            f"🔗 <a href='{panel_url}'>Open Your App Dashboard</a>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("my dashboard", "user:open_panel", "📱")]]),
            parse_mode="HTML"
        )
    else:
        await status.edit_text(
            f"❌ <b>Failed:</b> {res.get('reason','Unknown error')}\n\n"
            f"<i>Screenshot dekho live view panel pe — real page ka status dikhega.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("retry", "user:url_login", "🔄")]]),
            parse_mode="HTML"
        )