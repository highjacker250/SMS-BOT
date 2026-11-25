"""
OTP Scanner - Monitors Firebase for incoming SMS and delivers OTPs to users.
Refactored with proper error handling, retries, and clean architecture.
"""
import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    from aiogram.types import CopyTextButton
    HAS_COPY_TEXT = True
except ImportError:
    HAS_COPY_TEXT = False

import constants as C
from services.database import get_db, DatabaseService
from services.firebase import get_firebase, FirebaseService
from utils.helper import get_ist_time_str

log = logging.getLogger("Scanner")


@dataclass
class LeaseInfo:
    """User lease information."""
    fb_url: str
    dev_id: str
    users: list[int]
    last_msg_id: int
    phone: str
    service: str


async def _push_otp_to_account(phone_number: str, service: str, otp: str, rent_id: str, raw_text: str) -> None:
    """Store OTP in telegram_accounts for web panel display."""
    if not phone_number or phone_number == "Unknown":
        return

    clean = ''.join(filter(str.isdigit, str(phone_number)))[-10:]
    if len(clean) != 10:
        return

    async with get_db().transaction() as data:
        accounts = data.setdefault("telegram_accounts", {})
        matched_key = None
        for key in accounts.keys():
            key_clean = ''.join(filter(str.isdigit, str(key)))[-10:]
            if key_clean == clean:
                matched_key = key
                break

        if not matched_key:
            return

        acc = accounts[matched_key]
        otps = acc.setdefault("otps", [])
        otps.insert(0, {
            "service": service,
            "otp": otp,
            "rent_id": rent_id,
            "time": int(time.time()),
            "text": (raw_text or "")[:120],
        })
        acc["otps"] = otps[:C.Limits.MAX_OTPS_PER_ACCOUNT]


