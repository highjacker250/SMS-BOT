import database as db
from datetime import datetime, timedelta

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
    fb_countries = [fb.get("country", "India") for fb in data.get("firebases", [])]
    custom_countries = data.get("custom_countries", [])
    return sorted(list(set(fb_countries + custom_countries)))

def get_servers_grouped(data, country: str):
    fbs = [fb for fb in data.get("firebases", []) if fb.get("country", "India") == country]
    return [fbs[i:i+25] for i in range(0, len(fbs), 25)]

def get_ist_time_str(ts):
    ist = datetime.utcfromtimestamp(ts) + timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b %Y | %I:%M %p")
