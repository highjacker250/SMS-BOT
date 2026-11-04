from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import database as db
import config

app = FastAPI()
templates = Jinja2Templates(directory="web_panel/templates")

@app.get("/panel", response_class=HTMLResponse)
async def owner_panel(request: Request):
    # Note: Yahan Owner authentication (password check) lagega
    d = db.load_data()
    accounts = d.get("telegram_accounts", {})
    return templates.TemplateResponse("index.html", {"request": request, "accounts": accounts})
