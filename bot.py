import os, logging, asyncio
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.environ["BOT_TOKEN"]
FIREBASE_URL = os.environ["FIREBASE_URL"].rstrip("/")
FIREBASE_AUTH = os.getenv("FIREBASE_AUTH", "")
DEMO_PATH = os.getenv("DEMO_PATH", "/demo_messages")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

async def fb_get(path):
    params = {"auth": FIREBASE_AUTH} if FIREBASE_AUTH else {}
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{FIREBASE_URL}{path}.json", params=params) as r:
            r.raise_for_status()
            return await r.json()

def render_demo(record):
    # Fail closed: only deliberately synthetic fixtures are accepted.
    if not isinstance(record, dict):
        return None
    if record.get("demo") is not True or record.get("synthetic") is not True:
        return None
    if record.get("type") != "test":
        return None
    body = str(record.get("body", "")).strip()[:1000]
    if not body:
        return None
    title = str(record.get("title", "Demo message"))[:80]
    return f"🧪 {title}\n\n{body}\n\n[SIMULATED TEST MESSAGE]"

@dp.message(Command("start"))
async def start(m):
    await m.answer("Firebase Safe Demo Bot\n/devices — limited device metadata\n/demo — synthetic test messages only\n/health — connection check")

@dp.message(Command("health"))
async def health(m):
    try:
        await fb_get("/.info/connected")
        await m.answer("Firebase endpoint reachable.")
    except Exception:
        logging.exception("Firebase health check failed")
        await m.answer("Firebase connection failed. Check URL, rules and auth.")

@dp.message(Command("devices"))
async def devices(m):
    try:
        data = await fb_get("/clients")
        if not isinstance(data, dict):
            await m.answer("No device records found.")
            return
        rows = []
        for device_id, d in list(data.items())[:50]:
            if not isinstance(d, dict):
                continue
            model = str(d.get("modelName") or "Unknown")[:45]
            battery = d.get("battery", "—")
            online = bool(d.get("isOnline") or d.get("online") or d.get("connected"))
            rows.append(f"• {device_id} | {model} | Battery: {battery} | {'Online' if online else 'Unknown/offline'}")
        await m.answer("\n".join(rows) if rows else "No device metadata available.")
    except Exception:
        logging.exception("Device fetch failed")
        await m.answer("Could not read device metadata. Check Firebase permissions.")

@dp.message(Command("demo"))
async def demo(m):
    try:
        data = await fb_get(DEMO_PATH)
        if not isinstance(data, dict):
            await m.answer("No synthetic demo messages found.")
            return
        messages = []
        for _, record in sorted(data.items(), key=lambda kv: str(kv[0]), reverse=True):
            rendered = render_demo(record)
            if rendered:
                messages.append(rendered)
            if len(messages) == 10:
                break
        if not messages:
            await m.answer("No explicitly synthetic demo records found. Live SMS records are not displayed.")
            return
        for item in messages:
            await m.answer(item)
    except Exception:
        logging.exception("Demo fetch failed")
        await m.answer("Could not fetch demo messages. Check Firebase permissions.")

@dp.message(F.text)
async def fallback(m):
    await m.answer("Use /devices, /demo, or /health.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
