# handlers/user/account_login.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import database as db
import asyncio
import time
import uuid
from utils.ui import sc, btn
from states import S
from services.browser_automation import login_manual_target, create_target_account
import config

account_login_router = Router()

@account_login_router.callback_query(F.data == "user:acc_login")
async def start_acc_login(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    kb = [
        [btn("PayPal", "user:acc_plat:paypal", "💳"), btn("Facebook", "user:acc_plat:facebook", "📘")],
        [btn("Instagram", "user:acc_plat:instagram", "📸")],
        [btn("cancel", "user:main_menu", "❌")]
    ]
    await state.set_state(S.user_manual_login_platform)
    await cq.message.edit_text(
        "🔐 <b>Account Login</b>\n\nSelect platform jiska account login karna hai:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), 
        parse_mode="HTML"
    )

@account_login_router.callback_query(S.user_manual_login_platform, F.data.startswith("user:acc_plat:"))
async def select_platform(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    platform = cq.data.split(":")[2]
    await state.update_data(platform=platform)
    await state.set_state(S.user_manual_login_phone)
    await cq.message.edit_text(
        f"✅ Platform: {platform.upper()}\n\n"
        f"Ab apna mobile number daalein (with +91):"
    )

@account_login_router.message(S.user_manual_login_phone)
async def get_manual_phone(msg: Message, state: FSMContext):
    phone = msg.text.strip()
    if not phone.startswith("+"):
        return await msg.answer("❌ Number must start with + (e.g., +919876543210)")
    
    await state.update_data(phone=phone)
    status = await msg.answer("🔄 Sending OTP via AI Browser...")
    
    # Yahan Playwright trigger hoga OTP bhejne ke liye
    # Filhaal hum user ko OTP maang rahe hain
    await state.set_state(S.user_manual_login_otp)
    await status.edit_text(f"📩 OTP sent to {phone}. Please enter the OTP:")

@account_login_router.message(S.user_manual_login_otp)
async def get_manual_otp(msg: Message, state: FSMContext):
    otp = msg.text.strip()
    data = await state.get_data()
    status = await msg.answer("🔄 Logging in via AI Browser...")
    
    # 🚨 AI Browser se login karega (Playwright)
    res = await login_manual_target(data['platform'], data['phone'], otp)
    
    if res["status"] == "success":
        d = db.load_data()
        if "target_accounts" not in d: d["target_accounts"] = {}
        
        acc_id = str(uuid.uuid4())[:8]
        d["target_accounts"][acc_id] = {
            "user_id": msg.from_user.id, 
            "platform": data['platform'],
            "phone": data['phone'],
            "status": "active", 
            "cookies": res.get("cookies", ""), 
            "time": int(time.time())
        }
        db.save_data(d)
        
        token = str(uuid.uuid4())
        if "mini_tokens" not in d: d["mini_tokens"] = {}
        d["mini_tokens"][token] = msg.from_user.id
        db.save_data(d)
        
        await state.clear()
        await status.edit_text(
            f"✅ <b>Login Successful!</b>\n\n"
            f"Account: <code>{data['phone']}</code>\n"
            f"Platform: {data['platform'].upper()}\n\n"
            f"🔗 <a href='{config.WEB_URL}/mini_panel/{token}'>Click Here to Access Panel</a>",
            parse_mode="HTML"
        )
    else:
        await status.edit_text(f"❌ Failed: {res.get('reason')}\n\nAccount nahi mila? AI naya account bana sakta hai.")
        kb = [[btn("Create New Account", f"user:create_acc:{data['platform']}", "➕")], [btn("cancel", "user:main_menu", "❌")]]
        await msg.answer("Kya aap naya account banana chahte hain?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@account_login_router.callback_query(F.data.startswith("user:create_acc:"))
async def create_account_btn(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    platform = cq.data.split(":")[2]
    await state.update_data(platform=platform)
    
    await state.set_state(S.user_manual_create_name)
    await cq.message.edit_text(
        f"🛠 <b>Create New {platform.upper()} Account</b>\n\n"
        f"AI account banayega. Kuch details chahiye:\n\n"
        f"<b>Apna Naam daalein:</b>\n"
        f"(Ya /skip bhejein default name ke liye)"
    )

@account_login_router.message(S.user_manual_create_name)
async def get_create_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if name.startswith("/skip"):
        name = "Rahul Sharma"
    await state.update_data(name=name)
    
    await state.set_state(S.user_manual_create_age)
    await msg.answer(f"✅ Name: {name}\n\n<b>Apni Age daalein:</b>\n(Ya /skip bhejein default (25) ke liye)")

@account_login_router.message(S.user_manual_create_age)
async def get_create_age(msg: Message, state: FSMContext):
    age = msg.text.strip()
    if age.startswith("/skip"):
        age = "25"
    await state.update_data(age=age)
    
    await state.set_state(S.user_manual_create_loc)
    await msg.answer(f"✅ Age: {age}\n\n<b>Apni Location (City) daalein:</b>\n(Ya /skip bhejein default (Mumbai) ke liye)")

@account_login_router.message(S.user_manual_create_loc)
async def get_create_loc(msg: Message, state: FSMContext):
    loc = msg.text.strip()
    if loc.startswith("/skip"):
        loc = "Mumbai"
    
    data = await state.get_data()
    await state.clear()
    
    status = await msg.answer(f"⏳ AI is creating {data['platform'].upper()} account for {data['name']}...\nPlease wait...")
    
    # 🚨 AI Browser se account create karega (Playwright)
    res = await create_target_account(data['platform'], data['name'], data['age'], data['loc'])
    
    if res["status"] == "success":
        d = db.load_data()
        if "target_accounts" not in d: d["target_accounts"] = {}
        
        acc_id = str(uuid.uuid4())[:8]
        d["target_accounts"][acc_id] = {
            "user_id": msg.from_user.id, 
            "platform": data['platform'],
            "phone": res.get("phone", "N/A"),
            "status": "active", 
            "cookies": res.get("cookies", ""), 
            "time": int(time.time())
        }
        db.save_data(d)
        
        token = str(uuid.uuid4())
        if "mini_tokens" not in d: d["mini_tokens"] = {}
        d["mini_tokens"][token] = msg.from_user.id
        db.save_data(d)
        
        await status.edit_text(
            f"✅ <b>Account Created!</b>\n\n"
            f"Platform: {data['platform'].upper()}\n"
            f"Name: {data['name']}\n"
            f"Phone: {res.get('phone', 'N/A')}\n\n"
            f"🔗 <a href='{config.WEB_URL}/mini_panel/{token}'>Click Here to Access Panel</a>",
            parse_mode="HTML"
        )
    else:
        await status.edit_text(f"❌ Account creation failed: {res.get('reason')}")
