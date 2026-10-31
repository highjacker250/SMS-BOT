import asyncio, logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import config
import database as db
from services.otp_service import start_scanner
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router
from middlewares.throttle import ThrottlingMiddleware

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
    
    # Throttling middleware add kiya
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit=5.0))
    
    dp.include_routers(owner_router, admin_router, user_router)
    
    asyncio.create_task(start_scanner(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
