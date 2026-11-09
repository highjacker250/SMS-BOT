# services/ai_brain.py
import json
import logging
import aiohttp
from groq import Groq
import database as db
import config

log = logging.getLogger("AIBrain")

# 🚨 GROQ SETUP
groq_client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None
MODEL = "llama-3.1-8b-instant"  # 404 fix: Naya valid model

# 🚨 CLEAN APIS SETUP (Jo screenshot me key thi)
CLEAN_API_KEY = "cc_5mfVMbsqqYEbqr5nAoNxVOQkbfw66ZYKlsgvxDWBs5nm78Pw"
CLEAN_API_URL = "https://cleanapis.com/v1/chat/completions" # Assuming standard format

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


async def call_clean_api(messages, tools=None):
    """Fallback to Clean APIs if Groq fails"""
    headers = {
        "Authorization": f"Bearer {CLEAN_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-3.5-turbo", # Clean APIs typically proxies to OpenAI models
        "messages": messages
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CLEAN_API_URL, headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]
                else:
                    log.error(f"Clean API Error {resp.status}: {await resp.text()}")
                    return None
    except Exception as e:
        log.error(f"Clean API Exception: {e}")
        return None


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

    # 1. Try Groq
    if groq_client:
        try:
            response = groq_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.1,
            )
            msg = response.choices[0].message
            if msg.tool_calls:
                available_functions = {"get_ready_whatsapp_lines": get_ready_whatsapp_lines}
                messages.append(msg)
                for tc in msg.tool_calls:
                    fn = tc.function.name
                    if fn in available_functions:
                        fn_resp = available_functions[fn]()
                        messages.append({"tool_call_id": tc.id, "role": "tool", "name": fn, "content": fn_resp})
                
                second = groq_client.chat.completions.create(model=MODEL, messages=messages, temperature=0.1)
                final = second.choices[0].message.content
                clean = final.replace("```json", "").replace("```", "").strip()
                decision = json.loads(clean)
                return decision.get("rent_id"), decision.get("reason")
        except Exception as e:
            log.warning(f"Groq failed, falling back to Clean APIs: {e}")
    
    # 2. Try Clean APIs (Fallback)
    msg = await call_clean_api(messages, tools=tools)
    if msg and msg.get("tool_calls"):
        available_functions = {"get_ready_whatsapp_lines": get_ready_whatsapp_lines}
        messages.append(msg)
        for tc in msg["tool_calls"]:
            fn = tc["function"]["name"]
            if fn in available_functions:
                fn_resp = available_functions[fn]()
                messages.append({"tool_call_id": tc["id"], "role": "tool", "name": fn, "content": fn_resp})
        
        second = await call_clean_api(messages)
        if second and second.get("content"):
            final = second["content"]
            clean = final.replace("```json", "").replace("```", "").strip()
            decision = json.loads(clean)
            return decision.get("rent_id"), decision.get("reason")

    return None, "❌ AI APIs (Groq/Clean) failed to select number."


async def chat_with_ai_owner(user_msg):
    messages = [
        {"role": "system", "content": "You are a technical coding assistant for a Telegram Bot Owner. Keep answers short and in Hinglish."},
        {"role": "user", "content": user_msg}
    ]
    
    # Try Groq
    if groq_client:
        try:
            response = groq_client.chat.completions.create(model=MODEL, messages=messages, temperature=0.5)
            return response.choices[0].message.content
        except Exception as e:
            log.warning(f"Groq chat failed: {e}")
            
    # Try Clean APIs
    msg = await call_clean_api(messages)
    if msg and msg.get("content"):
        return msg["content"]
        
    return "AI Error: Dono APIs fail ho gayi."
