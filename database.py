import os, logging
from supabase import create_client, Client

log = logging.getLogger("DB")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

_DATA_CACHE = None

DEFAULT_URLS = [
    "https://sita-admin-default-rtdb.firebaseio.com",
    "https://my-admin-51-default-rtdb.firebaseio.com",
    "https://webfund3-default-rtdb.firebaseio.com",
    "https://vzvxvz-default-rtdb.firebaseio.com",
    "https://nuna-b-default-rtdb.firebaseio.com",
    "https://shakti-9703d-default-rtdb.firebaseio.com",
    "https://bigg-panal-7fbe5-default-rtdb.firebaseio.com",
    "https://ueur-357f2-default-rtdb.firebaseio.com",
    "https://nmpanagr-default-rtdb.firebaseio.com"
]

def load_data():
    global _DATA_CACHE
    if _DATA_CACHE is not None: return _DATA_CACHE
    if supabase:
        try:
            res = supabase.table("bot_data").select("data").eq("id", 1).execute()
            if res.data and len(res.data) > 0 and res.data[0]["data"]:
                data = res.data[0]["data"]
                if not data.get("firebases"):
                    data["firebases"] = [{"url": u, "label": u.split("//")[-1].split(".")[0], "auth": ""} for u in DEFAULT_URLS]
                _DATA_CACHE = data
                return _DATA_CACHE
        except Exception as e: log.error(f"Supabase load error: {e}")
    
    _DATA_CACHE = {
        "owner_id": 8480878371, "admins": [], "users": {}, "free_mode": True, "banned": [], "extra_tokens": [],
        "firebases": [{"url": u, "label": u.split("//")[-1].split(".")[0], "auth": ""} for u in DEFAULT_URLS],
        "user_leases": {}, "user_history": {}, "stats": {"total_otps": 0},
        "device_usage": {}, "videos": [], "pricing": {"plans": []}, "settings": {"ref_credits": 3}
    }
    return _DATA_CACHE

def save_data(data):
    global _DATA_CACHE
    _DATA_CACHE = data
    if supabase:
        try: supabase.table("bot_data").update({"data": data}).eq("id", 1).execute()
        except Exception as e: log.error(f"Supabase save error: {e}")
