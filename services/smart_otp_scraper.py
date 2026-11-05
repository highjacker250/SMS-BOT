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
        
        # Click "I Joined - Check Now"
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

async def find_and_click_button(app: Client, bot_username: str, button_text_match: str):
    """
    Bot ke last message me button dhundhta hai aur click karta hai.
    """
    async for msg in app.get_chat_history(bot_username, limit=1):
        if msg.reply_markup:
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if button_text_match.upper() in btn.text.upper():
                        await msg.click(btn.text)
                        log.info(f"Clicked button: {btn.text}")
                        return True
    return False

async def scrape_numbers_from_bot(app: Client, bot_username: str, target_platform: str = "PayPal"):
    numbers = []
    try:
        # 1. /start bhejo
        await app.send_message(bot_username, "/start")
        await asyncio.sleep(4)
        
        latest_msg = None
        async for msg in app.get_chat_history(bot_username, limit=1):
            latest_msg = msg
            break
        
        if not latest_msg: return []

        # 2. Force-Join Check
        is_force_join = False
        if latest_msg.text and "join our channel" in latest_msg.text.lower():
            is_force_join = await handle_force_join(app, bot_username, latest_msg)
        
        # 🚨 3. Agar Force-Join hua, toh /start dobara bhejo
        if is_force_join:
            log.info("Force-Join complete. Sending /start again...")
            await app.send_message(bot_username, "/start")
            await asyncio.sleep(4)
            async for msg in app.get_chat_history(bot_username, limit=1):
                latest_msg = msg
                break
        
        # 🚨 4. Ab latest message me button dhundho
        clicked_get_number = False
        if latest_msg and latest_msg.reply_markup:
            for row in latest_msg.reply_markup.inline_keyboard:
                for btn in row:
                    if "GET NUMBER" in btn.text.upper():
                        await latest_msg.click(btn.text)
                        clicked_get_number = True
                        log.info("Clicked GET NUMBER button.")
                        break
                if clicked_get_number: break
                
        # 5. Agar is message me nahi mila, toh purane message me dhundho
        if not clicked_get_number:
            clicked_get_number = await find_and_click_button(app, bot_username, "GET NUMBER")

        # 6. Agar fir bhi nahi mila, toh direct text "GET NUMBER" bhejo
        if not clicked_get_number:
            log.warning("GET NUMBER button not found. Sending text 'GET NUMBER'...")
            await app.send_message(bot_username, "GET NUMBER")
            await asyncio.sleep(4)
            # Check if new buttons appeared
            clicked_get_number = await find_and_click_button(app, bot_username, "GET NUMBER")

        if not clicked_get_number:
            log.error("Bot menu is broken. Could not find GET NUMBER button.")
            return []

        await asyncio.sleep(3)
        
        # 7. Platform select karo
        clicked_platform = await find_and_click_button(app, bot_username, target_platform.upper())
        if not clicked_platform:
            # Agar platform nahi mila, toh first button click karo
            async for msg2 in app.get_chat_history(bot_username, limit=1):
                if msg2.reply_markup and msg2.reply_markup.inline_keyboard:
                    await msg2.click(msg2.reply_markup.inline_keyboard[0][0].text)
                    log.warning(f"Platform {target_platform} not found. Clicked first available.")
                    break
        await asyncio.sleep(3)
        
        # 8. Country select karo (India)
        clicked_country = await find_and_click_button(app, bot_username, "INDIA")
        if not clicked_country:
            async for msg3 in app.get_chat_history(bot_username, limit=1):
                if msg3.reply_markup and msg3.reply_markup.inline_keyboard:
                    await msg3.click(msg3.reply_markup.inline_keyboard[0][0].text)
                    log.warning("Country INDIA not found. Clicked first available.")
                    break
        await asyncio.sleep(3)
        
        # 9. Numbers extract karo
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
