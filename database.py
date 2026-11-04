import logging
import time
from supabase import create_client, Client
import config

log = logging.getLogger("DB")
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY) if config.SUPABASE_URL and config.SUPABASE_KEY else None
_DATA_CACHE = None

_BOT_STATUS = {
    "task": "Idle",
    "detail": "Waiting for tasks...",
    "last_update": 0
}

def set_bot_status(task: str, detail: str):
    global _BOT_STATUS
    _BOT_STATUS["task"] = task
    _BOT_STATUS["detail"] = detail
    _BOT_STATUS["last_update"] = int(time.time())

def get_bot_status():
    return _BOT_STATUS

def load_data():
    global _DATA_CACHE
    if _DATA_CACHE is not None: return _DATA_CACHE
    if supabase:
        try:
            res = supabase.table("bot_data").select("data").eq("id", 1).execute()
            if res.data and len(res.data) > 0 and res.data[0]["data"]:
                data = res.data[0]["data"]
                data["owner_id"] = config.MAIN_OWNER
                if "vip_users" not in data: data["vip_users"] = []
                if "device_backups" not in data: data["device_backups"] = {}
                if "custom_countries" not in data: data["custom_countries"] = []
                if "upcoming_timers" not in data: data["upcoming_timers"] = {}
                if "whatsapp_ready_lines" not in data: data["whatsapp_ready_lines"] = {}
                if "telegram_accounts" not in data: data["telegram_accounts"] = {} # 🚨 Naya
                _DATA_CACHE = data
                return _DATA_CACHE
        except Exception as e: 
            log.error(f"Supabase load error: {e}")
    _DATA_CACHE = {
        "owner_id": config.MAIN_OWNER, "super_admins": [], "admins": [], "banned": [], 
        "free_mode": True, "users": {}, "firebases": [], "user_leases": {}, 
        "used_devices": {}, "extra_tokens": [], "stats": {"total_otps": 0}, 
        "vip_users": [], "device_backups": {}, "custom_countries": [], "upcoming_timers": {},
        "whatsapp_ready_lines": {}, "telegram_accounts": {}
    }
    return _DATA_CACHE

def save_data(data):
    global _DATA_CACHE
    _DATA_CACHE = data
    if supabase:
        try: supabase.table("bot_data").update({"data": data}).eq("id", 1).execute()
        except Exception as e: log.error(f"Supabase save error: {e}")
