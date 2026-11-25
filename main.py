"""
Main entry point for SMS-BOT.
FastAPI + aiogram Telegram bot with background scanners and web panel.
"""
import asyncio
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager
from typing import Optional

import aiohttp
from fastapi import FastAPI, HTTPException, Request, Depends, Security
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery

import config
import constants as C
from services.database import get_db, DatabaseService, database_transaction
from services.firebase import get_firebase, FirebaseService
from services.browser import get_browser_manager, close_browser, LoginAutomation
from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import auto_hunter_loop, reset_watchdog_loop
from services.proxy_manager import proxy_scanner_loop

from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("Main")

# ==========================
# Authentication & Security
# ==========================

# API Key header for web panel / API endpoints
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
BEARER_TOKEN = HTTPBearer(auto_error=False)

# Valid API keys (loaded from env or generated)
_valid_api_keys: set[str] = set()
_admin_user_ids: set[int] = set()


def init_auth() -> None:
    """Initialize authentication from config/database."""
    global _valid_api_keys, _admin_user_ids

    # Load API keys from environment
    api_keys_env = os.getenv("API_KEYS", "")
    if api_keys_env:
        _valid_api_keys.update(k.strip() for k in api_keys_env.split(",") if k.strip())

    # Add owner as admin
    _admin_user_ids.add(config.MAIN_OWNER)

    # Generate a default API key if none provided (for development)
    if not _valid_api_keys:
        import secrets
        default_key = secrets.token_urlsafe(32)
        _valid_api_keys.add(default_key)
        log.warning(f"No API_KEYS configured! Generated default: {default_key}")


async def verify_api_key(
    api_key: str = Security(API_KEY_HEADER),
    credentials: HTTPAuthorizationCredentials = Security(BEARER_TOKEN)
) -> str:
    """Verify API key from header or Bearer token."""
    # Check X-API-Key header
    if api_key and api_key in _valid_api_keys:
        return api_key

    # Check Authorization: Bearer header
    if credentials and credentials.credentials in _valid_api_keys:
        return credentials.credentials

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def verify_admin(user_id: int) -> bool:
    """Check if user is admin (for Telegram handlers)."""
    db = get_db()
    data = await db.load()
    return user_id == data.get("owner_id") or user_id in data.get("admins", []) or user_id in data.get("super_admins", [])


# ==========================
# Bot & Dispatcher Setup
# ==========================

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_routers(owner_router, admin_router, user_router)


@dp.callback_query(lambda c: c.data and c.data.startswith("copy_otp_"))
async def copy_otp_callback(cq: CallbackQuery):
    otp = cq.data.split("_")[2]
    await cq.answer(f"📋 OTP: {otp}\n\n(Manually copy karein)", show_alert=True)


# ==========================
# Background Tasks Management
# ==========================

class BackgroundTaskManager:
    """Manages background tasks with graceful shutdown."""

    def __init__(self):
        self._tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    def create_task(self, coro, name: str = "") -> asyncio.Task:
        """Create a tracked background task."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.append(task)
        task.add_done_callback(lambda t: self._tasks.remove(t) if t in self._tasks else None)
        return task

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Cancel all tasks and wait for completion."""
        log.info(f"Shutting down {len(self._tasks)} background tasks...")
        self._shutdown_event.set()

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                log.warning("Some tasks did not complete within timeout")

        log.info("All background tasks stopped")


task_manager = BackgroundTaskManager()


# ==========================
# Background Loops
# ==========================

async def self_ping() -> None:
    """Keep-alive ping to prevent hosting provider from sleeping."""
    url = f"http://127.0.0.1:{config.PORT}/api/health"
    while not task_manager._shutdown_event.is_set():
        try:
            await asyncio.sleep(C.Intervals.SELF_PING)
            if task_manager._shutdown_event.is_set():
                break
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.debug(f"self_ping failed: {e}")


async def db_flush_loop(db: DatabaseService) -> None:
    """Periodically flush pending database writes."""
    while not task_manager._shutdown_event.is_set():
        try:
            await asyncio.sleep(C.Intervals.DB_FLUSH)
            if task_manager._shutdown_event.is_set():
                break
            await db.flush_pending()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning(f"DB flush failed: {e}")


