import os

# ==========================
# TELEGRAM & OWNER
# ==========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAIN_OWNER = 8480878371
PORT = int(os.getenv("PORT", 8080))
WEB_URL = os.getenv("WEB_URL", "https://sms-bot-l6sz.onrender.com")

# ==========================
# DATABASE (SUPABASE)
# ==========================
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ==========================
# AI KEYS
# ==========================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLEAN_API_KEY = os.getenv("CLEAN_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ==========================
# TELEGRAM API & EMAIL
# ==========================
TG_API_ID = int(os.getenv("TG_API_ID", 39458429))
TG_API_HASH = os.getenv("TG_API_HASH", "")
MASTER_EMAIL = os.getenv("MASTER_EMAIL", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

# ==========================
# PAYPAL API
# ==========================
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET", "")
PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox")

# ==========================
# MISC
# ==========================
WARP_PROXY = None
