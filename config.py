import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAIN_OWNER = 8480878371  # Apna ID daal lena
PORT = int(os.getenv("PORT", 8080))

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# 🚨 NAYA: Groq API Key for AI
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
