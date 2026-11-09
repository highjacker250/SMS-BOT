# services/ai_brain.py
import json
import logging
from groq import Groq
import database as db
import config

log = logging.getLogger("AIBrain")

# 🚨 Groq PRIMARY (OpenAI hata diya)
groq_client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None
MODEL = "llama-3.3-70b-versatile"  # fast + smart, free tier pe available


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


async def get_best_number_with_ai(service_type="whatsapp"):
    if not groq_client:
        return None, "❌ GROQ_API_KEY missing."

    system_prompt = (
        "You are an expert backend AI for a Telegram OTP Bot. "
        "Your job is to select the BEST number for the user. "
        "Call tool `get_ready_whatsapp_lines` to fetch the list. "
        "Analyze health, battery, chance. Return exactly ONE best `rent_id`. "
        "Output must be pure JSON: {\"rent_id\": \"...\", \"reason\": \"...\"}. No extra text."
    )

    try:
        response = groq_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Find the best {service_type} number."},
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.1,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return None, "AI ne tool call nahi kiya."

        available_functions = {"get_ready_whatsapp_lines": get_ready_whatsapp_lines}
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Find the best {service_type} number."},
            msg,
        ]

        for tc in msg.tool_calls:
            fn = tc.function.name
            if fn in available_functions:
                fn_resp = available_functions[fn]()
                messages.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "name": fn,
                    "content": fn_resp,
                })

        second = groq_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.1,
        )
        final = second.choices[0].message.content
        try:
            clean = final.replace("```json", "").replace("```", "").strip()
            decision = json.loads(clean)
            return decision.get("rent_id"), decision.get("reason")
        except json.JSONDecodeError:
            return None, f"AI ne galat format bheja: {final}"

    except Exception as e:
        log.error(f"Groq AI Error: {e}")
        return None, f"AI Error: {str(e)}"


async def chat_with_ai_owner(user_msg):
    if not groq_client:
        return "❌ GROQ_API_KEY missing."
    try:
        response = groq_client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful coding and system architecture assistant for the Owner "
                        "of a Telegram OTP Bot. Keep answers short, technical, in Hinglish. "
                        "Suggest improvements for bot features."
                    ),
                },
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Error: {e}"
