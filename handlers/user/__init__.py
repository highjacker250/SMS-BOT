from .menu import user_router as menu_router
from .get_number import user_router as get_num_router
from .timers import user_router as timers_router
from .auto_logger import user_auto_router
from .account_login import account_login_router # 🚨 Naya

from aiogram import Router
user_router = Router()
user_router.include_routers(menu_router, get_num_router, timers_router, user_auto_router, account_login_router) # 🚨 Include
