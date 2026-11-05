# services/smart_otp_scraper.py
import asyncio
import logging
from pyrogram import Client
import config

log = logging.getLogger("OTPScraper")

async def scrape_numbers_from_bot(app: Client, bot_username: str, target_platform: str = "PayPal"):
    """
    User ke account se OTP bot ko /start bhejta hai, buttons click karta hai, aur numbers extract karta hai.
    """
    numbers = []
    try:
        await app.send_message(bot_username, "/start")
        await asyncio.sleep(3)
        
        # Last message fetch karo
        async for msg in app.get_chat_history(bot_username, limit=1):
            if msg.reply_markup:
                # 1. Click "GET NUMBER"
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        if "GET NUMBER" in btn.text.upper():
                            await msg.click(btn.text)
                            break
                
                await asyncio.sleep(3)
                
                # 2. Platform select karo (e.g., PayPal)
                async for msg2 in app.get_chat_history(bot_username, limit=1):
                    if msg2.reply_markup:
                        for row in msg2.reply_markup.inline_keyboard:
                            for btn in row:
                                if target_platform.upper() in btn.text.upper():
                                    await msg2.click(btn.text)
                                    break
                        
                        await asyncio.sleep(3)
                        
                        # 3. Country select karo (Example: India)
                        async for msg3 in app.get_chat_history(bot_username, limit=1):
                            if msg3.reply_markup:
                                for row in msg3.reply_markup.inline_keyboard:
                                    for btn in row:
                                        if "INDIA" in btn.text.upper():
                                            await msg3.click(btn.text)
                                            break
                                
                                await asyncio.sleep(3)
                                
                                # 4. Ab numbers aayenge (usually list ke roop me)
                                async for msg4 in app.get_chat_history(bot_username, limit=1):
                                    # Text me se numbers extract karo (Regex)
                                    import re
                                    found = re.findall(r'\+?\d{10,12}', msg4.text)
                                    if found:
                                        numbers.extend(found)
    except Exception as e:
        log.error(f"Scraper Error: {e}")
        
    return numbers

async def wait_for_otp_from_bot(app: Client, bot_username: str, timeout=300):
    """
    OTP bot ke chat me wait karta hai jab tak OTP na aa jaye.
    """
    import time
    start = time.time()
    while time.time() - start < timeout:
        async for msg in app.get_chat_history(bot_username, limit=3):
            if msg.text:
                import re
                # Common OTP patterns
                match = re.search(r'\b(\d{6})\b', msg.text)
                if match:
                    return match.group(1)
        await asyncio.sleep(5)
    return None
