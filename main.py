import asyncio
import logging
import aiohttp
from contextlib import asynccontextmanager

# 🚨 PYTHON 3.14 FIX for Pyrogram
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import config

# Tere bot ke modules
from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import reset_watchdog_loop
from services.proxy_manager import proxy_scanner_loop
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router
import database as db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Main")

# Bot Initialize
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_routers(owner_router, admin_router, user_router)

# Render Free Tier ke liye Self-Ping
async def self_ping():
    url = f"http://localhost:{config.PORT}/"
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    pass
        except Exception:
            pass

# Lifespan (Start & Stop)
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Bot Polling and Scanners...")
    asyncio.create_task(dp.start_polling(bot))
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(reset_watchdog_loop())
    asyncio.create_task(proxy_scanner_loop())
    asyncio.create_task(self_ping())
    yield
    log.info("Shutting down...")
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

# 🚨 FIXED ROUTE 1: Main Dashboard (Direct file read, no Jinja2 conflict)
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    try:
        with open("web_panel/templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        log.error(f"Dashboard HTML error: {e}")
        return HTMLResponse(content="<h1>Error loading Dashboard. Check logs.</h1>", status_code=500)

# 🚨 FIXED ROUTE 2: Telegram UI (Direct file read, no Jinja2 conflict)
@app.get("/telegram", response_class=HTMLResponse)
async def serve_telegram():
    try:
        with open("web_panel/templates/telegram.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        log.error(f"Telegram HTML error: {e}")
        return HTMLResponse(content="<h1>Error loading Telegram UI. Check logs.</h1>", status_code=500)

# 🚨 LIVE API: Real Accounts fetch karne ke liye
@app.get("/api/get_accounts")
async def get_accounts():
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    
    result = []
    for phone, acc in accounts.items():
        result.append({
            "phone": phone,
            "status": acc.get("status", "unknown"),
            "session": acc.get("session", "")[:15] + "..." if acc.get("session") else "No Session",
            "ai_task": f"Monitoring for {phone}...",
            "is_online": acc.get("status") == "active"
        })
        
    return JSONResponse(content={"status": "success", "accounts": result})

# 🚨 LIVE API: Health status
@app.get("/api/health")
async def get_health():
    d = db.load_data()
    status = db.get_bot_status()
    return JSONResponse(content={
        "task": status.get("task", "Idle"),
        "detail": status.get("detail", "Waiting..."),
        "accounts_count": len(d.get("telegram_accounts", {})),
        "working_proxies": len(d.get("working_proxies", []))
    })

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
