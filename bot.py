import asyncio
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clean-firebase-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MAIN_OWNER = int(os.getenv("MAIN_OWNER_ID", "0"))
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))
SCAN_INTERVAL = max(30, int(os.getenv("SCAN_INTERVAL_SECONDS", "60")))

def defaults():
    return {
        "owners": [MAIN_OWNER] if MAIN_OWNER else [],
        "admins": [],
        "banned": [],
        "users": {},
        "firebases": [],
        "plans": [],
        "redeem_codes": {},
        "settings": {"scan_interval": SCAN_INTERVAL},
        "activity_log": []
    }

def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for k, v in defaults().items():
                data.setdefault(k, v)
            return data
        except (OSError, json.JSONDecodeError) as exc:
            log.exception("Could not load data: %s", exc)
    data = defaults()
    save_data(data)
    return data

def save_data(data):
    temp = DATA_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(DATA_FILE)

def is_owner(uid, data=None):
    data = data or load_data()
    return uid in data.get("owners", [])

def is_admin(uid, data=None):
    data = data or load_data()
    return is_owner(uid, data) or uid in data.get("admins", [])

def register_user(user):
    data = load_data()
    uid = str(user.id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "id": user.id, "name": user.full_name or "User",
            "username": user.username, "joined_at": int(time.time()),
            "role": "owner" if is_owner(user.id, data) else "user",
            "banned": False
        }
    else:
        data["users"][uid]["name"] = user.full_name or "User"
        data["users"][uid]["username"] = user.username
    save_data(data)
    return data

def kb_home(uid, data):
    b = InlineKeyboardBuilder()
    b.button(text="🔥 Firebase Manager", callback_data="fb:menu")
    if is_admin(uid, data):
        b.button(text="📡 Firebase Live Status", callback_data="fb:status")
        b.button(text="📱 Online Devices", callback_data="devices")
    b.button(text="💰 Plans", callback_data="plans")
    if is_admin(uid, data):
        b.button(text="👥 Users", callback_data="users")
        b.button(text="⚙️ Settings", callback_data="settings")
    b.adjust(1)
    return b.as_markup()

def kb_back(dest="home"):
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Back", callback_data=dest)
    return b.as_markup()

def firebase_menu(data):
    b = InlineKeyboardBuilder()
    b.button(text="➕ Add URL", callback_data="fb:add")
    b.button(text="📄 Bulk add TXT", callback_data="fb:bulk_help")
    b.button(text="📋 List URLs", callback_data="fb:list:0")
    b.button(text="🔄 Scan devices", callback_data="devices")
    b.button(text="⬅️ Back", callback_data="home")
    b.adjust(1)
    return b.as_markup()

def valid_firebase_url(url):
    try:
        p = urlparse(url)
        return (p.scheme == "https" and p.hostname and
                (p.hostname.endswith("firebaseio.com") or p.hostname.endswith("firebasedatabase.app")) and
                not p.username and not p.password)
    except Exception:
        return False


