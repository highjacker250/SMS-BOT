import asyncio, logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import config
import database as db
from core.scanner import start_scanner
from core.start_bot import start_new_bot
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router

logging.basicConfig(level=logging.INFO)

routers_to_include = [owner_router, admin_router, user_router]

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
    
    for r in routers_to_include:
        dp.include_router(r)
        
    asyncio.create_task(start_scanner(bot))
    
    d = db.load_data()
    for tok in d.get("extra_tokens", []):
        await start_new_bot(tok, routers_to_include)
        
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
