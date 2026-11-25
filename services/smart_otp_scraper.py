# services/smart_otp_scraper.py
import asyncio
import logging
import re
from pyrogram import Client
from pyrogram.errors import UserAlreadyParticipant, FloodWait
import config

log = logging.getLogger("OTPScraper")

async def handle_force_join(app: Client, bot_username: str):
    try:
        async for msg in app.get_chat_history(bot_username, limit=3):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for b in row:
                        if "join" in b.text.lower() and b.url:
                            try:
                                await app.join_chat(b.url)
                                log.info(f"Joined {b.url}")
                            except UserAlreadyParticipant:
                                pass
                            except FloodWait as e:
                                await asyncio.sleep(e.value)
                            except Exception as ex:
                                log.warning(f"Force join failed: {ex}")
    except Exception as e:
        log.warning(f"handle_force_join err: {e}")

async def get_next_bot_message(app: Client, bot_username: str, timeout=15):
    try:
        msg = await app.wait_for(chat_id=bot_username, timeout=timeout)
        return msg
    except asyncio.TimeoutError:
        return None

async def send_start(app: Client, bot_username: str):
    try:
        await app.send_message(bot_username, "/start")
        await asyncio.sleep(2)
    except Exception as e:
        log.warning(f"/start err: {e}")

async def get_available_countries(app: Client, bot_username: str, target_platform: str = "PayPal"):
    """Bot ka main menu parse karke countries + price nikalta hai."""
    await send_start(app, bot_username)
    await handle_force_join(app, bot_username)
    await asyncio.sleep(1)
    # Refresh menu if stuck
    await app.send_message(bot_username, "/start")
    await asyncio.sleep(2)

    countries = []
    try:
        async for msg in app.get_chat_history(bot_username, limit=5):
            if not msg.reply_markup:
                continue
            for row in msg.reply_markup.inline_keyboard:
                for b in row:
                    txt = b.text or ""
                    # format expected: "🇮🇳 India - $0.25" or "India $0.25"
                    m = re.search(r'([A-Za-z][A-Za-z\s]+?)\s*[-:]?\s*\$?([\d.]+)', txt)
                    if m and b.callback_data:
                        name = m.group(1).strip()
                        price = m.group(2)
                        if len(name) < 30:
                            countries.append({
                                "name": name,
                                "price": f"${price}",
                                "original_text": txt,
                                "callback_data": b.callback_data,
                            })
            if countries:
                break
    except Exception as e:
        log.error(f"get_available_countries err: {e}")

    # dedupe by name
    seen = set()
    unique = []
    for c in countries:
        if c["name"].lower() not in seen:
            seen.add(c["name"].lower())
            unique.append(c)
    return unique

async def select_country_and_get_numbers(app: Client, bot_username: str, country_original_text: str):
    try:
        clicked_country = False
        async for msg in app.get_chat_history(bot_username, limit=5):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for b in row:
                        if b.text == country_original_text:
                            await msg.click(b.text)
                            clicked_country = True
                            break
                    if clicked_country: break
            if clicked_country: break
        if not clicked_country:
            return []

        log.info(f"Country selected. Waiting for numbers...")
        numbers = []
        for _ in range(3):
            num_msg = await get_next_bot_message(app, bot_username, timeout=10)
            if not num_msg: continue
            if num_msg.text:
                found = re.findall(r'\+?\d{10,12}', num_msg.text)
                if found: numbers.extend(found)
            if num_msg.reply_markup:
                for row in num_msg.reply_markup.inline_keyboard:
                    for b in row:
                        found_btn = re.findall(r'\+?\d{10,12}', b.text or "")
                        if found_btn: numbers.extend(found_btn)
                        if hasattr(b, 'copy_text') and b.copy_text:
                            found_copy = re.findall(r'\+?\d{10,12}', b.copy_text.text or "")
                            if found_copy: numbers.extend(found_copy)
            if numbers:
                return list(set(numbers))

        # Refresh fallback
        log.warning("No numbers found. Trying REFRESH...")
        refreshed = False
        async for msg in app.get_chat_history(bot_username, limit=2):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for b in row:
                        if "REFRESH" in (b.text or "").upper():
                            await msg.click(b.text)
                            refreshed = True
                            break
                    if refreshed: break
            if refreshed: break
        if refreshed:
            await asyncio.sleep(4)
            num_msg = await get_next_bot_message(app, bot_username, timeout=15)
            if num_msg:
                if num_msg.text:
                    numbers.extend(re.findall(r'\+?\d{10,12}', num_msg.text))
                if num_msg.reply_markup:
                    for row in num_msg.reply_markup.inline_keyboard:
                        for b in row:
                            numbers.extend(re.findall(r'\+?\d{10,12}', b.text or ""))
                            if hasattr(b, 'copy_text') and b.copy_text:
                                numbers.extend(re.findall(r'\+?\d{10,12}', b.copy_text.text or ""))
            return list(set(numbers))
        return []
    except Exception as e:
        log.error(f"Scraper Error: {e}")
        return []

async def wait_for_otp_from_bot(app: Client, bot_username: str, timeout=300):
    """Bot se OTP ka intezaar. 3-3 pattern aur 4-8 digits dono handle karta hai."""
    start = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start) < timeout:
        try:
            msg = await get_next_bot_message(app, bot_username, timeout=15)
            if not msg: continue
            text = msg.text or ""
            # Telegram code format: "12345" or "code: 123-456"
            m = re.search(r'\b(\d{5})\b', text)
            if m: return m.group(1)
            m2 = re.search(r'code[:\s]+(\d{3})[-\s]?(\d{3})', text, re.I)
            if m2: return m2.group(1) + m2.group(2)
            m3 = re.search(r'\b(\d{6})\b', text)
            if m3: return m3.group(1)
        except Exception as e:
            log.debug(f"wait_for_otp err: {e}")
        await asyncio.sleep(1)
    return None
