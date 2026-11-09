# services/ai_brain.py
import json
import logging
import aiohttp
from groq import Groq
import database as db
import config

log = logging.getLogger("AIBrain")

# ==========================
# 1. GROQ SETUP
# ==========================
groq_client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None
MODEL = "llama-3.1-8b-instant"

# ==========================
# 2. DEEPSEEK SETUP
# ==========================
DEEPSEEK_KEY = config.DEEPSEEK_API_KEY
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# ==========================
# 3. GEMINI SETUP
# ==========================
GEMINI_KEY = config.GEMINI_API_KEY
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"

# ==========================
# 4. CLEAN APIs
# ==========================
CLEAN_API_KEY = config.CLEAN_API_KEY
CLEAN_API_URL = "https://cleanapis.com/v1/chat/completions"


def get_ready_whatsapp_lines():
    d = db.load_data()
    lines = d.get("whatsapp_ready_lines", {})
    result = []
    for dev_id, info in lines.items():
        result.append({
            "rent_id": dev_id,
            "number": info.get("number"),
            "battery": info.get("battery"),
            "health": info.get("health"),
            "chance": info.get("chance"),
        })
    return json.dumps(result)


tools = [{
    "type": "function",
    "function": {
        "name": "get_ready_whatsapp_lines",
        "description": "Returns available WhatsApp verification lines with health, battery, chance.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}]


# ==========================
# HELPER: DEEPSEEK
# ==========================
async def call_deepseek(messages, tools=None):
    if not DEEPSEEK_KEY:
        return None
    headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}
    payload = {"model": DEEPSEEK_MODEL, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]
                log.error(f"DeepSeek Error {resp.status}: {await resp.text()}")
    except Exception as e:
        log.error(f"DeepSeek Exception: {e}")
    return None


# ==========================
# HELPER: GEMINI
# ==========================
async def call_gemini(messages, tools=None):
    if not GEMINI_KEY:
        return None
    headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_KEY}
    contents = []
    for m in messages:
        role = "user" if m["role"] in ["user", "system"] else "model"
        if m.get("content"):
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        
    payload = {"contents": contents}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GEMINI_URL, headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return {"role": "assistant", "content": text}
                log.error(f"Gemini Error {resp.status}: {await resp.text()}")
    except Exception as e:
        log.error(f"Gemini Exception: {e}")
    return None


# ==========================
# HELPER: CLEAN APIs
# ==========================
async def call_clean_api(messages, tools=None):
    if not CLEAN_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {CLEAN_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "gpt-3.5-turbo", "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CLEAN_API_URL, headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]
                log.error(f"CleanAPI Error {resp.status}: {await resp.text()}")
    except Exception as e:
        log.error(f"CleanAPI Exception: {e}")
    return None


# ==========================
# MAIN AI LOGIC (FALLBACK CHAIN)
# ==========================
async def get_best_number_with_ai(service_type="whatsapp"):
    system_prompt = (
        "You are an expert backend AI for a Telegram OTP Bot. "
        "Select the BEST number. Call tool `get_ready_whatsapp_lines`. "
        "Return exactly ONE best `rent_id` as pure JSON: {\"rent_id\": \"...\", \"reason\": \"...\"}."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Find the best {service_type} number."},
    ]

    # 1. Groq
    if groq_client:
        try:
            response = groq_client.chat.completions.create(
                model=MODEL, messages=messages, tools=tools, tool_choice="auto", temperature=0.1
            )
            msg = response.choices[0].message
            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    fn = tc.function.name
                    if fn == "get_ready_whatsapp_lines":
                        messages.append({"tool_call_id": tc.id, "role": "tool", "name": fn, "content": get_ready_whatsapp_lines()})
                second = groq_client.chat.completions.create(model=MODEL, messages=messages, temperature=0.1)
                final = second.choices[0].message.content
                return json.loads(final.replace("```json", "").replace("```", "").strip()).get("rent_id"), "Groq"
        except Exception as e:
            log.warning(f"Groq failed: {e}")

    # 2. DeepSeek
    msg = await call_deepseek(messages, tools)
    if msg and msg.get("tool_calls"):
        messages.append(msg)
        for tc in msg["tool_calls"]:
            if tc["function"]["name"] == "get_ready_whatsapp_lines":
                messages.append({"tool_call_id": tc["id"], "role": "tool", "name": "get_ready_whatsapp_lines", "content": get_ready_whatsapp_lines()})
        second = await call_deepseek(messages)
        if second and second.get("content"):
            try:
                return json.loads(second["content"].replace("```json", "").replace("```", "").strip()).get("rent_id"), "DeepSeek"
            except: pass

    # 3. Gemini
    msg = await call_gemini(messages)
    if msg and msg.get("content"):
        try:
            return json.loads(msg["content"].replace("```json", "").replace("```", "").strip()).get("rent_id"), "Gemini"
        except: pass

    # 4. Clean APIs
    msg = await call_clean_api(messages, tools)
    if msg and msg.get("tool_calls"):
        messages.append(msg)
        for tc in msg["tool_calls"]:
            if tc["function"]["name"] == "get_ready_whatsapp_lines":
                messages.append({"tool_call_id": tc["id"], "role": "tool", "name": "get_ready_whatsapp_lines", "content": get_ready_whatsapp_lines()})
        second = await call_clean_api(messages)
        if second and second.get("content"):
            try:
                return json.loads(second["content"].replace("```json", "").replace("```", "").strip()).get("rent_id"), "CleanAPI"
            except: pass

    return None, "❌ Saari APIs fail ho gayi (Groq, DeepSeek, Gemini, CleanAPI)."


async def chat_with_ai_owner(user_msg):
    messages = [
        {"role": "system", "content": "You are a technical coding assistant for a Telegram Bot Owner. Keep answers short and in Hinglish."},
        {"role": "user", "content": user_msg}
    ]
    
    if groq_client:
        try:
            response = groq_client.chat.completions.create(model=MODEL, messages=messages, temperature=0.5)
            return response.choices[0].message.content
        except Exception as e:
            log.warning(f"Groq chat failed: {e}")
            
    msg = await call_deepseek(messages)
    if msg and msg.get("content"): return msg["content"]
            
    msg = await call_gemini(messages)
    if msg and msg.get("content"): return msg["content"]

    msg = await call_clean_api(messages)
    if msg and msg.get("content"): return msg["content"]
        
    return "🤖 AI Error: Saari APIs (Groq, DeepSeek, Gemini, Clean) fail ho gayi."
