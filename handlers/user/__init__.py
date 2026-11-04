from .menu import user_router as menu_router
from .get_number import user_router as get_num_router
from .timers import user_router as timers_router

from aiogram import Router
user_router = Router()
# 🚨 Ensure karo ki saare routers yahan include hain
user_router.include_routers(menu_router, get_num_router, timers_router)
