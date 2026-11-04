import os
import json
import logging
from groq import Groq
import database as db
from datetime import datetime

log = logging.getLogger("AIBrain")

# 🚨 Config se API key load kar rahe hain
import config
client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None

# --- TOOLS JO AI USE KAREGA ---
def get_ready_whatsapp_lines():
    """AI is tool ko call karega jab usko WhatsApp lines chahiye hongi."""
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

# Available tools ka schema
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_ready_whatsapp_lines",
            "description": "Returns a list of all currently available WhatsApp verification lines with their real-time health, battery, and OTP chance.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

async def get_best_number_with_ai(service_type="whatsapp"):
    if not client:
        return None, "❌ AI API Key nahi mili. Please set GROQ_API_KEY in environment."

    system_prompt = (
        "You are an expert backend AI Agent for a Telegram OTP Bot. "
        "Your job is to select the absolute BEST number for the user. "
        "You have a tool `get_ready_whatsapp_lines` which gives you the list of available numbers. "
        "Call this tool, analyze the data (look for high health, high battery, and high chance), and return exactly ONE best `rent_id`. "
        "Output must be pure JSON with keys: `rent_id`, `reason`. Do not add any extra text."
    )

    try:
        # Step 1: AI ko message bhejte hain aur tool call trigger karte hain
        response = client.chat.completions.create(
            model="llama3-70b-8192", # Groq ka smartest free model
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

        # Step 2: Agar AI ne tool call kiya, toh hum data fetch karke wapas bhejte hain
        if tool_calls:
            available_functions = {
                "get_ready_whatsapp_lines": get_ready_whatsapp_lines,
            }
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

            # Step 3: AI ko data wapas de rahe hain, taaki wo final decision de
            second_response = client.chat.completions.create(
                model="llama3-70b-8192",
                messages=messages,
                temperature=0.1
            )
            
            final_answer = second_response.choices[0].message.content
            log.info(f"AI Decision: {final_answer}")

            try:
                # Clean up markdown backticks if AI sends them
                clean_json = final_answer.replace("```json", "").replace("```", "").strip()
                decision = json.loads(clean_json)
                return decision.get("rent_id"), decision.get("reason")
            except json.JSONDecodeError:
                return None, f"AI ne galat format bheja: {final_answer}"

        return None, "AI ne koi number select nahi kiya."
    except Exception as e:
        log.error(f"AI Brain Error: {e}")
        return None, f"AI Error: {str(e)}"
