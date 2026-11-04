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
    working_proxies = d.get("working_proxies", [])
    bot_status = db.get_bot_status()
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "accounts": accounts,
        "proxies": working_proxies,
        "bot_status": bot_status
    })
