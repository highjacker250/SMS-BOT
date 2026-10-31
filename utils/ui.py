from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

SMALL_CAPS_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
)

def sc(text: str) -> str:
    return text.translate(SMALL_CAPS_MAP)

def btn(text: str, callback_data: str, emoji: str = "") -> InlineKeyboardButton:
    label = f"{emoji} {sc(text)}".strip()
    return InlineKeyboardButton(text=label, callback_data=callback_data)

def btn_url(text: str, url: str, emoji: str = "") -> InlineKeyboardButton:
    label = f"{emoji} {sc(text)}".strip()
    return InlineKeyboardButton(text=label, url=url)
