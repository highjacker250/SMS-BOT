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

async def get_available_countries(app: Client, bot_username: str, target_platform: str = "PayPal"):
    try:
        await app.send_message(bot_username, "/start")
        await asyncio.sleep(3)
        
        latest_msg = None
        async for msg in app.get_chat_history(bot_username, limit=1):
            latest_msg = msg
            break
        
        if latest_msg and latest_msg.text and "join our channel" in latest_msg.text.lower():
            await handle_force_join(app, bot_username, latest_msg)
            await app.send_message(bot_username, "/start")
            await asyncio.sleep(3)

        # Send text "GET NUMBER"
        await app.send_message(bot_username, "GET NUMBER")
        await asyncio.sleep(4)

        # Find Platform Button
        clicked_platform = False
        async for msg in app.get_chat_history(bot_username, limit=5):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        if target_platform.upper() in btn.text.upper():
                            await msg.click(btn.text)
                            clicked_platform = True
                            break
                    if clicked_platform: break
        
        if not clicked_platform: return []

        await asyncio.sleep(4)

        # 🚨 Extract Country List with Price
        countries = []
        async for msg in app.get_chat_history(bot_username, limit=1):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        if btn.text.upper() not in ["BACK", "CANCEL", "🔙", "❌"]:
                            # Regex to extract price like (0.009$) or (0.0062$)
                            price_match = re.search(r'\(([^)]+)\)', btn.text)
                            price = price_match.group(1) if price_match else "N/A"
                            
                            # Clean name (remove price brackets and flags if any)
                            clean_name = btn.text.split('(')[0].strip()
                            # Remove emojis/flags (non-ascii)
                            clean_name = ''.join(i for i in clean_name if ord(i) < 128).strip()
                            
                            countries.append({
                                "name": clean_name, 
                                "price": price,
                                "original_text": btn.text
                            })
        
        return countries

    except Exception as e:
        log.error(f"Scraper Error (get countries): {e}")
        return []

async def select_country_and_get_numbers(app: Client, bot_username: str, country_original_text: str):
    numbers = []
    try:
        clicked_country = False
        async for msg in app.get_chat_history(bot_username, limit=3):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        if btn.text == country_original_text:
                            await msg.click(btn.text)
                            clicked_country = True
                            break
                    if clicked_country: break
        
        if not clicked_country:
            log.error(f"Could not find country button: {country_original_text}")
            return []

        await asyncio.sleep(4)

        # Extract Numbers
        async for msg in app.get_chat_history(bot_username, limit=1):
            if msg.text:
                found = re.findall(r'\+?\d{10,12}', msg.text)
                if found:
                    numbers.extend(found)
                    log.info(f"Found {len(found)} numbers.")
                else:
                    log.warning(f"Bot replied: {msg.text[:100]}")
        return numbers
    except Exception as e:
        log.error(f"Scraper Error (select country): {e}")
        return []

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
