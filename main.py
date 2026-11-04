import asyncio
import logging
import aiohttp

# 🚨 PYTHON 3.14 FIX for Pyrogram
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
import config
from core.scanner import start_scanner, backup_scanner, whatsapp_scanner
from services.telegram_automation import reset_watchdog_loop
from services.proxy_manager import proxy_scanner_loop
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.owner import owner_router

# FastAPI Import
from web_panel.app import app as fastapi_app
from uvicorn import Config, Server

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Main")

# 🚨 1. FastAPI (Panel) ko Port 8081 pe start karo
async def run_fastapi():
    conf = Config(app=fastapi_app, host="127.0.0.1", port=config.PORT + 1, log_level="warning")
    server = Server(conf)
    await server.serve()

# 🚨 2. Main Web Server (Port 8080) jo requests ko handle karega
async def web_server():
    app = web.Application()
    
    # Bot keep-alive route
    app.router.add_get('/', lambda r: web.Response(text="Bot Running!"))
    
    # 🚨 PROXY ROUTE: Agar koi /panel pe aaye, toh use FastAPI (8081) pe bhej do
    async def proxy_to_fastapi(request):
        target_url = f"http://127.0.0.1:{config.PORT + 1}{request.path_qs}"
        
        async with ClientSession() as session:
            # Original request ke headers copy karo
            headers = dict(request.headers)
            headers.pop('Host', None) # Host header hatao warna FastAPI confuse hoga
            
            # Body read karo (agar POST request hai toh)
            body = await request.read() if request.method in ["POST", "PUT", "PATCH"] else None
            
            async with session.request(request.method, target_url, headers=headers, data=body) as resp:
                resp_body = await resp.read()
                # Response wapas bhej do
                return web.Response(
                    body=resp_body,
                    status=resp.status,
                    headers={k: v for k, v in resp.headers.items() if k.lower() not in ('content-encoding', 'transfer-encoding', 'content-length')},
                    content_type=resp.content_type
                )
                
    # Saare panel routes proxy kar do
    app.router.add_route('*', '/panel', proxy_to_fastapi)
    app.router.add_route('*', '/panel/{tail:.*}', proxy_to_fastapi)
    
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', config.PORT).start()

# 🚨 3. Render Free Tier ke liye Self-Ping (15 min me sleep na ho)
async def self_ping():
    url = f"http://localhost:{config.PORT}/"
    while True:
        await asyncio.sleep(600) # Har 10 min me ping
        try:
            async with ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    pass
            log.info("Self-ping successful.")
        except Exception as e:
            log.warning(f"Self-ping failed: {e}")

async def main():
    # Dono servers start karo
    asyncio.create_task(run_fastapi())
    await asyncio.sleep(2) # FastAPI ko start hone ka time do
    await web_server()
    
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_routers(owner_router, admin_router, user_router)
    
    # Background Tasks start karo
    asyncio.create_task(start_scanner(bot))
    asyncio.create_task(backup_scanner(bot))
    asyncio.create_task(whatsapp_scanner(bot))
    asyncio.create_task(reset_watchdog_loop())
    asyncio.create_task(proxy_scanner_loop())
    asyncio.create_task(self_ping()) 
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
