from aiogram.types import InlineKeyboardMarkup
from utils.ui import btn

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("get number", "user:get_num", "📱"), btn("my numbers", "user:saved", "⭐")],
        [btn("otp history", "user:history", "📜"), btn("help/support", "user:support", "🆘")]
    ])
