import asyncio
import logging
import aiohttp

# 🚨 PYTHON 3.14 FIX for Pyrogram
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

from web_panel.app import app as fastapi_app
from uvicorn import Config, Server

logging.basicConfig(level=logging.INFO)

async def run_fastapi():
    conf = Config(app=fastapi_app, host="0.0.0.0", port=config.PORT + 1, log_level="warning")
    server = Server(conf)
    await server.serve()

async def web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', config.PORT).start()

# 🚨 NAYA: Self-Ping System for Render Free Tier
async def self_ping():
    url = f"http://localhost:{config.PORT}/"
    while True:
        await asyncio.sleep(600) # Har 10 min me ping
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    pass
            logging.info("Self-ping successful.")
        except Exception as e:
            logging.warning(f"Self-ping failed: {e}")

async def main():
    await web_server()
    asyncio.create_task(run_fastapi())
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_routers(owner_router, admin_router, user_router)
    
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(reset_watchdog_loop())
    asyncio.create_task(proxy_scanner_loop())
    asyncio.create_task(self_ping()) # 🚨 Start Self Ping
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