async def scan_firebase_status(session, fb):
    """Read only authorized /clients device metadata; never read SMS/message nodes."""
    base = fb["url"].rstrip("/")
    result = {
        "id": fb["id"], "label": fb.get("label", "Firebase"),
        "url": base, "status": "ERROR", "http": None, "device_count": 0,
        "online_count": 0, "devices": [], "checked_at": int(time.time()),
        "detail": ""
    }
    try:
        async with session.get(
            f"{base}/clients.json?shallow=true",
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            result["http"] = resp.status
            if resp.status in (401, 403):
                result["status"] = "LOCKED"
                result["detail"] = "Authentication/rules permission required"
                return result
            if resp.status == 404:
                result["status"] = "NOT FOUND"
                result["detail"] = "Database/path not found"
                return result
            if resp.status != 200:
                result["status"] = "ERROR"
                result["detail"] = f"HTTP {resp.status}"
                return result
            ids = await resp.json(content_type=None)

        if not isinstance(ids, dict):
            result["status"] = "CONNECTED"
            result["detail"] = "Reachable, but /clients is not an object"
            return result

        result["status"] = "ONLINE"
        result["device_count"] = len(ids)
        for device_id in list(ids.keys())[:100]:
            try:
                async with session.get(
                    f"{base}/clients/{device_id}.json",
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status != 200:
                        continue
                    device = await resp.json(content_type=None)
                if not isinstance(device, dict):
                    continue
                raw_status = device.get(
                    "isOnline",
                    device.get("online", device.get("connected", device.get("status", False)))
                )
                online = raw_status is True or str(raw_status).lower() in (
                    "online", "true", "connected", "1"
                )
                if online:
                    result["online_count"] += 1
                    result["devices"].append({
                        "label": result["label"],
                        "device_id": str(device_id)[:80],
                        "name": str(device.get("deviceName", device.get("name", "Unknown")))[:60],
                        "battery": str(device.get("battery", device.get("batteryLevel", "?")))[:16]
                    })
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
        result["detail"] = "Metadata scan complete"
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        result["status"] = "OFFLINE"
        result["detail"] = type(exc).__name__
    return result

async def scan_all_firebase(session, data):
    results = []
    for fb in data.get("firebases", []):
        results.append(await scan_firebase_status(session, fb))
    return results

dp = Dispatcher()
pending = {}

@dp.message(CommandStart())
async def start(message: Message):
    data = register_user(message.from_user)
    uid = message.from_user.id
    if str(uid) in data.get("banned", []) or data["users"].get(str(uid), {}).get("banned"):
        await message.answer("⛔ Access disabled hai. Owner se contact karo.")
        return
    await message.answer(
        "✨ <b>Firebase Device Manager</b>\n\n"
        "Clean starter panel ready hai. Firebase URLs aur user settings local persistent JSON mein save hote hain.\n"
        "SMS inbox/OTP collection is starter mein intentionally enabled nahi hai.",
        reply_markup=kb_home(uid, data), parse_mode="HTML"
    )

@dp.message(Command("id"))
async def show_id(message: Message):
    await message.answer(f"Telegram User ID: <code>{message.from_user.id}</code>", parse_mode="HTML")

@dp.callback_query(F.data == "home")
async def home(cq: CallbackQuery):
    data = register_user(cq.from_user)
    await cq.message.edit_text("🏠 <b>Main Menu</b>", reply_markup=kb_home(cq.from_user.id, data), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "fb:menu")
async def fb_menu(cq: CallbackQuery):
    data = load_data()
    if not is_owner(cq.from_user.id, data):
        await cq.answer("Owner only.", show_alert=True); return
    await cq.message.edit_text(f"🔥 <b>Firebase Manager</b>\nSaved URLs: <b>{len(data['firebases'])}</b>\n\nAdd URLs anytime; duplicates are skipped.",
                               reply_markup=firebase_menu(data), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "fb:add")
async def fb_add(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        await cq.answer("Owner only.", show_alert=True); return
    pending[cq.from_user.id] = "add_url"
    await cq.message.answer("Format bhejo:\n<code>EARNKAROBABA 7 | https://YOUR-PROJECT-default-rtdb.firebaseio.com</code>\n\nSirf apna/authorized Firebase URL add karo.", parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "fb:bulk_help")
async def fb_bulk_help(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        await cq.answer("Owner only.", show_alert=True); return
    await cq.message.answer("Bulk add ke liye `.txt` file bhejo. Har line ka format:\n<code>Label | https://YOUR-PROJECT-default-rtdb.firebaseio.com</code>\nAuthorized databases only.", parse_mode="HTML")
    pending[cq.from_user.id] = "bulk_file"
    await cq.answer()

@dp.message(F.document)
async def bulk_file(message: Message):
    if pending.get(message.from_user.id) != "bulk_file" or not is_owner(message.from_user.id):
        return
    if not message.document.file_name.lower().endswith(".txt"):
        await message.answer("Sirf .txt file bhejo."); return
    file = await message.bot.get_file(message.document.file_id)
    stream = await message.bot.download_file(file.file_path)
    raw = stream.read().decode("utf-8", errors="replace")
    data = load_data()
    existing = {x["url"] for x in data["firebases"]}
    added = skipped = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if "|" in line:
            label, url = [p.strip() for p in line.split("|", 1)]
        else:
            url = line
            label = url.split("://")[-1].split(".")[0][:30]
        url = url.rstrip("/")
        if not valid_firebase_url(url) or url in existing:
            skipped += 1; continue
        data["firebases"].append({"id": str(int(time.time()*1000))+str(added), "label": label[:60] or "Firebase", "url": url, "added_at": int(time.time())})
        existing.add(url); added += 1
    save_data(data); pending.pop(message.from_user.id, None)
    await message.answer(f"✅ Added: {added}\n⏭️ Skipped/invalid: {skipped}\n📊 Total: {len(data['firebases'])}")

@dp.message(F.text)
async def text_input(message: Message):
    mode = pending.get(message.from_user.id)
    if mode != "add_url":
        return
    if not is_owner(message.from_user.id):
        pending.pop(message.from_user.id, None); return
    raw = message.text.strip()
    if "|" in raw:
        label, url = [p.strip() for p in raw.split("|", 1)]
    else:
        url = raw
        label = url.split("://")[-1].split(".")[0][:30]
    url = url.rstrip("/")
    if not valid_firebase_url(url):
        await message.answer("❌ URL format valid nahi. HTTPS Realtime Database URL use karo."); return
    data = load_data()
    if any(x["url"] == url for x in data["firebases"]):
        pending.pop(message.from_user.id, None)
        await message.answer("⚠️ Ye URL pehle se saved hai."); return
    data["firebases"].append({"id": str(int(time.time()*1000)), "label": label[:60] or "Firebase", "url": url, "added_at": int(time.time())})
    save_data(data); pending.pop(message.from_user.id, None)
    await message.answer(f"✅ Firebase saved: <b>{label}</b>\nTotal URLs: {len(data['firebases'])}", parse_mode="HTML")

@dp.callback_query(F.data.startswith("fb:list:"))
async def fb_list(cq: CallbackQuery):
    data = load_data()
    if not is_owner(cq.from_user.id, data):
        await cq.answer("Owner only.", show_alert=True); return
    try: page = max(0, int(cq.data.rsplit(":", 1)[1]))
    except ValueError: page = 0
    items = data["firebases"]
    per_page = 8
    pages = max(1, (len(items)+per_page-1)//per_page)
    page = min(page, pages-1)
    lines = [f"📋 <b>Firebase URLs</b> — Page {page+1}/{pages}\n"]
    b = InlineKeyboardBuilder()
    for item in items[page*per_page:(page+1)*per_page]:
        lines.append(f"• <b>{item['label']}</b>\n  <code>{item['url']}</code>")
        b.button(text=f"🗑 Remove {item['label'][:18]}", callback_data=f"fb:del:{item['id']}:{page}")
    if page > 0: b.button(text="◀️ Previous", callback_data=f"fb:list:{page-1}")
    if page < pages-1: b.button(text="Next ▶️", callback_data=f"fb:list:{page+1}")
    b.button(text="⬅️ Back", callback_data="fb:menu")
    b.adjust(1)
    await cq.message.edit_text("\n".join(lines) if items else "Abhi koi Firebase URL saved nahi hai.", reply_markup=b.as_markup(), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data.startswith("fb:del:"))
async def fb_delete(cq: CallbackQuery):
    data = load_data()
    if not is_owner(cq.from_user.id, data):
        await cq.answer("Owner only.", show_alert=True); return
    parts = cq.data.split(":")
    fb_id, page = parts[2], int(parts[3])
    data["firebases"] = [x for x in data["firebases"] if x["id"] != fb_id]
    save_data(data)
    await cq.answer("URL removed.")
    cq.data = f"fb:list:{page}"
    await fb_list(cq)


@dp.callback_query(F.data == "fb:status")
async def firebase_status(cq: CallbackQuery):
    data = load_data()
    if not is_admin(cq.from_user.id, data):
        await cq.answer("Admin/Owner only.", show_alert=True)
        return
    if not data["firebases"]:
        await cq.message.edit_text(
            "📡 <b>Firebase Live Status</b>\n\nAbhi URL saved nahi hai. Owner se URL add karwao.",
            reply_markup=kb_back("home"), parse_mode="HTML"
        )
        await cq.answer()
        return
    await cq.answer("Checking Firebase URLs…")
    async with aiohttp.ClientSession() as session:
        statuses = await scan_all_firebase(session, data)
    lines = ["📡 <b>Firebase Live Status</b>", "<i>Refresh time: just now</i>", ""]
    b = InlineKeyboardBuilder()
    for item in statuses[:30]:
        icon = "🟢" if item["status"] == "ONLINE" else ("🔒" if item["status"] == "LOCKED" else "🔴")
        lines.append(
            f"{icon} <b>{item['label']}</b> — <b>{item['status']}</b>\n"
            f"Devices: {item['online_count']}/{item['device_count']} online\n"
            f"HTTP: {item['http'] if item['http'] is not None else 'No response'} · "
            f"{item['detail'][:70]}"
        )
        lines.append("")
    lines.append("Checks database reachability + authorized device metadata only.")
    b.button(text="🔄 Refresh Status", callback_data="fb:status")
    b.button(text="📱 Online Devices", callback_data="devices")
    b.button(text="⬅️ Back", callback_data="home")
    b.adjust(1)
    await cq.message.edit_text("\n".join(lines), reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "devices")
async def devices(cq: CallbackQuery):
    data = load_data()
    if not is_admin(cq.from_user.id, data):
        await cq.answer("Admin/Owner only.", show_alert=True)
        return
    if not data["firebases"]:
        await cq.message.edit_text(
            "Pehle Owner panel mein authorized Firebase URL add karo.",
            reply_markup=kb_back("home")
        )
        await cq.answer()
        return
    await cq.answer("Scanning device metadata…")
    async with aiohttp.ClientSession() as session:
        statuses = await scan_all_firebase(session, data)
    found = [d for s in statuses for d in s["devices"]]
    if not found:
        lines = ["📱 <b>Online Devices</b>", ""]
        for s in statuses[:20]:
            icon = "🟢" if s["status"] == "ONLINE" else "🔴"
            lines.append(f"{icon} <b>{s['label']}</b>: {s['status']} — {s['online_count']} online")
        lines.append("\nKoi online device detect nahi hua, ya database ka device schema different hai.")
    else:
        lines = [f"📱 <b>Online Devices</b> — {len(found)} found", ""]
        for d in found[:50]:
            lines.append(
                f"🟢 <b>{d['name']}</b>\nSource: {d['label']}\n"
                f"Device ID: <code>{d['device_id']}</code>\nBattery: {d['battery']}"
            )
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Refresh Devices", callback_data="devices")
    b.button(text="📡 Firebase Status", callback_data="fb:status")
    b.button(text="⬅️ Back", callback_data="home")
    b.adjust(1)
    await cq.message.edit_text("\n\n".join(lines), reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "plans")
async def plans(cq: CallbackQuery):
    data = load_data()
    if not data["plans"]:
        text = "💰 <b>Plans</b>\n\nAbhi koi plan configured nahi hai. Owner config mein plans add kar sakta hai."
    else:
        text = "💰 <b>Plans</b>\n\n" + "\n\n".join(f"• <b>{p.get('name','Plan')}</b> — ₹{p.get('price','?')} / {p.get('credits','?')} credits" for p in data["plans"])
    await cq.message.edit_text(text, reply_markup=kb_back("home"), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "users")
async def users(cq: CallbackQuery):
    data = load_data()
    if not is_admin(cq.from_user.id, data):
        await cq.answer("Admin only.", show_alert=True); return
    entries = list(data["users"].values())[-30:]
    lines = [f"👥 <b>Registered Users</b> — {len(data['users'])} total\n"]
    for u in reversed(entries):
        lines.append(f"• {u.get('name','User')} — <code>{u['id']}</code> — @{u.get('username') or 'none'}")
    await cq.message.edit_text("\n".join(lines), reply_markup=kb_back("home"), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "settings")
async def settings(cq: CallbackQuery):
    data = load_data()
    if not is_admin(cq.from_user.id, data):
        await cq.answer("Admin only.", show_alert=True); return
    await cq.message.edit_text(
        f"⚙️ <b>Settings</b>\nScan interval: {data['settings'].get('scan_interval', SCAN_INTERVAL)} seconds\nPersistent file: <code>{DATA_FILE}</code>",
        reply_markup=kb_back("home"), parse_mode="HTML")
    await cq.answer()

async def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN env variable missing. Create a bot via BotFather and set BOT_TOKEN.")
    if MAIN_OWNER <= 0:
        raise SystemExit("MAIN_OWNER_ID env variable missing. Use your Telegram numeric user ID.")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
