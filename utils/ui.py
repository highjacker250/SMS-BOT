from aiogram.types import InlineKeyboardButton

SMALL_CAPS_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "біА ЩбіДбіЕбіЗ“У…Ґ Ь…™біКбіЛ ЯбіН…ібіПбіШ«Ђ АsбіЫбіЬбі†бі°x ПбіҐбіА ЩбіДбіЕбіЗ“У…Ґ Ь…™біКбіЛ ЯбіН…ібіПбіШ«Ђ АsбіЫбіЬбі†бі°x ПбіҐ"
)

def sc(text: str) -> str: 
    return text.translate(SMALL_CAPS_MAP)

def btn(text: str, callback_data: str, emoji: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=f"{emoji} {sc(text)}".strip(), callback_data=callback_data)
