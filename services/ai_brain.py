# services/ai_brain.py
import json
import logging
import aiohttp
from groq import Groq
import database as db
import config

log = logging.getLogger("AIBrain")

# ==========================
# CLIENT SETUP
# ==========================
groq_client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None
GROQ_MODEL = "llama-3.1-8b-instant"

# ==========================
# HELPER: OPENROUTER
# ==========================
async def call_openrouter(messages):
    if not config.OPENROUTER_API_KEY: return None
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": config.WEB_URL,
        "X-Title": "OTP Bot"
    }
    # Using a good fast free model on OpenRouter
    payload = {"model": "meta-llama/llama-3-8b-instruct", "messages": messages}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                log.error(f"OpenRouter Error {resp.status}: {await resp.text()}")
    except Exception as e:
        log.error(f"OpenRouter Exception: {e}")
    return None

# ==========================
# HELPER: GEMINI
# ==========================
async def call_gemini(messages):
    if not config.GEMINI_API_KEY: return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={config.GEMINI_API_KEY}"
    
    # Format messages for Gemini
    contents = []
    for m in messages:
        role = "user" if m["role"] in ["user", "system"] else "model"
        if m.get("content"):
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
            
    payload = {"contents": contents}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                log.error(f"Gemini Error {resp.status}: {await resp.text()}")
    except Exception as e:
        log.error(f"Gemini Exception: {e}")
    return None

# ==========================
# HELPER: CLOUDFLARE
# ==========================
async def call_cloudflare(messages):
    if not config.CLOUDFLARE_API_TOKEN or not config.CLOUDFLARE_ACCOUNT_ID: return None
    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/meta/llama-3-8b-instruct"
    headers = {"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}"}
    
    # Cloudflare expects a single prompt
    prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    payload = {"messages": [{"role": "user", "content": prompt}]}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["result"]["response"]
                log.error(f"Cloudflare Error {resp.status}: {await resp.text()}")
    except Exception as e:
        log.error(f"Cloudflare Exception: {e}")
    return None

# ==========================
# HELPER: DEEPSEEK
# ==========================
async def call_deepseek(messages):
    if not config.DEEPSEEK_API_KEY: return None
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": messages}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                log.error(f"DeepSeek Error {resp.status}: {await resp.text()}")
    except Exception as e:
        log.error(f"DeepSeek Exception: {e}")
    return None


# ==========================
# MAIN AI LOGIC (FALLBACK)
# ==========================
async def get_best_number_with_ai(service_type="whatsapp"):
    # ... (Tumhara purana whatsapp function, isme koi change nahi karna) ...
    # Bas isko waise hi rakho jaise pehle tha.
    pass # Assuming you keep your original logic here


# ==========================
# CHAT WITH OWNER (UPDATED)
# ==========================
async def chat_with_ai_owner(user_msg):
    messages = [
        {"role": "system", "content": "You are a technical coding assistant for a Telegram Bot Owner. Keep answers short and in Hinglish. Give direct code fixes."},
        {"role": "user", "content": user_msg}
    ]
    
    # 1. Try Groq (Fastest)
    if groq_client:
        try:
            response = groq_client.chat.completions.create(model=GROQ_MODEL, messages=messages, temperature=0.5)
            return response.choices[0].message.content
        except Exception as e:
            log.warning(f"Groq chat failed: {e}")
            
    # 2. Try OpenRouter (Great Fallback)
    res = await call_openrouter(messages)
    if res: return res

    # 3. Try Gemini
    res = await call_gemini(messages)
    if res: return res

    # 4. Try Cloudflare
    res = await call_cloudflare(messages)
    if res: return res
    
    # 5. Try DeepSeek
    res = await call_deepseek(messages)
    if res: return res
        
    return "🤖 AI Error: Saari APIs (Groq, OpenRouter, Gemini, Cloudflare, DeepSeek) fail ho gayi."