# ==========================
# FastAPI Lifespan
# ==========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with proper startup/shutdown."""
    log.info("Starting SMS-BOT...")

    # Initialize auth
    init_auth()

    # Initialize services
    db = get_db()
    firebase = get_firebase()
    browser_mgr = await get_browser_manager()

    # Verify connections
    try:
        await db.load()
        log.info("Database connected")
    except Exception as e:
        log.error(f"Database connection failed: {e}")

    # Start background tasks
    log.info("Starting background scanners...")
    task_manager.create_task(dp.start_polling(bot), "bot_polling")
    task_manager.create_task(start_scanner(bot), "scanner")
    task_manager.create_task(backup_scanner(bot), "backup_scanner")
    task_manager.create_task(whatsapp_scanner(bot), "whatsapp_scanner")
    task_manager.create_task(auto_hunter_loop(bot), "auto_hunter")
    task_manager.create_task(reset_watchdog_loop(bot), "watchdog")
    task_manager.create_task(proxy_scanner_loop(), "proxy_scanner")
    task_manager.create_task(self_ping(), "self_ping")
    task_manager.create_task(db_flush_loop(db), "db_flush")

    log.info("All services started")

    yield

    # Shutdown
    log.info("Shutting down...")
    await task_manager.shutdown()
    await bot.session.close()
    await firebase.close()
    await close_browser()
    log.info("Shutdown complete")


app = FastAPI(
    title="SMS-BOT API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if config.DEBUG else None,
    redoc_url=None
)