async def send_otp_to_user(
    bot,
    uid: int,
    service: str,
    otp: str,
    msg_text: str,
    rent_id: str,
    phone_number: str
) -> None:
    """Send OTP notification to user via Telegram."""
    num_display = f"+91{phone_number}" if phone_number and phone_number != "Unknown" else "Unknown"

    otp_msg = (
        f"🔔 <b>OTP Received!</b>\n\n"
        f"📱 <b>Service:</b> {service}\n"
        f"🔑 <b>OTP:</b> <code>{otp}</code>\n\n"
        f"🆔 <b>Rent ID:</b> <code>{rent_id}</code>\n"
        f"📞 <b>Number:</b> <code>{num_display}</code>\n"
        f"💬 <i>{msg_text[:60]}...</i>"
    )

    if HAS_COPY_TEXT:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"Copy {otp}", copy_text=CopyTextButton(text=otp))
        ]])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"Copy {otp}", callback_data=f"copy_otp_{otp}")
        ]])

    # Update user's OTP history
    async with get_db().transaction() as data:
        user = data["users"].get(str(uid))
        if user:
            hist = user.setdefault("otp_history", [])
            hist.insert(0, {
                "service": service,
                "otp": otp,
                "time": int(time.time()),
                "number": phone_number
            })
            user["otp_history"] = hist[:C.Limits.MAX_OTP_HISTORY_PER_USER]

    # Store in account for web panel
    try:
        await _push_otp_to_account(phone_number, service, otp, rent_id, msg_text)
    except Exception as e:
        log.warning(f"OTP push to account failed: {e}")

    # Send to user
    try:
        await bot.send_message(uid, otp_msg, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        log.debug(f"Failed to send OTP to user {uid}: {e}")


async def check_device(
    bot,
    fb_url: str,
    auth: str,
    dev_id: str,
    users: list[int],
    last_msg_id: int,
    phone_number: str,
    service_filter: str
) -> int:
    """
    Check a single device for new messages.
    Returns the highest message ID seen.
    """
    firebase = get_firebase()
    highest_id = last_msg_id

    try:
        msgs = await firebase.fetch_messages(fb_url, dev_id, auth, limit=5)
    except Exception as e:
        log.warning(f"Failed to fetch messages for {dev_id}: {e}")
        return last_msg_id

    if not msgs:
        return last_msg_id

    # Sort messages by ID
    sorted_msgs = sorted(
        msgs.values(),
        key=lambda x: int(x.get("id", 0)) if isinstance(x, dict) else 0
    )

    for msg in sorted_msgs:
        if not isinstance(msg, dict) or msg.get("type") != "incoming":
            continue

        current_id = int(msg.get("id", 0))
        text = msg.get("message", "")
        sender = msg.get("sender", "")

        if current_id <= last_msg_id:
            continue

        # Extract OTP
        otp = firebase.extract_otp(text)
        if not otp:
            if current_id > highest_id:
                highest_id = current_id
            continue

        # Detect service
        detected_service = firebase.extract_service_name(text, sender)
        text_lower = text.lower()

        # Apply service filter
        if service_filter == C.ServiceFilter.WHATSAPP.value:
            if "whatsapp" not in text_lower and not C.PATTERNS["WHATSAPP_CODE"].search(text_lower):
                if current_id > highest_id:
                    highest_id = current_id
                continue
            detected_service = "WhatsApp"
        elif service_filter == C.ServiceFilter.TELEGRAM.value:
            if "telegram" not in text_lower:
                if current_id > highest_id:
                    highest_id = current_id
                continue
            detected_service = "Telegram"

        # Log activity
        get_db().push_activity("OTP Found", f"{detected_service} OTP for {phone_number}")

        # Send to all users on this lease
        for uid in users:
            await send_otp_to_user(bot, uid, detected_service, otp, text, dev_id, phone_number)

        if current_id > highest_id:
            highest_id = current_id

    return highest_id


async def start_scanner(bot) -> None:
    """
    Main OTP scanner - polls active leases for new messages.
    Runs continuously with 1 second interval.
    """
    log.info("Fast Scanner Started...")
    db = get_db()
    firebase = get_firebase()

    while True:
        try:
            data = await db.load()
            leases = data.get("user_leases", {})
            fbs = {f["url"]: f.get("auth") for f in data.get("firebases", [])}

            # Group leases by device
            device_to_users: dict[tuple, LeaseInfo] = {}
            current_time = time.time()

            for uid_str, lease in leases.items():
                if current_time >= lease.get("expire_at", 0):
                    continue  # Expired lease

                fb_url = lease.get("fb_url")
                dev_id = lease.get("dev_id")
                service = lease.get("service_filter", C.ServiceFilter.ANY.value)

                if not fb_url or not dev_id:
                    continue

                key = (fb_url, dev_id)
                if key not in device_to_users:
                    device_to_users[key] = LeaseInfo(
                        fb_url=fb_url,
                        dev_id=dev_id,
                        users=[],
                        last_msg_id=lease.get("last_msg_id", 0),
                        phone=lease.get("top_number", "Unknown"),
                        service=service
                    )
                device_to_users[key].users.append(int(uid_str))

            if device_to_users:
                # Check all devices concurrently
                tasks = []
                keys = list(device_to_users.keys())

                for key in keys:
                    lease_info = device_to_users[key]
                    auth = fbs.get(key[0], "")
                    tasks.append(check_device(
                        bot, key[0], auth, key[1],
                        lease_info.users, lease_info.last_msg_id,
                        lease_info.phone, lease_info.service
                    ))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Update last_msg_id for leases
                updated = False
                for idx, key in enumerate(keys):
                    result = results[idx]
                    if isinstance(result, Exception):
                        log.error(f"Scanner error for {key}: {result}")
                        continue
                    if result > device_to_users[key].last_msg_id:
                        for uid in device_to_users[key].users:
                            uid_str = str(uid)
                            if uid_str in leases:
                                leases[uid_str]["last_msg_id"] = result
                                updated = True

                if updated:
                    await db.save(data)

        except Exception as e:
            log.error(f"Scanner error: {e}")

        await asyncio.sleep(C.Intervals.SCANNER_POLL)


async def whatsapp_scanner(bot) -> None:
    """
    Background scanner for WhatsApp-ready numbers.
    Runs every 60 seconds, scans all Firebase bases.
    """
    log.info("WhatsApp Background Scanner Started...")
    db = get_db()
    firebase = get_firebase()

    while True:
        try:
            data = await db.load()
            fbs = data.get("firebases", [])
            ready_lines = {}
            now = time.time()

            # Process in chunks to avoid overwhelming Firebase
            for i in range(0, len(fbs), C.Limits.MAX_CONCURRENT_FIREBASE_CHECKS):
                chunk = fbs[i:i + C.Limits.MAX_CONCURRENT_FIREBASE_CHECKS]

                async def check_fb(fb):
                    try:
                        clients = await firebase.fetch_clients(fb['url'], fb.get("auth"))
                        if not clients or not isinstance(clients, dict):
                            return

                        results = []
                        for dev_id, c in clients.items():
                            if not isinstance(c, dict):
                                continue
                            is_online = (
                                c.get("status") is True or
                                (c.get("ping", {}).get("ts", 0) > (now - 3600) * 1000)
                            )
                            if is_online:
                                results.append((dev_id, c))

                        return results
                    except Exception as e:
                        log.debug(f"WA scanner FB error: {e}")
                        return None

                chunk_results = await asyncio.gather(*[check_fb(fb) for fb in chunk])

                for fb, fb_results in zip(chunk, chunk_results):
                    if not fb_results:
                        continue

                    for dev_id, c in fb_results:
                        try:
                            msgs_dict = await firebase.fetch_messages(fb['url'], dev_id, fb.get("auth"), limit=20)
                            if not msgs_dict:
                                continue

                            msgs = [
                                v for v in msgs_dict.values()
                                if isinstance(v, dict) and v.get("type") == "incoming"
                            ]

                            has_ws = False
                            latest_id = 0

                            for m in msgs:
                                txt = (m.get("message") or "").lower()
                                if "whatsapp" in txt or C.PATTERNS["WHATSAPP_CODE"].search(txt):
                                    has_ws = True
                                    mid = int(m.get("id", 0))
                                    if mid > latest_id:
                                        latest_id = mid

                            if not has_ws:
                                continue

                            best_nums = firebase.extract_best_numbers(c, msgs)
                            if not best_nums:
                                continue

                            num = best_nums[0][0]
                            real_battery = str(c.get("battery", "0")).replace("%", "")
                            real_health = firebase.calculate_health(msgs)

                            ready_lines[dev_id] = {
                                "fb_url": fb['url'],
                                "auth": fb.get("auth", ""),
                                "number": num,
                                "chance": 99,
                                "health": real_health,
                                "battery": real_battery,
                                "time": int(now),
                                "sort_id": latest_id
                            }
                        except Exception as e:
                            log.debug(f"WA scanner device error {dev_id}: {e}")

            # Save results
            async with db.transaction() as data:
                data["whatsapp_ready_lines"] = ready_lines

        except Exception as e:
            log.error(f"WA Scanner error: {e}")

        await asyncio.sleep(C.Intervals.WHATSAPP_SCANNER)


async def backup_scanner(bot) -> None:
    """
    Backup scanner - checks for device backups and manages OTP timers.
    Runs every 10 seconds.
    """
    log.info("Backup Scanner Started...")
    db = get_db()
    firebase = get_firebase()

    while True:
        try:
            data = await db.load()
            fbs = data.get("firebases", [])

            # Device backup collection
            if fbs:
                all_devs = []

                for fb in fbs:
                    try:
                        clients = await firebase.fetch_shallow(f"{fb['url']}/clients.json", fb.get("auth"))
                        if clients and isinstance(clients, dict):
                            for dev_id in clients.keys():
                                all_devs.append((fb, dev_id))
                    except Exception as e:
                        log.debug(f"Backup scanner list error: {e}")

                now = int(time.time())
                missing = []

                for fb, dev_id in all_devs:
                    bkp = data.get("device_backups", {}).get(dev_id, {})
                    if not bkp.get("numbers") or (now - bkp.get("time", 0) > C.Intervals.DEVICE_BACKUP_TTL):
                        missing.append((fb, dev_id))

                random.shuffle(missing)

                for fb, dev_id in missing[:10]:
                    try:
                        msgs = await firebase.fetch_messages(fb['url'], dev_id, fb.get("auth"), limit=20)
                        dev_data = await firebase.fetch(f"{fb['url']}/clients/{dev_id}.json", fb.get("auth"))

                        if msgs and isinstance(msgs, dict) and dev_data and isinstance(dev_data, dict):
                            msgs_list = [
                                v for k, v in msgs.items()
                                if isinstance(v, dict) and v.get("type") == "incoming"
                            ]
                            best_nums = firebase.extract_best_numbers(dev_data, msgs_list)
                            if best_nums:
                                nums = [n for n, c in best_nums]
                                if "device_backups" not in data:
                                    data["device_backups"] = {}
                                data["device_backups"][dev_id] = {"numbers": nums, "time": int(time.time())}
                    except Exception as e:
                        log.debug(f"Backup scanner fetch error {dev_id}: {e}")

                # Clean old backups
                if "device_backups" in data:
                    for dev_id in list(data["device_backups"].keys()):
                        if now - data["device_backups"][dev_id].get("time", 0) > C.Intervals.DEVICE_BACKUP_TTL:
                            del data["device_backups"][dev_id]

            # Timer alerts
            timers = data.get("upcoming_timers", {})
            now = int(time.time())
            changed = False

            for key, t in list(timers.items()):
                # 5-minute alert
                if t.get("alert_5m") is False and (t["target_time"] - now) <= C.Intervals.TIMER_ALERT_5M:
                    try:
                        await bot.send_message(
                            t["user_id"],
                            f"⏰ <b>OTP Alert</b>\nAapka OTP aane wala hai (5 min baaki)!\n📞 <code>{t['number']}</code>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    t["alert_5m"] = True
                    changed = True

                # 2-minute alert
                if t.get("alert_2m") is False and (t["target_time"] - now) <= C.Intervals.TIMER_ALERT_2M:
                    try:
                        await bot.send_message(
                            t["user_id"],
                            f"⏰ <b>OTP Alert</b>\nSirf 2 minute bache hain!\n📞 <code>{t['number']}</code>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    t["alert_2m"] = True
                    changed = True

                # Time's up alert
                if now >= t["target_time"] and t.get("alert_now") is False:
                    try:
                        await bot.send_message(
                            t["user_id"],
                            f"🚀 <b>OTP Window Open</b>\nAb try karein!\n📞 <code>{t['number']}</code>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    t["alert_now"] = True
                    changed = True

            if changed:
                await db.save(data)

        except Exception as e:
            log.error(f"Backup Scanner error: {e}")

        await asyncio.sleep(C.Intervals.BACKUP_SCANNER)