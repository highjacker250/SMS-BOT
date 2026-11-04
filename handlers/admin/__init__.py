from .dashboard import admin_router as dash_router, admin_home_msg
from .servers import admin_router as srv_router
from .users import admin_router as user_admin_router

from aiogram import Router
admin_router = Router()
admin_router.include_routers(dash_router, srv_router, user_admin_router)
