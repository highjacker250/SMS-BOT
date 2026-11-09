from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
import database as db
from utils.ui import sc, btn
from utils.helper import is_owner
from states import S
from services.ai_brain import chat_with_ai_owner

admin_router = Router()

@admin_router.callback_query(F.data == "admin:ai_chat")
async def admin_ai_chat_prompt(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    if not is_owner(cq.from_user.id): return
    await state.set_state(S.ai_chat)
    
    text = (
        f"🤖 <b>AI Assistant Mode</b>\n\n"
        f"Ask me anything about the bot's architecture, new features, or bug fixes. I will reply in Hinglish.\n\n"
        f"<i>Type your message to start...</i>"
    )
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("exit chat", "admin:home", "❌")]]), parse_mode="HTML")

@admin_router.message(S.ai_chat)
async def admin_ai_chat_reply(msg: Message, state: FSMContext):
    user_text = msg.text
    status = await msg.answer("🧠 AI is thinking... (Checking Groq, DeepSeek, Gemini...)")
    
    # 🚨 Ye naye fallback wale AI ko call karega
    reply = await chat_with_ai_owner(user_text)
    
    await status.edit_text(
        f"🤖 <b>AI Response:</b>\n\n{reply}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("ask again", "admin:ai_chat", "💬")], [btn("exit chat", "admin:home", "❌")]]),
        parse_mode="HTML"
    )
