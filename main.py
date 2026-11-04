import asyncio
import logging
import aiohttp

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import config
from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import reset_watchdog_loop
from services.proxy_manager import proxy_scanner_loop
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router
import database as db

logging.basicConfig(level=logging.INFO)

# 🚨 NAYA: Simple Panel renderer (Bina FastAPI ke, taaki 500 error na aaye)
async def panel_handler(request):
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    bot_status = db.get_bot_status()
    
    html = f"""
    <html>
    <head>
        <title>AI TG Panel</title>
        <style>
            body {{ font-family: Arial; background: #17212b; color: #fff; margin: 0; }}
            .sidebar {{ width: 300px; height: 100vh; background: #0e1621; float: left; padding: 20px; }}
            .main {{ margin-left: 320px; padding: 20px; }}
            .account {{ padding: 10px; border-bottom: 1px solid #242f3d; }}
            .status-active {{ color: #4caf50; }}
            .status-waiting_7_days {{ color: #ff9800; }}
            .status-failed {{ color: #f44336; }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>TG Accounts</h2>
            {"".join([f'<div class="account"><b>+{phone}</b><br><span class="status-{acc.get("status", "unknown")}">{acc.get("status", "unknown").upper()}</span></div>' for phone, acc in accounts.items()])}
        </div>
        <div class="main">
            <h1>Live Status</h1>
            <p><b>Task:</b> {bot_status.get('task')}</p>
            <p><b>Detail:</b> {bot_status.get('detail')}</p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

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

async def main():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Running!"))
    app.router.add_get('/panel', panel_handler) # 🚨 Panel route
    
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', config.PORT).start()
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_routers(owner_router, admin_router, user_router)
    
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(reset_watchdog_loop())
    asyncio.create_task(proxy_scanner_loop())
    asyncio.create_task(self_ping()) 
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
