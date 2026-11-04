import asyncio, logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import config
from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import reset_watchdog_loop # 🚨 Naya
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router

# 🚨 FastAPI Web Panel Import
from web_panel.app import app as fastapi_app
from uvicorn import Config, Server

logging.basicConfig(level=logging.INFO)

async def run_fastapi():
    config = Config(app=fastapi_app, host="0.0.0.0", port=config.PORT + 1, log_level="warning")
    server = Server(config)
    await server.serve()

async def web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', config.PORT).start()

async def main():
    await web_server()
    
    # Start FastAPI panel in background
    asyncio.create_task(run_fastapi())
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_routers(owner_router, admin_router, user_router)
    
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(reset_watchdog_loop()) # 🚨 Naya Watchdog
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
