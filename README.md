# Firebase Safe Demo Telegram Bot

This bot reads limited device metadata and explicitly synthetic demo fixtures only.
It does not read live SMS inboxes, OTPs, phone-number lists, or outgoing SMS command queues.

## Synthetic fixture
Create `/demo_messages` in Firebase with records like:

```json
{
  "sample-001": {
    "demo": true,
    "synthetic": true,
    "type": "test",
    "title": "Sample event",
    "body": "This is a simulated message for testing the Telegram interface."
  }
}
```

Never put real SMS, OTPs, financial alerts, phone numbers, or identity data in this path.

## Install and run
Python 3.10+:

```bash
pip install -r requirements.txt
export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
export FIREBASE_URL="https://YOUR-PROJECT-default-rtdb.firebaseio.com"
export FIREBASE_AUTH="YOUR_FIREBASE_TOKEN"
python bot.py
```

Render:
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`
- Add `BOT_TOKEN`, `FIREBASE_URL`, and `FIREBASE_AUTH` as environment variables.

Commands: `/start`, `/health`, `/devices`, `/demo`.

Use read-only Firebase rules and a dedicated least-privilege token. Never commit credentials.
