from .dashboard import admin_router as dash_router, admin_home_msg
from .servers import admin_router as srv_router
from .users import admin_router as user_admin_router
from .tg_login import admin_router as tg_login_router
from .proxy import admin_router as proxy_router
from .ai_chat import admin_router as ai_chat_router

from aiogram import Router
admin_router = Router()
admin_router.include_routers(dash_router, srv_router, user_admin_router, tg_login_router, proxy_router, ai_chat_router)2
