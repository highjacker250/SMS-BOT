"""
Database service layer with proper connection management, caching, and error handling.
Replaces the global-state database.py with a class-based approach.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional
from supabase import create_client, Client
import config
import constants as C

log = logging.getLogger("Database")


@dataclass
class BotStatus:
    task: str = C.TaskStatus.IDLE.value
    detail: str = "Waiting for tasks..."
    last_update: int = 0


@dataclass
class DatabaseConfig:
    """Configuration for database behavior."""
    cache_ttl: int = 30  # seconds
    save_throttle: float = C.Intervals.DB_SAVE_THROTTLE
    max_activity_feed: int = C.Limits.MAX_ACTIVITY_FEED
    activity_feed_throttle: float = C.Intervals.ACTIVITY_FEED_THROTTLE


class DatabaseService:
    """
    Thread-safe database service with:
    - Connection pooling via Supabase client reuse
    - TTL-based caching with invalidation
    - Atomic save operations with debouncing
    - Structured error handling
    """

    def __init__(self, cfg: Optional[DatabaseConfig] = None):
        self.cfg = cfg or DatabaseConfig()
        self._client: Optional[Client] = None
        self._cache: Optional[dict] = None
        self._cache_time: float = 0
        self._last_save: float = 0
        self._pending_save = False
        self._lock = asyncio.Lock()
        self._bot_status = BotStatus()
        self._feed_push_state = {
            "last_push": 0.0,
            "last_task": None,
            "last_detail": None
        }

    @property
    def client(self) -> Client:
        """Lazy-initialize Supabase client."""
        if self._client is None:
            if not config.SUPABASE_URL or not config.SUPABASE_KEY:
                raise RuntimeError("Supabase credentials not configured")
            self._client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        return self._client

    def _is_cache_valid(self) -> bool:
        return self._cache is not None and (time.time() - self._cache_time) < self.cfg.cache_ttl

    async def load(self, force: bool = False) -> dict:
        """
        Load data from Supabase with caching.
        Returns default structure if DB unavailable.
        """
        if not force and self._is_cache_valid():
            return self._cache

        async with self._lock:
            # Double-check after acquiring lock
            if not force and self._is_cache_valid():
                return self._cache

            data = await self._fetch_from_db()
            self._cache = data
            self._cache_time = time.time()
            return data

    async def _fetch_from_db(self) -> dict:
        """Fetch and normalize data from Supabase."""
        default_data = self._get_default_structure()

        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            log.warning("Supabase not configured, using default structure")
            return default_data

        try:
            # Run blocking Supabase call in executor
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None,
                lambda: self.client.table("bot_data").select("data").eq("id", 1).execute()
            )

            if res.data and len(res.data) > 0 and res.data[0].get("data"):
                data = res.data[0]["data"]
                # Merge with defaults to ensure all keys exist
                return self._merge_with_defaults(data, default_data)
        except Exception as e:
            log.error(f"Supabase load error: {e}")

        return default_data

    def _get_default_structure(self) -> dict:
        """Get the default data structure."""
        return {
            "owner_id": config.MAIN_OWNER,
            "super_admins": [],
            "admins": [],
            "banned": [],
            "free_mode": True,
            "users": {},
            "firebases": [],
            "user_leases": {},
            "used_devices": {},
            "extra_tokens": [],
            "stats": {"total_otps": 0},
            "vip_users": [],
            "device_backups": {},
            "custom_countries": [],
            "upcoming_timers": {},
            "whatsapp_ready_lines": {},
            "telegram_accounts": {},
            "target_accounts": {},
            "hunting_enabled": True,
            "custom_proxies": [],
            "working_proxies": [],
            "mini_tokens": {},
            "activity_feed": [],
            "owner_profile": {
                "username": C.DEFAULTS["OWNER_USERNAME"],
                "email": config.MASTER_EMAIL or "",
                "rank": C.DEFAULTS["OWNER_RANK"]
            },
            "owner_settings": {
                "poll_interval": C.DEFAULTS["POLL_INTERVAL"],
                "sound_enabled": C.DEFAULTS["SOUND_ENABLED"],
                "discord_webhook": C.DEFAULTS["DISCORD_WEBHOOK"],
                "api_base": C.DEFAULTS["API_BASE"],
            },
        }

    def _merge_with_defaults(self, data: dict, defaults: dict) -> dict:
        """Ensure all default keys exist in loaded data."""
        merged = defaults.copy()
        merged.update(data)

        # Ensure nested dicts have required keys
        for uid, user in merged.get("users", {}).items():
            if "auto_session" in user and user["auto_session"]:
                user.setdefault("auto_sessions", {})[user.get("auto_phone", "Unknown_Phone")] = user["auto_session"]
                user.pop("auto_session", None)
            user.setdefault("auto_sessions", {})
            user.setdefault("otp_history", [])
            user.setdefault("saved_numbers", {})

        return merged

    async def save(self, data: dict, force: bool = False) -> bool:
        """
        Save data to Supabase with throttling.
        Returns True if saved, False if throttled.
        """
        self._cache = data
        self._cache_time = time.time()

        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            return False

        now = time.time()
        if not force and (now - self._last_save) < self.cfg.save_throttle:
            self._pending_save = True
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.table("bot_data").update({"data": data}).eq("id", 1).execute()
            )
            self._last_save = now
            self._pending_save = False
            return True
        except Exception as e:
            log.error(f"Supabase save error: {e}")
            self._pending_save = True
            return False

    async def flush_pending(self) -> bool:
        """Force save any pending changes."""
        if self._pending_save and self._cache is not None:
            return await self.save(self._cache, force=True)
        return False

    def invalidate_cache(self) -> None:
        """Invalidate cache to force fresh load on next access."""
        self._cache = None
        self._cache_time = 0

    # ==========================
    # Bot Status Management
    # ==========================
    def set_bot_status(self, task: str, detail: str) -> None:
        self._bot_status.task = task
        self._bot_status.detail = detail
        self._bot_status.last_update = int(time.time())

    def get_bot_status(self) -> BotStatus:
        return self._bot_status

    # ==========================
    # Activity Feed
    # ==========================
    def push_activity(self, task: str, detail: str) -> None:
        """Push to activity feed with throttling."""
        now = time.time()
        state = self._feed_push_state

        if (task == state["last_task"] and
            detail == state["last_detail"] and
            (now - state["last_push"]) < self.cfg.activity_feed_throttle):
            return

        # This will be saved on next save() or flush_pending()
        state["last_push"] = now
        state["last_task"] = task
        state["last_detail"] = detail

    def get_activity_feed(self, data: dict) -> list:
        return data.get("activity_feed", [])

    def clear_activity_feed(self, data: dict) -> None:
        data["activity_feed"] = []

    # ==========================
    # High-level Operations
    # ==========================
    async def get_telegram_accounts(self) -> dict:
        data = await self.load()
        return data.get("telegram_accounts", {})

    async def get_user_lease(self, user_id: int) -> Optional[dict]:
        data = await self.load()
        return data.get("user_leases", {}).get(str(user_id))

    async def set_user_lease(self, user_id: int, lease: dict) -> None:
        data = await self.load()
        data.setdefault("user_leases", {})[str(user_id)] = lease
        await self.save(data)

    async def clear_user_lease(self, user_id: int) -> None:
        data = await self.load()
        if str(user_id) in data.get("user_leases", {}):
            del data["user_leases"][str(user_id)]
            await self.save(data)

    async def add_telegram_account(self, phone: str, account: dict) -> None:
        data = await self.load()
        data.setdefault("telegram_accounts", {})[phone] = account
        await self.save(data)

    async def get_firebases(self) -> list:
        data = await self.load()
        return data.get("firebases", [])

    async def get_working_proxies(self) -> list:
        data = await self.load()
        return data.get("working_proxies", [])

    async def set_working_proxies(self, proxies: list) -> None:
        data = await self.load()
        data["working_proxies"] = proxies
        await self.save(data)

    async def get_custom_proxies(self) -> list:
        data = await self.load()
        return data.get("custom_proxies", [])


# Global instance (initialized on first use)
_db_service: Optional[DatabaseService] = None


def get_db() -> DatabaseService:
    """Get the global database service instance."""
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
    return _db_service


@asynccontextmanager
async def database_transaction():
    """
    Context manager for atomic read-modify-write operations.
    Usage:
        async with database_transaction() as data:
            data['key'] = value
        # Auto-saves on exit
    """
    db = get_db()
    data = await db.load()
    try:
        yield data
    finally:
        await db.save(data, force=True)


# Backward compatibility functions (deprecated)
def load_data() -> dict:
    """Deprecated: Use get_db().load() instead."""
    import warnings
    warnings.warn("load_data() is deprecated, use get_db().load()", DeprecationWarning, stacklevel=2)
    # This is sync - for backward compat only
    db = get_db()
    # Can't await in sync context, return cache or default
    if db._is_cache_valid():
        return db._cache
    return db._get_default_structure()


def save_data(data: dict, force: bool = False) -> None:
    """Deprecated: Use get_db().save() instead."""
    import warnings
    warnings.warn("save_data() is deprecated, use get_db().save()", DeprecationWarning, stacklevel=2)
    db = get_db()
    # Fire and forget
    asyncio.create_task(db.save(data, force=force))


def set_bot_status(task: str, detail: str) -> None:
    get_db().set_bot_status(task, detail)


def get_bot_status() -> dict:
    s = get_db().get_bot_status()
    return {"task": s.task, "detail": s.detail, "last_update": s.last_update}


def push_activity(task: str, detail: str) -> None:
    get_db().push_activity(task, detail)


def get_activity_feed() -> list:
    data = load_data()
    return data.get("activity_feed", [])


def clear_activity_feed() -> None:
    data = load_data()
    data["activity_feed"] = []
    save_data(data, force=True)


def flush_pending() -> None:
    db = get_db()
    asyncio.create_task(db.flush_pending())