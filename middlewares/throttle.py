import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 5.0):
        self.rate_limit = rate_limit
        self.user_cooldowns = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        # Check only for specific spam-prone buttons
        spam_actions = ["user:get_num", "user:server:", "user:country:", "user:access:"]
        if not any(event.data.startswith(act) for act in spam_actions):
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.time()

        if user_id in self.user_cooldowns:
            last_time = self.user_cooldowns[user_id]
            if now - last_time < self.rate_limit:
                await event.answer(f"⏳ Thoda sabar karein! {int(self.rate_limit - (now - last_time))}s baad try karein.", show_alert=True)
                return

        self.user_cooldowns[user_id] = now
        return await handler(event, data)
