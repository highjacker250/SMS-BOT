import asyncio, logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import config
from core.scanner import start_scanner, backup_scanner
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router

logging.basicConfig(level=logging.INFO)

async def web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', config.PORT).start()

async def main():
    await web_server()
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Routers include karo
    dp.include_routers(owner_router, admin_router, user_router)
    
    # Background tasks start karo (bot pass karna zaroori hai)
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    
    # Polling start karo
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
