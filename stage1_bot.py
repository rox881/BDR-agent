import os
import re
import logging
from dotenv import load_dotenv
from pydantic import BaseModel
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# 1. Input Data Schema (Confirmed contract for Stage 2 LangGraph state)
class LeadQuery(BaseModel):
    company: str
    city: str


# 2. Input Normalizer (Extracts Company + City from natural text or commands)
def parse_lead_input(raw_text: str) -> LeadQuery | None:
    # Strip optional '/find' prefix and common filler phrases
    cleaned = re.sub(r"^/find\s*", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"^(find\s+(event\s+)?leads\s+for\s+)", "", cleaned, flags=re.IGNORECASE)

    # Match "<Company> in <City>"
    match = re.match(r"^(?P<company>.+?)\s+in\s+(?P<city>.+)$", cleaned, flags=re.IGNORECASE)
    if not match:
        return None

    return LeadQuery(
        company=match.group("company").strip(" .!?"),
        city=match.group("city").strip(" .!?"),
    )


# 3. Telegram Handlers
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 GoPratle BDR Agent ready.\n"
        "Send: /find Zomato in Gurgaon\n"
        "Or: Find event leads for Zomato in Gurgaon"
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
