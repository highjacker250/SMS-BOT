import asyncio

# COLAB FIX: fresh event loop before any other import
asyncio.set_event_loop(asyncio.new_event_loop())

import logging
import aiohttp
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
import uvicorn
import config

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery

from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router
from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import auto_hunter_loop, reset_watchdog_loop
from services.proxy_manager import proxy_scanner_loop
import database as db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Main")

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

dp.include_routers(owner_router, admin_router, user_router)


@dp.callback_query(lambda c: c.data and c.data.startswith("copy_otp_"))
async def copy_otp_callback(cq: CallbackQuery):
    otp = cq.data.split("_")[2]
    await cq.answer(f"📋 OTP: {otp}\n\n(Manually copy karein)", show_alert=True)


async def self_ping():
    url = f"http://127.0.0.1:{config.PORT}/api/health"
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    pass
        except Exception as e:
            log.debug(f"self_ping failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Bot Polling and Scanners...")
    asyncio.create_task(dp.start_polling(bot))
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(auto_hunter_loop(bot))
    asyncio.create_task(reset_watchdog_loop(bot))
    asyncio.create_task(proxy_scanner_loop())
    asyncio.create_task(self_ping())
    yield
    log.info("Shutting down...")
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


# =========================
# HTML ROUTES
# =========================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    try:
        with open("web_panel/templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading Dashboard: {e}</h1>", status_code=500)


@app.get("/telegram", response_class=HTMLResponse)
async def serve_telegram():
    try:
        with open("web_panel/templates/telegram.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading Telegram UI: {e}</h1>", status_code=500)


@app.get("/mini_panel/{token}", response_class=HTMLResponse)
async def serve_mini_panel(token: str):
    d = db.load_data()
    if token not in d.get("mini_tokens", {}):
        raise HTTPException(status_code=403, detail="Invalid or Expired Token")
    try:
        with open("web_panel/templates/mini_panel.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read().replace("{{ token }}", token))
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading Mini Panel: {e}</h1>", status_code=500)


# =========================
# API: ACCOUNTS
# =========================

@app.get("/api/get_accounts")
async def get_accounts():
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    result = []
    for phone, acc in accounts.items():
        result.append({
            "phone": phone,
            "status": acc.get("status", "unknown"),
            "session": (acc.get("session", "")[:15] + "...") if acc.get("session") else "No Session",
            "device_id": acc.get("device_id", "Unknown"),
            "ai_task": f"Monitoring {phone}...",
            "reset_time": acc.get("reset_time", 0),
        })
    return JSONResponse(content={"status": "success", "accounts": result})


# =========================
# API: HUNTING
# =========================

@app.get("/api/hunting_status")
async def hunting_status():
    d = db.load_data()
    return JSONResponse(content={"enabled": d.get("hunting_enabled", True)})


@app.post("/api/toggle_hunting")
async def toggle_hunting(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    d = db.load_data()
    action = body.get("action") if isinstance(body, dict) else None

    if action == "start":
        d["hunting_enabled"] = True
    elif action == "stop":
        d["hunting_enabled"] = False
    else:
        d["hunting_enabled"] = not d.get("hunting_enabled", True)

    db.save_data(d)
    return JSONResponse(content={"status": "success", "enabled": d["hunting_enabled"]})


# =========================
# API: HEALTH
# =========================

@app.get("/api/health")
async def get_health():
    status = db.get_bot_status()
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    active = sum(1 for a in accounts.values() if a.get("status") == "active")
    total = len(accounts)
    completion_rate = round((active / total) * 100, 1) if total else 0.0

    return JSONResponse(content={
        "task": status.get("task", "Idle"),
        "detail": status.get("detail", "Waiting..."),
        "last_update": status.get("last_update", 0),
        "accounts_count": total,
        "active_accounts": active,
        "working_proxies": len(d.get("working_proxies", [])),
        "completion_rate": completion_rate,
        "hunting_enabled": d.get("hunting_enabled", True),
    })


# =========================
# API: ACTIVITY FEED
# =========================

@app.get("/api/activity_feed")
async def activity_feed():
    feed = db.get_activity_feed()
    return JSONResponse(content={"status": "success", "feed": feed})


@app.post("/api/clear_feed")
async def clear_feed():
    db.clear_activity_feed()
    return JSONResponse(content={"status": "success"})


# =========================
# API: LIVE SCREENSHOT
# =========================

@app.get("/api/live_screenshot")
async def get_live_screenshot():
    try:
        if os.path.exists("live_browser.png"):
            with open("live_browser.png", "rb") as f:
                img_data = f.read()
            return Response(content=img_data, media_type="image/png", headers={"Cache-Control": "no-store"})
        return JSONResponse(content={"error": "No screenshot found"}, status_code=404)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# =========================
# API: PROFILE
# =========================

@app.get("/api/get_profile")
async def get_profile():
    d = db.load_data()
    profile = d.get("owner_profile", {})
    return JSONResponse(content={"status": "success", "profile": profile})


@app.post("/api/save_profile")
async def save_profile(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    username = (body.get("username") or "").strip()
    email = (body.get("email") or "").strip()
    rank = (body.get("rank") or "").strip()

    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be >= 3 chars")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    d = db.load_data()
    d["owner_profile"] = {
        "username": username,
        "email": email,
        "rank": rank or "S-RANK HUNTER",
    }
    db.save_data(d)
    return JSONResponse(content={"status": "success", "profile": d["owner_profile"]})


# =========================
# API: SETTINGS
# =========================

@app.get("/api/get_settings")
async def get_settings():
    d = db.load_data()
    settings = d.get("owner_settings", {})
    return JSONResponse(content={"status": "success", "settings": settings})


@app.post("/api/save_settings")
async def save_settings(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    poll = body.get("poll_interval", 3)
    try:
        poll = max(1, min(30, int(poll)))
    except Exception:
        poll = 3

    d = db.load_data()
    d["owner_settings"] = {
        "poll_interval": poll,
        "sound_enabled": bool(body.get("sound_enabled", True)),
        "discord_webhook": (body.get("discord_webhook") or "").strip(),
        "api_base": (body.get("api_base") or "/api").strip(),
    }
    db.save_data(d)
    return JSONResponse(content={"status": "success", "settings": d["owner_settings"]})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
