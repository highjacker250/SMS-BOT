import asyncio
import logging
import aiohttp
from contextlib import asynccontextmanager

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import config

from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import auto_hunter_loop
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

async def self_ping():
    url = f"http://localhost:{config.PORT}/"
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    pass
        except: pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Bot Polling and Scanners...")
    asyncio.create_task(dp.start_polling(bot))
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(auto_hunter_loop(bot)) # 🚨 GHATAK HUNTER
    asyncio.create_task(proxy_scanner_loop())
    asyncio.create_task(self_ping())
    yield
    log.info("Shutting down...")
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    with open("web_panel/templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/telegram", response_class=HTMLResponse)
async def serve_telegram():
    with open("web_panel/templates/telegram.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

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
            "device_id": acc.get("device_id", "Unknown"),
            "ai_task": f"Monitoring {phone}..."
        })
    return JSONResponse(content={"status": "success", "accounts": result})

@app.get("/api/health")
async def get_health():
    status = db.get_bot_status()
    return JSONResponse(content={"task": status.get("task"), "detail": status.get("detail")})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
