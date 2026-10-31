import time
import database as db

COOLDOWNS = {}

def check_cooldown(uid: int) -> bool:
    now = time.time()
    if uid in COOLDOWNS and now - COOLDOWNS[uid] < 5: return False
    COOLDOWNS[uid] = now
    return True

def is_owner(uid):
    d = db.load_data()
    return uid == d.get("owner_id") or uid in d.get("super_admins", [])

def is_admin(uid):
    d = db.load_data()
    return is_owner(uid) or uid in d.get("admins", [])

def clear_user_lease(uid):
    d = db.load_data()
    if str(uid) in d.get("user_leases", {}):
        del d["user_leases"][str(uid)]
        db.save_data(d)

def get_countries(data):
    return sorted(list(set([fb.get("country", "India") for fb in data.get("firebases", [])])))

def get_servers_grouped(data, country: str):
    fbs = [fb for fb in data.get("firebases", []) if fb.get("country", "India") == country]
    return [fbs[i:i+25] for i in range(0, len(fbs), 25)]
