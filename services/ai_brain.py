import os
import json
import logging
from groq import Groq
import database as db
import config

log = logging.getLogger("AIBrain")
client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None

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
            "chance": info.get("chance")
        })
    return json.dumps(result)

tools = [{
    "type": "function",
    "function": {
        "name": "get_ready_whatsapp_lines",
        "description": "Returns a list of all currently available WhatsApp verification lines with their real-time health, battery, and OTP chance.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
}]

async def get_best_number_with_ai(service_type="whatsapp"):
    if not client:
        return None, "❌ AI API Key nahi mili."
    system_prompt = (
        "You are an expert backend AI Agent for a Telegram OTP Bot. "
        "Your job is to select the absolute BEST number for the user. "
        "You have a tool `get_ready_whatsapp_lines` which gives you the list of available numbers. "
        "Call this tool, analyze the data (look for high health, high battery, and high chance), and return exactly ONE best `rent_id`. "
        "Output must be pure JSON with keys: `rent_id`, `reason`. Do not add any extra text."
    )
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant", # 🚨 NAYA MODEL
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Find the best {service_type} number for me."}
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.1
        )
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        if tool_calls:
            available_functions = {"get_ready_whatsapp_lines": get_ready_whatsapp_lines}
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Find the best {service_type} number for me."},
                response_message
            ]
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_to_call = available_functions[function_name]
                function_response = function_to_call()
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": function_response,
                })
            second_response = client.chat.completions.create(
                model="llama-3.1-8b-instant", # 🚨 NAYA MODEL
                messages=messages,
                temperature=0.1
            )
            final_answer = second_response.choices[0].message.content
            try:
                clean_json = final_answer.replace("```json", "").replace("```", "").strip()
                decision = json.loads(clean_json)
                return decision.get("rent_id"), decision.get("reason")
            except json.JSONDecodeError:
                return None, f"AI ne galat format bheja: {final_answer}"
        return None, "AI ne koi number select nahi kiya."
    except Exception as e:
        log.error(f"AI Brain Error: {e}")
        return None, f"AI Error: {str(e)}"

async def chat_with_ai_owner(user_msg):
    if not client: return "AI Key missing."
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant", # 🚨 NAYA MODEL
            messages=[
                {"role": "system", "content": "You are a helpful coding and system architecture assistant for the Owner of a Telegram OTP Bot. Keep answers short, technical, and in Hinglish. Suggest improvements for bot features."},
                {"role": "user", "content": user_msg}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Error: {e}"
