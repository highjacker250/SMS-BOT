# main.py
import asyncio
import logging
import aiohttp
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import config
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import auto_hunter_loop, reset_watchdog_loop
from services.proxy_manager import proxy_scanner_loop
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router
from handlers.user.auto_logger import user_auto_router # 🚨 Import
import database as db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Main")

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_routers(owner_router, admin_router, user_router, user_auto_router) # 🚨 Include

# ... (lifespan, self_ping same rahenge)

app = FastAPI(lifespan=lifespan)

# ... (existing routes for / and /telegram)

# 🚨 NAYA ROUTE: Mini Panel
@app.get("/mini_panel/{token}", response_class=HTMLResponse)
async def serve_mini_panel(token: str):
    d = db.load_data()
    if token not in d.get("mini_tokens", {}):
        raise HTTPException(status_code=403, detail="Invalid or Expired Token")
    with open("web_panel/templates/mini_panel.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read().replace("{{ token }}", token))

@app.get("/api/user_accounts/{token}")
async def get_user_accounts(token: str):
    d = db.load_data()
    if token not in d.get("mini_tokens", {}):
        return JSONResponse(content={"error": "Invalid"}, status_code=403)
    uid = d["mini_tokens"][token]
    
    accounts = []
    for phone, acc in d.get("target_accounts", {}).items():
        if acc.get("user_id") == uid:
            accounts.append({
                "platform": acc.get("platform", "Unknown"),
                "username": phone,
                "status": acc.get("status", "Unknown")
            })
    return JSONResponse(content={"accounts": accounts})

# ... (baaki API same rahenge)
