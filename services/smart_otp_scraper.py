# services/smart_otp_scraper.py
import asyncio
import logging
import re
from pyrogram import Client
from pyrogram.errors import UserAlreadyParticipant, FloodWait
from pyrogram.types import Message
import config

log = logging.getLogger("OTPScraper")

# ... (handle_force_join same rahega)

async def get_next_bot_message(app: Client, bot_username: str, timeout=15):
    try:
        msg = await app.wait_for(chat_id=bot_username, timeout=timeout)
        return msg
    except asyncio.TimeoutError:
        return None

async def get_available_countries(app: Client, bot_username: str, target_platform: str = "PayPal"):
    # ... (pura purana code same rahega)
    pass

async def select_country_and_get_numbers(app: Client, bot_username: str, country_original_text: str):
    try:
        # 1. Country click karo
        clicked_country = False
        async for msg in app.get_chat_history(bot_username, limit=5):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        if btn.text == country_original_text:
                            await msg.click(btn.text)
                            clicked_country = True
                            break
                    if clicked_country: break
        
        if not clicked_country: return []

        log.info(f"Country selected. Waiting for numbers...")
        
        numbers = []
        # 🚨 2. Wait & Listen for Numbers
        for _ in range(3):
            num_msg = await get_next_bot_message(app, bot_username, timeout=10)
            if not num_msg: continue
            
            # Check text
            if num_msg.text:
                found = re.findall(r'\+?\d{10,12}', num_msg.text)
                if found: numbers.extend(found)
            
            # Check buttons/copy_text
            if num_msg.reply_markup:
                for row in num_msg.reply_markup.inline_keyboard:
                    for btn in row:
                        found_btn = re.findall(r'\+?\d{10,12}', btn.text)
                        if found_btn: numbers.extend(found_btn)
                        if hasattr(btn, 'copy_text') and btn.copy_text:
                            found_copy = re.findall(r'\+?\d{10,12}', btn.copy_text.text)
                            if found_copy: numbers.extend(found_copy)
            
            if numbers:
                return list(set(numbers))
        
        # 🚨 3. No numbers found? Click REFRESH!
        log.warning("No numbers found. Trying to click REFRESH...")
        refreshed = False
        async for msg in app.get_chat_history(bot_username, limit=2):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        if "REFRESH" in btn.text.upper():
                            await msg.click(btn.text)
                            refreshed = True
                            break
                    if refreshed: break
            if refreshed: break
        
        if refreshed:
            log.info("Clicked REFRESH. Waiting for new numbers...")
            await asyncio.sleep(4)
            num_msg = await get_next_bot_message(app, bot_username, timeout=15)
            if num_msg:
                if num_msg.text:
                    found = re.findall(r'\+?\d{10,12}', num_msg.text)
                    if found: numbers.extend(found)
                if num_msg.reply_markup:
                    for row in num_msg.reply_markup.inline_keyboard:
                        for btn in row:
                            found_btn = re.findall(r'\+?\d{10,12}', btn.text)
                            if found_btn: numbers.extend(found_btn)
                            if hasattr(btn, 'copy_text') and btn.copy_text:
                                found_copy = re.findall(r'\+?\d{10,12}', btn.copy_text.text)
                                if found_copy: numbers.extend(found_copy)
            return list(set(numbers))

        return []
    except Exception as e:
        log.error(f"Scraper Error: {e}")
        return []

async def wait_for_otp_from_bot(app: Client, bot_username: str, timeout=300):
    # ... (wait_for logic same rahega)
    pass
