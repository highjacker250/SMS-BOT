# database.py
import logging
import time
from supabase import create_client, Client
import config

log = logging.getLogger("DB")
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY) if config.SUPABASE_URL and config.SUPABASE_KEY else None
_DATA_CACHE = None

_BOT_STATUS = {"task": "Idle", "detail": "Waiting for tasks...", "last_update": 0}
ACTIVITY_FEED_MAX = 50

# Throttle control (Fixes PATCH spam)
_LAST_FEED_PUSH = 0.0
_LAST_FEED_TASK = None
_LAST_FEED_DETAIL = None
_FEED_MIN_INTERVAL = 60.0 

_LAST_SAVE = 0.0
_SAVE_MIN_INTERVAL = 2.0
_PENDING_SAVE = False


def set_bot_status(task: str, detail: str):
    global _BOT_STATUS
    _BOT_STATUS["task"] = task
    _BOT_STATUS["detail"] = detail
    _BOT_STATUS["last_update"] = int(time.time())


def push_activity(task: str, detail: str):
    global _LAST_FEED_PUSH, _LAST_FEED_TASK, _LAST_FEED_DETAIL
    now = time.time()
    if task == _LAST_FEED_TASK and (now - _LAST_FEED_PUSH) < _FEED_MIN_INTERVAL:
        return
    try:
        d = load_data()
        feed = d.setdefault("activity_feed", [])
        feed.insert(0, {"time": int(time.time()), "task": task, "detail": detail})
        d["activity_feed"] = feed[:ACTIVITY_FEED_MAX]
        save_data(d)
        _LAST_FEED_PUSH = now
        _LAST_FEED_TASK = task
        _LAST_FEED_DETAIL = detail
    except Exception as e:
        log.warning(f"Feed push failed: {e}")


def get_bot_status():
    return _BOT_STATUS


def get_activity_feed():
    return load_data().get("activity_feed", [])


def clear_activity_feed():
    d = load_data()
    d["activity_feed"] = []
    save_data(d, force=True)


def load_data():
    global _DATA_CACHE
    if _DATA_CACHE is not None:
        return _DATA_CACHE
    if supabase:
        try:
            res = supabase.table("bot_data").select("data").eq("id", 1).execute()
            if res.data and len(res.data) > 0 and res.data[0]["data"]:
                data = res.data[0]["data"]
                data["owner_id"] = config.MAIN_OWNER
                for k in ["vip_users", "custom_countries", "mini_tokens"]:
                    if k not in data: data[k] = []
                for k in ["device_backups", "upcoming_timers", "whatsapp_ready_lines", "telegram_accounts", "target_accounts"]:
                    if k not in data: data[k] = {}
                if "hunting_enabled" not in data: data["hunting_enabled"] = True
                if "custom_proxies" not in data: data["custom_proxies"] = []
                if "working_proxies" not in data: data["working_proxies"] = []
                if "activity_feed" not in data: data["activity_feed"] = []
                if "owner_profile" not in data:
                    data["owner_profile"] = {"username": "operator", "email": config.MASTER_EMAIL, "rank": "S-RANK HUNTER"}
                if "owner_settings" not in data:
                    data["owner_settings"] = {"poll_interval": 3, "sound_enabled": True, "discord_webhook": "", "api_base": "/api"}
                for uid, user in data.get("users", {}).items():
                    if "auto_session" in user and user["auto_session"]:
                        user.setdefault("auto_sessions", {})[user.get("auto_phone", "Unknown_Phone")] = user["auto_session"]
                        del user["auto_session"]
                    if "auto_sessions" not in user: user["auto_sessions"] = {}
                _DATA_CACHE = data
                return _DATA_CACHE
        except Exception as e:
            log.error(f"Supabase load error: {e}")
    _DATA_CACHE = {
        "owner_id": config.MAIN_OWNER, "super_admins": [], "admins": [], "banned": [],
        "free_mode": True, "users": {}, "firebases": [], "user_leases": {}, "used_devices": {},
        "extra_tokens": [], "stats": {"total_otps": 0}, "vip_users": [], "device_backups": {},
        "custom_countries": [], "upcoming_timers": {}, "whatsapp_ready_lines": {},
        "telegram_accounts": {}, "target_accounts": {}, "hunting_enabled": True,
        "custom_proxies": [], "working_proxies": [], "mini_tokens": {},
        "activity_feed": [],
        "owner_profile": {"username": "operator", "email": config.MASTER_EMAIL, "rank": "S-RANK HUNTER"},
        "owner_settings": {"poll_interval": 3, "sound_enabled": True, "discord_webhook": "", "api_base": "/api"},
    }
    return _DATA_CACHE


def save_data(data, force=False):
    global _DATA_CACHE, _LAST_SAVE, _PENDING_SAVE
    _DATA_CACHE = data
    if not supabase:
        return
    now = time.time()
    if not force and (now - _LAST_SAVE) < _SAVE_MIN_INTERVAL:
        _PENDING_SAVE = True
        return
    try:
        supabase.table("bot_data").update({"data": data}).eq("id", 1).execute()
        _LAST_SAVE = now
        _PENDING_SAVE = False
    except Exception as e:
        log.error(f"Supabase save error: {e}")


def flush_pending():
    global _PENDING_SAVE
    if _PENDING_SAVE and _DATA_CACHE is not None:
        save_data(_DATA_CACHE, force=True)
