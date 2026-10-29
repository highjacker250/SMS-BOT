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

## Force Join
1. Add the bot as an admin to your own public Telegram channel.
2. In the bot, as the configured owner, run `/setforcejoin @YourChannel`.
3. Disable it with `/unsetforcejoin`.
4. New users must join and tap Verify. Owner/Admin can still access the panel.

## Render Free Web Service
This version exposes `/health` and `/` on `PORT` while Telegram polling runs. Select the `$0/month` instance if it is offered for your account. Free instances can spin down and do not provide persistent disks, so uptime and local JSON persistence are not guaranteed. Do not deploy until the environment variables are filled.

## Owner UI refresh
- Black-theme friendly compact inline control center
- Owner dashboard with live database reachability, device counts, users, and admins
- Separate owner/admin/user menus
- Force Join help button and commands
- This build supports authorized Firebase device metadata only. It does not retrieve or distribute real users' SMS/OTP contents; use synthetic codes or an owned test inbox for QA.

## Custom panel links and 24-hour saved test numbers
- Owner can save custom HTTPS panel links under Custom Panels.
- Saving a panel URL does not automatically integrate its private API; API documentation and authorization are required.
- Users can save their own/authorized QA test numbers for 24 hours. Expired saved entries are removed when the list is opened.
- This build does not fetch or redistribute third-party login OTPs/SMS. Real incoming-message integration must be connected to an authorized inbox endpoint with per-user access control.
