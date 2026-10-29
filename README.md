# Firebase Device Status Telegram Bot (GitHub + Render)

## Features
- Owner-only Firebase URL manager (single URL and `.txt` bulk import)
- URL labels such as `EARNKAROBABA 7`
- Duplicate URL prevention and JSON configuration
- Owner/Admin live status screen: reachable/locked/offline/error, HTTP status, online-device count
- Owner/Admin online-device metadata screen (device name, ID, battery if available)
- Manual refresh buttons; each refresh checks the saved URLs live
- Basic user registration, role-aware menus, and user list
- Does **not** read, copy, or distribute SMS/OTP/message contents

## Render environment variables
- `BOT_TOKEN`: bot token stored as a secret environment variable
- `MAIN_OWNER_ID`: your numeric Telegram user ID
- Optional: `SCAN_INTERVAL_SECONDS` (default 60)

## Deploy
1. Upload `bot.py`, `requirements.txt`, and `README.md` to a GitHub repository.
2. In Render create a **Background Worker** from that repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Add the environment variables above.
6. For settings to survive redeploys, configure a persistent disk and set `DATA_FILE` to a path on that disk.

## Add a URL
Owner opens **Firebase Manager → Add URL** and sends:
`EARNKAROBABA 7 | https://YOUR-PROJECT-default-rtdb.firebaseio.com`

The hostname is a placeholder; replace it with a database you own or are authorized to administer.

## Schema note
The status checker reads `/clients.json?shallow=true` and individual `/clients/{device_id}.json` metadata. It expects online fields such as `isOnline`, `online`, `connected`, or `status`. If your authorized database uses another schema, the device count may show zero until its metadata schema is verified.

Firebase REST access requires HTTPS and Firebase Security Rules/authentication permission. A reachable URL does not automatically grant read access. Official docs: https://firebase.google.com/docs/reference/rest/database

## Security
- Never commit bot tokens or Firebase credentials into GitHub.
- If a token was hardcoded in an old source file, revoke it and create a new one.
- Do not make a database public merely to make the bot work.
