# services/smart_otp_scraper.py
import asyncio
import logging
import re
from pyrogram import Client
from pyrogram.errors import UserAlreadyParticipant, FloodWait
from pyrogram.types import Message
import config

log = logging.getLogger("OTPScraper")

async def handle_force_join(app: Client, bot_username: str, msg: Message):
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

# 🚨 Helper to wait for next message from bot
async def get_next_bot_message(app: Client, bot_username: str, timeout=15):
    try:
        # wait_for naye message ka wait karta hai
        msg = await app.wait_for(
            chat_id=bot_username,
            timeout=timeout
        )
        return msg
    except asyncio.TimeoutError:
        return None

async def get_available_countries(app: Client, bot_username: str, target_platform: str = "PayPal"):
    try:
        log.info(f"Trying to get countries for {target_platform}...")
        
        # Start Command
        await app.send_message(bot_username, "/start")
        await asyncio.sleep(2)
        msg = await get_next_bot_message(app, bot_username)
        
        if msg and msg.text and "join our channel" in msg.text.lower():
            await handle_force_join(app, bot_username, msg)
            await app.send_message(bot_username, "/start")
            await asyncio.sleep(2)

        # Send GET NUMBER
        await app.send_message(bot_username, "GET NUMBER")
        await asyncio.sleep(2)
        msg = await get_next_bot_message(app, bot_username)
        
        if not msg or not msg.reply_markup:
            log.error("No menu after GET NUMBER.")
            return []

        # Click Platform
        clicked = False
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                if target_platform.upper() in btn.text.upper():
                    await msg.click(btn.text)
                    clicked = True
                    break
            if clicked: break
            
        if not clicked: return []

        # 🚨 Ab wait karo country list ke liye (Listen Mode)
        log.info("Platform selected. Waiting for country list...")
        country_msg = await get_next_bot_message(app, bot_username)
        
        if not country_msg or not country_msg.reply_markup:
            return []

        countries = []
        for row in country_msg.reply_markup.inline_keyboard:
            for btn in row:
                if btn.text.upper() not in ["BACK", "CANCEL", "🔙", "❌"]:
                    price_match = re.search(r'\(([^)]+)\)', btn.text)
                    price = price_match.group(1) if price_match else "N/A"
                    clean_name = btn.text.split('(')[0].strip()
                    clean_name = ''.join(c for c in clean_name if ord(c) < 128).strip()
                    
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
    try:
        # Note: Country select karne ke liye hume us purane message ke buttons click karne hain
        # Par wait_for sirf naye messages sunta hai, isliye purane message ko history se nikalna padega
        # Ek trick: send "/country" command? Nahi. Hum just last message uthayenge history se.
        
        # Kyunki user ne country list abhi dekhi hai, wo latest message me hi hogi
        msg_to_click = None
        async for msg in app.get_chat_history(bot_username, limit=1):
            msg_to_click = msg
            break
            
        if not msg_to_click or not msg_to_click.reply_markup:
            log.error("Country menu not found in history.")
            return []

        clicked_country = False
        for row in msg_to_click.reply_markup.inline_keyboard:
            for btn in row:
                if btn.text == country_original_text:
                    await msg_to_click.click(btn.text)
                    clicked_country = True
                    break
            if clicked_country: break
        
        if not clicked_country: return []

        log.info(f"Country selected. Waiting for numbers (Listen Mode)...")
        
        numbers = []
        # Wait for number message (max 3 retries)
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

        log.warning("No numbers found after waiting.")
        return []
        
    except Exception as e:
        log.error(f"Scraper Error (select country): {e}")
        return []

async def wait_for_otp_from_bot(app: Client, bot_username: str, timeout=300):
    log.info("Waiting for OTP (Listen Mode)...")
    start_time = asyncio.get_event_loop().time()
    
    while (asyncio.get_event_loop().time() - start_time) < timeout:
        try:
            msg = await get_next_bot_message(app, bot_username, timeout=10)
            if msg and msg.text:
                # Regex for OTP (4-6 digits)
                match = re.search(r'\b(\d{4,6})\b', msg.text)
                if match:
                    log.info(f"OTP Found: {match.group(1)}")
                    return match.group(1)
        except Exception as e:
            log.error(f"OTP Wait Error: {e}")
            
    return None
