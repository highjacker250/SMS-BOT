from aiogram.fsm.state import State, StatesGroup

class S(StatesGroup):
    add_bulk_urls = State()
    add_bot = State()
    add_admin = State()
    ban_user = State()
    broadcast = State()
    add_credits_uid = State()
    add_credits_amt = State()
    support_msg = State()
