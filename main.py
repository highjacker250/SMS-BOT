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
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
import uvicorn
import config

from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import reset_watchdog_loop
from services.proxy_manager import proxy_scanner_loop
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router
import database as db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Main")

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_routers(owner_router, admin_router, user_router)

# Background Tasks
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

# 🚨 FastAPI App setup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start Bot Polling and Background Tasks
    log.info("Starting Bot Polling and Scanners...")
    asyncio.create_task(dp.start_polling(bot))
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(reset_watchdog_loop())
    asyncio.create_task(proxy_scanner_loop())
    asyncio.create_task(self_ping())
    yield
    # Shutdown
    log.info("Shutting down...")
    await bot.session.close()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="web_panel/templates")

@app.get("/", response_class=HTMLResponse)
async def health_check():
    return "Bot is Running! Go to /panel for dashboard."

@app.get("/panel", response_class=HTMLResponse)
async def owner_panel(request: Request):
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    bot_status = db.get_bot_status()
    proxies = d.get("working_proxies", [])
    
    formatted_accounts = []
    for phone, acc in accounts.items():
        formatted_accounts.append({
            "phone": phone,
            "status": acc.get("status", "unknown"),
            "session": acc.get("session", "")[:10] + "..." if acc.get("session") else "No Session",
            "reset_time": acc.get("reset_time", 0)
        })
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "accounts": formatted_accounts,
        "bot_status": bot_status,
        "proxies": proxies
    })

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
