from aiogram.types import InlineKeyboardMarkup
from utils.ui import btn

def owner_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("admin panel", "admin:home", "👑")],
        [btn("add credits", "owner:add_credits", "💰"), btn("broadcast", "owner:broadcast", "📢")],
        [btn("add bot", "owner:add_bot", "🤖"), btn("stats", "owner:stats", "📊")]
    ])