# ==========================
# Web Panel Routes (Protected)
# ==========================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(api_key: str = Depends(verify_api_key)):
    """Main control panel - requires API key."""
    try:
        with open("web_panel/templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


@app.get("/telegram", response_class=HTMLResponse)
async def serve_telegram(api_key: str = Depends(verify_api_key)):
    """Telegram management panel."""
    try:
        with open("web_panel/templates/telegram.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


@app.get("/mini_panel/{token}", response_class=HTMLResponse)
async def serve_mini_panel(token: str, api_key: str = Depends(verify_api_key)):
    """Mini panel for user access - token-based."""
    db = get_db()
    data = await db.load()
    if token not in data.get("mini_tokens", {}):
        raise HTTPException(status_code=403, detail="Invalid or Expired Token")
    try:
        with open("web_panel/templates/mini_panel.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read().replace("{{ token }}", token))
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


@app.get("/user_panel/{user_id}", response_class=HTMLResponse)
async def serve_user_panel(user_id: str, api_key: str = Depends(verify_api_key)):
    """User's personal AI dashboard."""
    try:
        with open("web_panel/templates/user_dashboard.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read().replace("{{ user_id }}", user_id))
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {e}</h1>", status_code=500)


# ==========================
# API Routes (Protected)
# ==========================

@app.get("/api/health")
async def get_health(api_key: str = Depends(verify_api_key)):
    """Comprehensive health check."""
    db = get_db()
    data = await db.load()
    status = db.get_bot_status()
    accounts = data.get("telegram_accounts", {})
    active = sum(1 for a in accounts.values() if a.get("status") == C.AccountStatus.ACTIVE.value)
    total = len(accounts)

    # Check dependency health
    firebase_healthy = True
    try:
        await firebase.check_ping(data.get("firebases", [{}])[0].get("url", ""))
    except Exception:
        firebase_healthy = False

    return JSONResponse(content={
        "status": "healthy",
        "task": status.task,
        "detail": status.detail,
        "last_update": status.last_update,
        "accounts_count": total,
        "active_accounts": active,
        "working_proxies": len(data.get("working_proxies", [])),
        "completion_rate": round((active / total) * 100, 1) if total else 0.0,
        "hunting_enabled": data.get("hunting_enabled", True),
        "dependencies": {
            "database": "connected",
            "firebase": "healthy" if firebase_healthy else "degraded",
            "browser": "ready"
        }
    })


@app.get("/api/get_accounts")
async def get_accounts(api_key: str = Depends(verify_api_key)):
    """Get all Telegram accounts."""
    db = get_db()
    data = await db.load()
    result = []
    for phone, acc in data.get("telegram_accounts", {}).items():
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


@app.get("/api/get_target_accounts")
async def get_target_accounts(api_key: str = Depends(verify_api_key)):
    """Get target accounts for automation."""
    db = get_db()
    data = await db.load()
    result = []
    for acc_id, acc in data.get("target_accounts", {}).items():
        result.append({
            "id": acc_id,
            "user_id": acc.get("user_id"),
            "platform": acc.get("platform", "Unknown"),
            "phone": acc.get("phone", "Unknown"),
            "status": acc.get("status", "unknown"),
            "time": acc.get("time", 0),
        })
    return JSONResponse(content={"status": "success", "targets": result})


@app.get("/api/user_accounts/{user_id}")
async def get_user_accounts(user_id: str, api_key: str = Depends(verify_api_key)):
    """Get accounts for a specific user."""
    db = get_db()
    data = await db.load()
    targets = data.get("target_accounts", {})
    user_accs = []
    for acc_id, acc in targets.items():
        if str(acc.get("user_id")) == user_id:
            user_accs.append({
                "id": acc_id,
                "platform": acc.get("platform", "Unknown"),
                "phone": acc.get("phone", "Unknown"),
                "status": acc.get("status", "failed"),
                "time": acc.get("time", 0)
            })
    return JSONResponse(content={"status": "success", "accounts": user_accs})


@app.get("/api/get_account_otps")
async def get_account_otps(phone: str, api_key: str = Depends(verify_api_key)):
    """Get OTPs for a specific account."""
    db = get_db()
    data = await db.load()
    acc = data.get("telegram_accounts", {}).get(phone)
    if not acc:
        return JSONResponse(
            content={"status": "error", "reason": "Account not found", "otps": []},
            status_code=404
        )
    return JSONResponse(content={"status": "success", "otps": acc.get("otps", [])})


@app.post("/api/clear_account_otps")
async def clear_account_otps(request: Request, api_key: str = Depends(verify_api_key)):
    """Clear OTPs for an account."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    phone = body.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Phone required")

    async with database_transaction() as data:
        if phone in data.get("telegram_accounts", {}):
            data["telegram_accounts"][phone]["otps"] = []

    return JSONResponse(content={"status": "success"})


@app.get("/api/hunting_status")
async def hunting_status(api_key: str = Depends(verify_api_key)):
    """Get hunting status."""
    db = get_db()
    data = await db.load()
    return JSONResponse(content={"enabled": data.get("hunting_enabled", True)})


@app.post("/api/toggle_hunting")
async def toggle_hunting(request: Request, api_key: str = Depends(verify_api_key)):
    """Toggle hunting on/off."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    action = body.get("action")
    async with database_transaction() as data:
        if action == "start":
            data["hunting_enabled"] = True
        elif action == "stop":
            data["hunting_enabled"] = False
        else:
            data["hunting_enabled"] = not data.get("hunting_enabled", True)
        enabled = data["hunting_enabled"]

    return JSONResponse(content={"status": "success", "enabled": enabled})


@app.get("/api/activity_feed")
async def activity_feed(api_key: str = Depends(verify_api_key)):
    """Get activity feed."""
    db = get_db()
    data = await db.load()
    return JSONResponse(content={"status": "success", "feed": data.get("activity_feed", [])})


@app.post("/api/clear_feed")
async def clear_feed(api_key: str = Depends(verify_api_key)):
    """Clear activity feed."""
    async with database_transaction() as data:
        data["activity_feed"] = []
    return JSONResponse(content={"status": "success"})


@app.get("/api/live_screenshot")
async def get_live_screenshot(api_key: str = Depends(verify_api_key)):
    """Get live browser screenshot."""
    try:
        if os.path.exists("live_browser.png"):
            with open("live_browser.png", "rb") as f:
                return Response(
                    content=f.read(),
                    media_type="image/png",
                    headers={"Cache-Control": "no-store"}
                )
        return JSONResponse(content={"error": "No screenshot found"}, status_code=404)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/get_profile")
async def get_profile(api_key: str = Depends(verify_api_key)):
    """Get owner profile."""
    db = get_db()
    data = await db.load()
    return JSONResponse(content={"status": "success", "profile": data.get("owner_profile", {})})


@app.post("/api/save_profile")
async def save_profile(request: Request, api_key: str = Depends(verify_api_key)):
    """Save owner profile."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    async with database_transaction() as data:
        data["owner_profile"] = {
            "username": body.get("username", "").strip(),
            "email": body.get("email", "").strip(),
            "rank": body.get("rank", C.DEFAULTS["OWNER_RANK"])
        }

    return JSONResponse(content={"status": "success"})


@app.get("/api/get_settings")
async def get_settings(api_key: str = Depends(verify_api_key)):
    """Get owner settings."""
    db = get_db()
    data = await db.load()
    return JSONResponse(content={"status": "success", "settings": data.get("owner_settings", {})})


@app.post("/api/save_settings")
async def save_settings(request: Request, api_key: str = Depends(verify_api_key)):
    """Save owner settings."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    async with database_transaction() as data:
        data["owner_settings"] = {
            "poll_interval": max(1, min(30, int(body.get("poll_interval", C.DEFAULTS["POLL_INTERVAL"])))),
            "sound_enabled": bool(body.get("sound_enabled", C.DEFAULTS["SOUND_ENABLED"])),
            "discord_webhook": body.get("discord_webhook", ""),
            "api_base": body.get("api_base", C.DEFAULTS["API_BASE"]),
        }

    return JSONResponse(content={"status": "success"})


# ==========================
# Main Entry Point
# ==========================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        log_level="info",
        access_log=False
    )