# services/smart_otp_scraper.py
import asyncio
import logging
import re
from pyrogram import Client
from pyrogram.errors import UserAlreadyParticipant, FloodWait
import config

log = logging.getLogger("OTPScraper")

async def handle_force_join(app: Client, bot_username: str, msg):
    text = msg.text.lower() if msg.text else ""
    if "join our channel" in text or "join our channel(s)" in text:
        log.info("Force-Join detected! AI is joining channels...")
        
        if msg.reply_markup:
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if btn.url and ("t.me" in btn.url or "telegram.me" in btn.url):
                        try:
                            channel = btn.url.split("/")[-1].replace("@", "")
                            await app.join_chat(channel)
                            log.info(f"AI successfully joined: {channel}")
                            await asyncio.sleep(2) 
                        except UserAlreadyParticipant:
                            pass
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception as e:
                            log.error(f"Failed to join {channel}: {e}")
        
        # Click "I Joined - Check Now" (if it exists)
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
    numbers = []
    try:
        # STEP 1: Initial /start
        await app.send_message(bot_username, "/start")
        await asyncio.sleep(4)
        
        latest_msg = None
        async for msg in app.get_chat_history(bot_username, limit=1):
            latest_msg = msg
            break
        
        # STEP 2: Force-Join Check
        if latest_msg and latest_msg.text:
            if "join our channel" in latest_msg.text.lower():
                await handle_force_join(app, bot_username, latest_msg)
                # After joining, we MUST send /start again to get the real menu
                log.info("Sending /start after Force-Join...")
                await app.send_message(bot_username, "/start")
                await asyncio.sleep(4)

        # 🚨 STEP 3: SEND TEXT "GET NUMBER" (TERA IDEA)
        log.info("Directly sending text 'GET NUMBER' to bot...")
        await app.send_message(bot_username, "GET NUMBER")
        await asyncio.sleep(4)

        # STEP 4: Find the response and click Platform
        clicked_platform = False
        async for msg2 in app.get_chat_history(bot_username, limit=5):
            if msg2.reply_markup:
                for row in msg2.reply_markup.inline_keyboard:
                    for btn in row:
                        if target_platform.upper() in btn.text.upper():
                            await msg2.click(btn.text)
                            clicked_platform = True
                            log.info(f"Selected platform: {target_platform}")
                            break
                    if clicked_platform: break
        
        if not clicked_platform:
            # Fallback: Click first available platform if exact match not found
            async for msg2 in app.get_chat_history(bot_username, limit=1):
                if msg2.reply_markup and msg2.reply_markup.inline_keyboard:
                    await msg2.click(msg2.reply_markup.inline_keyboard[0][0].text)
                    log.warning(f"Platform {target_platform} not found. Clicked first available.")
                    break
        
        await asyncio.sleep(3)

        # STEP 5: Select Country
        clicked_country = False
        async for msg3 in app.get_chat_history(bot_username, limit=5):
            if msg3.reply_markup:
                for row in msg3.reply_markup.inline_keyboard:
                    for btn in row:
                        if "INDIA" in btn.text.upper():
                            await msg3.click(btn.text)
                            clicked_country = True
                            log.info("Selected country: INDIA")
                            break
                    if clicked_country: break
        
        if not clicked_country:
            # Fallback: Click first available country
            async for msg3 in app.get_chat_history(bot_username, limit=1):
                if msg3.reply_markup and msg3.reply_markup.inline_keyboard:
                    await msg3.click(msg3.reply_markup.inline_keyboard[0][0].text)
                    log.warning("Country INDIA not found. Clicked first available.")
                    break

        await asyncio.sleep(3)

        # STEP 6: Extract Numbers
        async for msg4 in app.get_chat_history(bot_username, limit=1):
            if msg4.text:
                found = re.findall(r'\+?\d{10,12}', msg4.text)
                if found:
                    numbers.extend(found)
                    log.info(f"Found {len(found)} numbers.")
                else:
                    log.warning("No numbers found in text. Bot might be out of stock.")
                    log.warning(f"Bot replied: {msg4.text[:100]}")
                    
    except Exception as e:
        log.error(f"Scraper Error: {e}")
        
    return numbers

async def wait_for_otp_from_bot(app: Client, bot_username: str, timeout=300):
    import time
    start = time.time()
    while time.time() - start < timeout:
        try:
            async for msg in app.get_chat_history(bot_username, limit=3):
                if msg.text:
                    match = re.search(r'\b(\d{4,6})\b', msg.text)
                    if match:
                        return match.group(1)
        except Exception as e:
            log.error(f"OTP wait error: {e}")
            
        await asyncio.sleep(5)
    return None
