import logging
from supabase import create_client, Client
import config

log = logging.getLogger("DB")
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY) if config.SUPABASE_URL and config.SUPABASE_KEY else None

_DATA_CACHE = None

def load_data():
    global _DATA_CACHE
    if _DATA_CACHE is not None: return _DATA_CACHE
    
    if supabase:
        try:
            res = supabase.table("bot_data").select("data").eq("id", 1).execute()
            if res.data and len(res.data) > 0 and res.data[0]["data"]:
                data = res.data[0]["data"]
                _DATA_CACHE = data
                return _DATA_CACHE
        except Exception as e: 
            log.error(f"Supabase load error: {e}")
    
    _DATA_CACHE = {
        "owner_id": config.MAIN_OWNER, "super_admins": [], "admins": [], "banned": [], 
        "free_mode": True, "users": {}, "firebases": [], "user_leases": {}, 
        "used_devices": {}, "extra_tokens": [], "stats": {"total_otps": 0}
    }
    return _DATA_CACHE

def save_data(data):
    global _DATA_CACHE
    _DATA_CACHE = data
    if supabase:
        try: 
            supabase.table("bot_data").update({"data": data}).eq("id", 1).execute()
        except Exception as e: 
            log.error(f"Supabase save error: {e}")
