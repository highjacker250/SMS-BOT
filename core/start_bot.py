import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

running_bots = {}

async def start_new_bot(token: str, routers: list):
    if token in running_bots: return
    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    for r in routers:
        dp.include_router(r)
    running_bots[token] = bot
    asyncio.create_task(dp.start_polling(bot))
    logging.info(f"New bot started: {token[:10]}...")
