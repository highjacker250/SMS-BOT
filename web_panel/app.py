from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import database as db
import config

app = FastAPI()
templates = Jinja2Templates(directory="web_panel/templates")

@app.get("/panel", response_class=HTMLResponse)
async def owner_panel(request: Request):
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    bot_status = db.get_bot_status()
    proxies = d.get("working_proxies", [])
    
    # 🚨 Data ko format karo taaki HTML easily padh sake
    formatted_accounts = []
    for phone, acc in accounts.items():
        formatted_accounts.append({
            "phone": phone,
            "status": acc.get("status", "unknown"),
            "session": acc.get("session", "")[:10] + "..." if acc.get("session") else "No Session",
            "reset_time": acc.get("reset_time", 0)
        })
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "accounts": formatted_accounts,
        "bot_status": bot_status,
        "proxies": proxies
    })
