import os
import re
import logging
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import ContextTypes
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from typing import Optional
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# 1. Input Data Schema (Confirmed contract for Stage 2 LangGraph state)
class LeadQuery(BaseModel):
    company: str = Field(description="Clean company or venue name (e.g., 'Capgemini'), or 'INVALID'")
    city: str = Field(description="Target city (e.g., 'Mumbai'), or 'India' if not mentioned")
    is_valid: bool = Field(description="True only if a real company/organization is mentioned")

_extractor_llm = ChatGoogleGenerativeAI(
    model=os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-3.5-flash-lite"),
    api_key=os.getenv("GEMINI_EXTRACTION_KEY"),
    max_retries=1,
).with_structured_output(LeadQuery).with_fallbacks(
    [ChatGroq(model="llama-3.3-70b-versatile", temperature=0).with_structured_output(LeadQuery)]
)

# 2. Input Normalizer (Extracts Company + City from natural text or commands)
def parse_lead_input(text: str) -> Optional[LeadQuery]:
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 3:
        return None

    # Step 1: Fast-path Regex (0 tokens) for "for Zomato in Mumbai"
    match = re.search(r"(?:for|at)\s+([A-Za-z0-9&.\-\s]+?)\s+in\s+([A-Za-z\s]+)$", cleaned, re.IGNORECASE)
    if match:
        return LeadQuery(company=match.group(1).strip(), city=match.group(2).strip().title(), is_valid=True)

    # Step 2: LLM Fallback (~50 tokens) for "Capgemini event leads mumbai" or "Zomato Gurgaon"
    try:
        prompt = (
            f"Extract the company name and city from: '{cleaned}'. "
            "Ignore filler words like 'event leads', 'find', 'representatives'. "
            "If no company is mentioned (e.g., 'hi' or 'help'), set is_valid=False."
        )
        parsed: LeadQuery = _extractor_llm.invoke(prompt)
        if parsed.is_valid and parsed.company.upper() != "INVALID":
            return parsed
    except Exception as e:
        print(f"⚠️ Input parser fallback error: {e}")

    return None

# 3. Telegram Handlers
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 **GoPratle BDR Lead Agent Ready!**\n\n"
        "Send any company and city naturally—for example:\n"
        "• `Capgemini event leads Mumbai`\n"
        "• `Zomato Gurgaon`\n"
        "• `Find event leads for Swiggy in Pune`\n\n"
        "Command: `/send_approved` (dispatch Sheet-approved leads)",
        parse_mode="Markdown",
    )


async def lead_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text or ""
    parsed = parse_lead_input(user_text)

    if not parsed:
        await update.message.reply_text(
            "⚠️ Could not extract Company and City.\n"
            "Please use the format: `Find event leads for <Company> in <City>`",
            parse_mode="Markdown",
        )
        return

    # Stage 2 hook: Later we will pass `parsed.model_dump()` into LangGraph here
    await update.message.reply_text(
        f"✅ **Input Normalized:**\n```json\n{parsed.model_dump_json(indent=2)}\n```\n"
        "Ready to trigger LangGraph pipeline.",
        parse_mode="Markdown",
    )


def main() -> None:
    if not TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN in .env")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("find", lead_request_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lead_request_handler))

    logging.info("Bot polling started...")
    app.run_polling()


if __name__ == "__main__":
    main()
