# services/smart_otp_scraper.py
import asyncio
import logging
import re
from pyrogram import Client
from pyrogram.errors import UserAlreadyParticipant, InviteHashExpired, ChannelPrivate, FloodWait
import config

log = logging.getLogger("OTPScraper")

async def handle_force_join(app: Client, bot_username: str, msg):
    """
    AI khud channels join karega, aur fir 'I Joined' pe click karega.
    """
    text = msg.text.lower() if msg.text else ""
    if "join our channel" in text or "join our channel(s)" in text:
        log.info("Force-Join detected! AI is joining channels...")
        
        # 1. AI khud saare channels join karega
        if msg.reply_markup:
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if btn.url and ("t.me" in btn.url or "telegram.me" in btn.url):
                        try:
                            # Link se username nikaalo (e.g., https://t.me/smartxteam -> smartxteam)
                            channel = btn.url.split("/")[-1].replace("@", "")
                            
                            # Channel join karo
                            await app.join_chat(channel)
                            log.info(f"AI successfully joined: {channel}")
                            await asyncio.sleep(2) # Delay taaki Telegram block na kare
                            
                        except UserAlreadyParticipant:
                            log.info(f"AI is already in channel: {channel}")
                        except FloodWait as e:
                            log.warning(f"FloodWait! Sleeping for {e.value}s")
                            await asyncio.sleep(e.value)
                        except Exception as e:
                            log.error(f"Failed to join {channel}: {e}")
        
        # 2. Ab "I Joined - Check Now" button pe click karega
        if msg.reply_markup:
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if "joined" in btn.text.lower() or "check now" in btn.text.lower():
                        try:
                            await msg.click(btn.text)
                            log.info("AI clicked 'I Joined - Check Now'.")
                            await asyncio.sleep(3)
                            return True
                        except Exception as e:
                            log.error(f"Failed to click 'I Joined': {e}")
    return False

async def scrape_numbers_from_bot(app: Client, bot_username: str, target_platform: str = "PayPal"):
    """
    User ke account se OTP bot ko /start bhejta hai, buttons click karta hai, aur numbers extract karta hai.
    """
    numbers = []
    try:
        # 1. Bot ko /start bhejo
        await app.send_message(bot_username, "/start")
        await asyncio.sleep(3)
        
        # 2. Latest message fetch karo
        latest_msg = None
        async for msg in app.get_chat_history(bot_username, limit=1):
            latest_msg = msg
            break
        
        if not latest_msg:
            log.error("No message received from bot.")
            return []

        # 3. Check if Force-Join is required
        if latest_msg.reply_markup:
            is_force_join = await handle_force_join(app, bot_username, latest_msg)
            if is_force_join:
                # Naya message fetch karo join ke baad
                await asyncio.sleep(2)
                async for msg_new in app.get_chat_history(bot_username, limit=1):
                    latest_msg = msg_new
                    break
        
        # 4. Click "GET NUMBER" (ya jo bhi pehla valid button ho)
        clicked_get_number = False
        if latest_msg.reply_markup:
            for row in latest_msg.reply_markup.inline_keyboard:
                for btn in row:
                    if "GET NUMBER" in btn.text.upper() or "GET" in btn.text.upper():
                        await latest_msg.click(btn.text)
                        clicked_get_number = True
                        log.info("Clicked GET NUMBER.")
                        break
                if clicked_get_number: break
        
        if not clicked_get_number:
            log.warning("GET NUMBER button not found after start.")
            return []

        await asyncio.sleep(3)
        
        # 5. Platform select karo (e.g., PayPal)
        async for msg2 in app.get_chat_history(bot_username, limit=1):
            if msg2.reply_markup:
                clicked_platform = False
                for row in msg2.reply_markup.inline_keyboard:
                    for btn in row:
                        if target_platform.upper() in btn.text.upper():
                            await msg2.click(btn.text)
                            clicked_platform = True
                            log.info(f"Selected platform: {target_platform}")
                            break
                    if clicked_platform: break
                
                # Fallback: Agar specific platform nahi mila, toh pehla button click karo
                if not clicked_platform and msg2.reply_markup.inline_keyboard:
                    await msg2.click(msg2.reply_markup.inline_keyboard[0][0].text)
                    log.warning(f"Platform {target_platform} not found. Clicked first available.")
                
                await asyncio.sleep(3)
                
                # 6. Country select karo (Example: India)
                async for msg3 in app.get_chat_history(bot_username, limit=1):
                    if msg3.reply_markup:
                        clicked_country = False
                        for row in msg3.reply_markup.inline_keyboard:
                            for btn in row:
                                if "INDIA" in btn.text.upper():
                                    await msg3.click(btn.text)
                                    clicked_country = True
                                    log.info("Selected country: INDIA")
                                    break
                            if clicked_country: break
                        
                        if not clicked_country and msg3.reply_markup.inline_keyboard:
                            await msg3.click(msg3.reply_markup.inline_keyboard[0][0].text)
                            log.warning("Country INDIA not found. Clicked first available.")
                        
                        await asyncio.sleep(3)
                        
                        # 7. Ab numbers aayenge (list ke roop me)
                        async for msg4 in app.get_chat_history(bot_username, limit=1):
                            if msg4.text:
                                found = re.findall(r'\+?\d{10,12}', msg4.text)
                                if found:
                                    numbers.extend(found)
                                    log.info(f"Found {len(found)} numbers.")
                                else:
                                    log.warning("No numbers found in text. Bot might be out of stock.")
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
        try:
            async for msg in app.get_chat_history(bot_username, limit=3):
                if msg.text:
                    # Common OTP patterns (4-6 digits)
                    match = re.search(r'\b(\d{4,6})\b', msg.text)
                    if match:
                        return match.group(1)
        except Exception as e:
            log.error(f"OTP wait error: {e}")
            
        await asyncio.sleep(5)
    return None
