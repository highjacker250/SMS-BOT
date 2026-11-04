from aiogram.types import InlineKeyboardButton

# 🚨 FIXED: Length now matches (52 English letters to 52 Unicode small caps)
SMALL_CAPS_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"
)

def sc(text: str) -> str: 
    return text.translate(SMALL_CAPS_MAP)

def btn(text: str, callback_data: str, emoji: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=f"{emoji} {sc(text)}".strip(), callback_data=callback_data)
