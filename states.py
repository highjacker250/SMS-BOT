from aiogram.fsm.state import State, StatesGroup

class S(StatesGroup):
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
    tg_login_phone = State() # 🚨 Naya
