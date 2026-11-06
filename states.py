# states.py
from aiogram.fsm.state import State, StatesGroup

class S(StatesGroup):
    # Purane States
    add_bulk_urls = State()
    add_bot = State()
    add_admin = State()
    ban_user = State()
    broadcast = State()
    add_credits_uid = State()
    add_credits_amt = State()
    deduct_credits_uid = State()
    deduct_credits_amt = State()
    support_msg = State()
    add_country = State()
    track_query = State()
    add_vip = State()
    set_timer = State()
    ai_chat = State()
    save_name = State()
    tg_login_phone = State()
    add_custom_proxy = State()
    add_manual_proxy = State()
    
    # User Auto Logger States
    user_auto_phone = State()
    user_auto_otp = State()
    user_auto_2fa = State()
    user_auto_bot_username = State()
    user_auto_target = State()
    user_auto_limit = State()
    user_select_country = State()
    
    # Naye Account Login States
    user_manual_login_platform = State()
    user_manual_login_phone = State()
    user_manual_login_otp = State()
    user_manual_create_name = State()
    user_manual_create_age = State()
    user_manual_create_loc = State()
