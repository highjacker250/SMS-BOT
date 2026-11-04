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

@app.get("/", response_class=HTMLResponse)
async def health_check():
    return "Bot is Running! Go to /panel for dashboard."

# 🚨 SAFE HTML RENDER ROUTE (Bina Jinja2 ke, taaki 500 error na aaye)
@app.get("/panel", response_class=HTMLResponse)
async def owner_panel(request: Request):
    try:
        d = db.load_data()
        accounts = d.get("telegram_accounts", {})
        bot_status = db.get_bot_status()
        
        # HTML me bhejne ke liye data ready karo
        account_cards = ""
        if not accounts:
            account_cards = "<div style='color: #7f91a4;'>No accounts logged in yet.</div>"
        else:
            for phone, acc in accounts.items():
                status = acc.get("status", "unknown")
                color = "#4fae4e" if status == "active" else ("#e8a838" if status == "waiting_7_days" else "#e53935")
                session = acc.get("session", "")
                session_preview = session[:10] + "..." if session else "No Session"
                
                account_cards += f"""
                <div style="background: #242f3d; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 4px solid {color};">
                    <h4 style="margin: 0; color: #fff;">{phone}</h4>
                    <p style="margin: 5px 0 0 0; font-size: 12px; color: #7f91a4;">Session: {session_preview}</p>
                    <span style="font-size: 10px; font-weight: bold; color: {color}; text-transform: uppercase;">{status}</span>
                </div>
                """

        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Telegram OTP Bot Panel</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
            <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
            <style>
                body {{ background-color: #0e1621; color: #f5f5f5; font-family: 'Roboto', sans-serif; margin: 0; overflow: hidden; }}
                .sidebar {{ width: 320px; background: #17212b; height: 100vh; float: left; padding: 20px; border-right: 1px solid #242f3d; }}
                .main {{ margin-left: 320px; height: 100vh; display: flex; flex-direction: column; }}
                .topbar {{ padding: 15px 25px; background: #17212b; border-bottom: 1px solid #242f3d; display: flex; justify-content: space-between; align-items: center; }}
                .status-box {{ background: #0e1621; padding: 10px 20px; border-radius: 10px; border: 1px solid #242f3d; display: flex; align-items: center; gap: 15px; }}
                .dot {{ width: 10px; height: 10px; background: #4fae4e; border-radius: 50%; animation: pulse 2s infinite; }}
                @keyframes pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(79, 174, 78, 0.7); }} 70% {{ box-shadow: 0 0 0 10px rgba(79, 174, 78, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(79, 174, 78, 0); }} }}
            </style>
        </head>
        <body>
            <div class="sidebar">
                <h2 style="font-size: 18px; margin-bottom: 20px; color: #5288c1;"><i class="fa-brands fa-telegram"></i> AI Sentinel</h2>
                <h3 style="font-size: 12px; color: #7f91a4; text-transform: uppercase; margin-bottom: 15px;">Live Accounts ({len(accounts)})</h3>
                {account_cards}
            </div>
            <div class="main">
                <div class="topbar">
                    <h1 style="font-size: 18px; margin: 0;">Owner Control Dashboard</h1>
                    <div class="status-box">
                        <div class="dot"></div>
                        <div>
                            <p style="margin: 0; font-size: 10px; color: #4fae4e; font-weight: bold; text-transform: uppercase;">AI Live Status</p>
                            <p style="margin: 0; font-size: 12px;">{bot_status.get('task', 'Idle')} - {bot_status.get('detail', 'Waiting...')}</p>
                        </div>
                    </div>
                </div>
                <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #7f91a4;">
                    <i class="fa-solid fa-shield-halved" style="font-size: 60px; opacity: 0.3; margin-bottom: 20px;"></i>
                    <h2 style="color: #fff; margin: 0;">System is Protected</h2>
                    <p style="margin-top: 10px;">WARP Proxy & Telegram Accounts are running smoothly.</p>
                </div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    except Exception as e:
        log.error(f"Panel Error: {e}")
        return HTMLResponse(content=f"<h1 style='color:red;'>Panel Error: {str(e)}</h1>", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
