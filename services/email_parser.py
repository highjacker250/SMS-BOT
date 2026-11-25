import imaplib
import email
import re
import time
import asyncio
import logging
import config

log = logging.getLogger("EmailParser")

def _sync_fetch_otp():
    if not config.MASTER_EMAIL or not config.EMAIL_APP_PASSWORD:
        return None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(config.MASTER_EMAIL, config.EMAIL_APP_PASSWORD)
        mail.select("inbox")
        status, messages = mail.search(None, '(FROM "telegram")')
        if status != "OK" or not messages[0]:
            return None
        mail_ids = messages[0].split()
        for i in range(1, min(4, len(mail_ids) + 1)):
            mail_id = mail_ids[-i]
            status, data = mail.fetch(mail_id, '(RFC822)')
            for response_part in data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject = str(msg.get("subject", ""))
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = str(part.get_payload(decode=True).decode())
                                break
                    else:
                        body = str(msg.get_payload(decode=True).decode())
                    match = re.search(r'\b(\d{5})\b', subject + " " + body)
                    if match:
                        code = match.group(1)
                        log.info(f"Found TG Email OTP: {code}")
                        mail.logout()
                        return code
        mail.logout()
    except Exception as e:
        log.error(f"Email parse error: {e}")
    return None

async def get_telegram_email_otp(timeout=60):
    start_time = time.time()
    while time.time() - start_time < timeout:
        otp = await asyncio.get_event_loop().run_in_executor(None, _sync_fetch_otp)
        if otp:
            return otp
        await asyncio.sleep(5)
    return None
