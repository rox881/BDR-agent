import os
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from stage1_bot import parse_lead_input, start_handler
from stage2_graph import bdr_agent
from stage3_actions import log_lead_to_sheet, send_sandbox_email, scheduled_followup_job
from stage3_actions import get_existing_leads, log_lead_to_sheet, send_sandbox_email, scheduled_followup_job

load_dotenv()
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOLLOWUP_DELAY = int(os.getenv("DEMO_FOLLOWUP_SECONDS", "15"))


async def run_full_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text or ""
    parsed = parse_lead_input(user_text)

    if not parsed:
        await update.message.reply_text(
            "⚠️ Format error. Try: `Find event leads for Zomato in Gurgaon`",
            parse_mode="Markdown",
        )
        return

    status_msg = await update.message.reply_text(
        f"🔎 Searching & qualifying event leads for **{parsed.company}** in **{parsed.city}**...",
        parse_mode="Markdown",
    )

    # Inside run_full_pipeline() in main.py:
    existing_leads = await asyncio.to_thread(get_existing_leads)

    result = await asyncio.to_thread(
        bdr_agent.invoke,
        {
            "company": parsed.company,
            "city": parsed.city,
            "existing_leads": list(existing_leads),
            "retries": 0,
        },
    )

    is_still_duplicate = (
        result["lead_name"] == "NOT_FOUND"
        or result["lead_name"].strip().lower() in existing_leads
        or result["contact_info"].strip().rstrip("/").lower() in existing_leads
    )

    if is_still_duplicate:
        await status_msg.edit_text(
            f"ℹ️ No **new unique** event leads found for **{parsed.company}** in **{parsed.city}** "
            f"(all discovered contacts are already logged in your Google Sheet).",
            parse_mode="Markdown",
        )
        return

    # 1. Run Stage 2 LangGraph Agent (in a thread so async bot stays responsive)
    result = await asyncio.to_thread(
        bdr_agent.invoke,
        {"company": parsed.company, "city": parsed.city, "retries": 0},
    )

    # 2. Send Initial Outreach Email (Sandbox)
    email_sent = await asyncio.to_thread(
        send_sandbox_email,
        f"Partnering with {parsed.company} for upcoming events",
        result["pitch"],
    )

    # 3. Log Lead & Pitch to Google Sheets
    followup_eta = (datetime.now() + timedelta(seconds=FOLLOWUP_DELAY)).strftime("%Y-%m-%d %H:%M:%S")
    row_idx = await asyncio.to_thread(log_lead_to_sheet, result, followup_eta)

    # 4. Schedule Automated Follow-Up via JobQueue
    context.job_queue.run_once(
        scheduled_followup_job,
        when=FOLLOWUP_DELAY,
        chat_id=update.effective_chat.id,
        data={
            "chat_id": update.effective_chat.id,
            "row_idx": row_idx,
            "lead_name": result["lead_name"],
            "company": parsed.company,
            "follow_up": result["follow_up"],
        },
    )

    # 5. Send Full Summary Card back to Telegram
    channel_status = "Email + Telegram" if email_sent else "Telegram Sandbox"
    await status_msg.edit_text(
        f"✅ **BDR Pipeline Complete!**\n\n"
        f"👤 **Lead:** {result['lead_name']} — _{result['lead_role']}_\n"
        f"🔗 **Profile:** {result['contact_info']}\n"
        f"⭐ **Fit Score:** {result['qualification_score']}/10\n"
        f"📊 **Google Sheet:** Logged at Row `{row_idx}`\n"
        f"📤 **Outreach Sent via:** {channel_status}\n\n"
        f"💬 **3-Line GoPratle Pitch:**\n{result['pitch']}\n\n"
        f"⏳ _Follow-up scheduled in {FOLLOWUP_DELAY}s..._",
        parse_mode="Markdown",
    )
    


def main() -> None:
    if not TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN in .env")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("find", run_full_pipeline))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, run_full_pipeline))

    logging.info("🚀 GoPratle End-to-End BDR Agent is LIVE...")
    app.run_polling()


if __name__ == "__main__":
    main()