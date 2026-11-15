import os
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from stage3_actions import get_existing_leads, log_lead_for_review, send_approved_leads, get_worksheet, send_sandbox_email


from stage1_bot import parse_lead_input, start_handler
from stage2_graph import bdr_agent
from stage3_actions import log_lead_to_sheet, send_sandbox_email, scheduled_followup_job
from stage3_actions import get_existing_leads, log_lead_to_sheet, send_sandbox_email, scheduled_followup_job

load_dotenv()
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOLLOWUP_DELAY = int(os.getenv("DEMO_FOLLOWUP_SECONDS", "15"))

# Step 1: User sends "Find event leads for Zomato in Mumbai" -> Bot asks count (1-5)
async def ask_lead_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parsed = parse_lead_input(update.message.text or "")
    if not parsed:
        await update.message.reply_text("⚠️ Use format: `Find event leads for Zomato in Mumbai`", parse_mode="Markdown")
        return

    keyboard = [[
        InlineKeyboardButton(str(i), callback_data=f"count|{parsed.company}|{parsed.city}|{i}")
        for i in range(1, 6)
    ]]
    await update.message.reply_text(
        f"🎯 Target: **{parsed.company}** in **{parsed.city}**\nHow many unique leads should I find? (1–5)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

# Step 2: Run LangGraph N times, log as PENDING_REVIEW, and route HITL approval
async def handle_count_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, company, city, count_str = query.data.split("|")
    count = int(count_str)

    await query.edit_message_text(f"🔎 Searching up to **{count}** unique lead(s) for **{company}** in **{city}**...", parse_mode="Markdown")
    existing = await asyncio.to_thread(get_existing_leads)
    found_rows = []

    for _ in range(count):
        res = await asyncio.to_thread(
            bdr_agent.invoke,
            {"company": company, "city": city, "existing_leads": list(existing), "retries": 0},
        )
        if res["lead_name"] == "NOT_FOUND" or res["lead_name"].strip().lower() in existing:
            break
        row_idx = await asyncio.to_thread(log_lead_for_review, res)
        existing.add(res["lead_name"].strip().lower())
        found_rows.append((row_idx, res))

    if not found_rows:
        await query.edit_message_text(f"ℹ️ No new unique leads found for **{company}** in **{city}**.", parse_mode="Markdown")
        return

    # Single Lead -> Telegram Inline Button Review
    if count == 1:
        row_idx, lead = found_rows[0]
        approve_kb = [[
            InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve|{row_idx}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject|{row_idx}"),
        ]]
        await query.edit_message_text(
            f"📝 **Human Review Required (Row {row_idx})**\n\n"
            f"👤 **Lead:** {lead['lead_name']} ({lead['lead_role']})\n"
            f"🔗 **Profile:** {lead['profile_url']}\n"
            f"📧 **Email:** {lead['email']}\n"
            f"📞 **Phone:** {lead['phone_number']}\n"
            f"⭐ **Score:** {lead['qualification_score']}/10\n\n"
            f"💬 **Draft Pitch:**\n{lead['pitch']}",
            reply_markup=InlineKeyboardMarkup(approve_kb),
            parse_mode="Markdown",
        )
    # Multiple Leads (2-5) -> Sheet-Level Review
    else:
        summary = "\n".join([f"• Row {r}: **{l['lead_name']}** ({l['lead_role']}) — Email: `{l['email']}`" for r, l in found_rows])
        await query.edit_message_text(
            f"📊 **Logged {len(found_rows)} Lead(s) for Sheet-Level Review**\n\n{summary}\n\n"
            f"👉 **Next Step:** Open your Google Sheet (`GoPratle_BDR_Leads`), review/edit the pitches, change `Status` from `PENDING_REVIEW` to `APPROVED`, then send `/send_approved` here.",
            parse_mode="Markdown",
        )

# Step 3A: Single-lead Telegram button callback
async def handle_single_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, row_str = query.data.split("|")
    row_idx = int(row_str)
    ws = await asyncio.to_thread(get_worksheet)

    if action == "reject":
        await asyncio.to_thread(ws.update_cell, row_idx, 11, "REJECTED")
        await query.edit_message_text(f"❌ Row {row_idx} marked as `REJECTED`. No email sent.", parse_mode="Markdown")
        return

    await asyncio.to_thread(ws.update_cell, row_idx, 11, "APPROVED")
    dispatched = await asyncio.to_thread(send_approved_leads)
    await query.edit_message_text(f"🚀 **Approved & Dispatched!**\n" + "\n".join(dispatched), parse_mode="Markdown")

# Step 3B: Batch Sheet approval command (/send_approved)
async def send_approved_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dispatched = await asyncio.to_thread(send_approved_leads)
    if not dispatched:
        await update.message.reply_text("ℹ️ No rows marked `APPROVED` in Google Sheets.")
        return
    await update.message.reply_text("🚀 **Dispatched Approved Leads:**\n" + "\n".join(dispatched), parse_mode="Markdown")    


def main() -> None:
    if not TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN in .env")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("find", ask_lead_count))
    app.add_handler(CommandHandler("send_approved", send_approved_command))
    app.add_handler(CallbackQueryHandler(handle_count_selection, pattern=r"^count\|"))
    app.add_handler(CallbackQueryHandler(handle_single_approval, pattern=r"^(approve|reject)\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_lead_count))

    logging.info("🚀 GoPratle End-to-End BDR Agent is LIVE...")
    app.run_polling()


if __name__ == "__main__":
    main()