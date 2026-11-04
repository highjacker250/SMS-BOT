import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAIN_OWNER = 8480878371
PORT = int(os.getenv("PORT", 8080))

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

TG_API_ID = int(os.getenv("TG_API_ID", 39458429))
TG_API_HASH = os.getenv("TG_API_HASH", "bcd4426911f4d1f04ddb7c881abf1bcc")
MASTER_EMAIL = os.getenv("MASTER_EMAIL", "iamnotready171@gmail.com")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "uhuqjurpxqkvayet")

WEB_URL = os.getenv("WEB_URL", "http://localhost:8081")
