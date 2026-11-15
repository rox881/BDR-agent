import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from stage1_bot import parse_lead_input, start_handler
from stage2_graph import bdr_agent
from stage3_actions import (
    get_existing_leads,
    log_lead_for_review,
    send_approved_leads,
    get_worksheet,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)

NEXT_INPUT_HINT = (
    "\n\n💡 Ready for your next search! Type any company & city "
    "(e.g., 'Capgemini event leads Mumbai' or 'Zomato Gurgaon')."
)


# Step 1: Parse natural input (via thread so LLM fallback never blocks) & ask count (1-5)
async def ask_lead_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text or ""
    parsed = await asyncio.to_thread(parse_lead_input, user_text)

    if not parsed:
        await update.message.reply_text(
            "⚠️ Please include a company name and city.\n"
            "Examples:\n"
            "• Capgemini event leads Mumbai\n"
            "• Zomato Gurgaon\n"
            "• Find event leads for Swiggy in Pune"
        )
        return

    keyboard = [[
        InlineKeyboardButton(str(i), callback_data=f"count|{parsed.company}|{parsed.city}|{i}")
        for i in range(1, 6)
    ]]
    await update.message.reply_text(
        f"🎯 Target: {parsed.company} in {parsed.city}\n"
        "How many unique leads should I find? (1–5)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# Step 2: Run LangGraph N times, log as PENDING_REVIEW, and route HITL approval
async def handle_count_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass  # Ignore transient network hiccups on button ack

    _, company, city, count_str = query.data.split("|")
    count = int(count_str)

    await query.edit_message_text(
        f"🔎 Searching up to {count} unique lead(s) for {company} in {city}..."
    )

    existing = await asyncio.to_thread(get_existing_leads, company)
    found_rows = []

    for i in range(count):
        try:
            await query.edit_message_text(
                f"🔎 Searching lead {i + 1}/{count} for {company} in {city} "
                f"(Found {len(found_rows)} so far)..."
            )
            res = await asyncio.to_thread(
                bdr_agent.invoke,
                {
                    "company": company,
                    "city": city,
                    "existing_leads": list(existing),
                    "source_index": i,
                    "retries": 0,
                },
            )

            if res["lead_name"] == "NOT_FOUND":
                print("ℹ️ Search pool exhausted for this company/city -> Stopping batch early.")
                break

            if res["lead_name"].strip().lower() in existing:
                continue

            row_idx = await asyncio.to_thread(log_lead_for_review, res)
            existing.add(res["lead_name"].strip().lower())
            if res.get("profile_url", "").startswith("http"):
                existing.add(res["profile_url"].strip().rstrip("/").lower())
            found_rows.append((row_idx, res))

            await asyncio.sleep(1.5)
        except Exception as e:
            print(f"⚠️ Stopped batch at iteration {i + 1}: {e}")
            break

    if not found_rows:
        await query.edit_message_text(
            f"ℹ️ No new unique leads found for {company} in {city}." + NEXT_INPUT_HINT
        )
        return

    # Single Lead (count == 1) -> Telegram 1-Click Inline Approval
    if count == 1:
        row_idx, lead = found_rows[0]
        approve_kb = [[
            InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve|{row_idx}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject|{row_idx}"),
        ]]
        await query.edit_message_text(
            f"📝 Human Review Required (Row {row_idx})\n\n"
            f"👤 Lead: {lead['lead_name']} ({lead['lead_role']})\n"
            f"🔗 Profile: {lead['profile_url']}\n"
            f"📧 Email: {lead['email']}\n"
            f"📞 Phone: {lead['phone_number']}\n"
            f"⭐ Score: {lead['qualification_score']}/10\n\n"
            f"💬 Draft Pitch:\n{lead['pitch']}",
            reply_markup=InlineKeyboardMarkup(approve_kb),
        )
    # Batch Leads (count 2-5) -> Sheet-Level Review
    else:
        summary = "\n".join(
            [
                f"• Row {r}: {l['lead_name']} ({l['lead_role']}) — Email: {l['email']}"
                for r, l in found_rows
            ]
        )
        await query.edit_message_text(
            f"📊 Logged {len(found_rows)} Lead(s) for Sheet-Level Review\n\n"
            f"{summary}\n\n"
            f"👉 Next Step: Open Google Sheets (GoPratle_BDR_Leads), review/edit pitches, "
            f"change Status from PENDING_REVIEW to APPROVED, then send /send_approved here."
            + NEXT_INPUT_HINT
        )


# Step 3A: Single-lead Telegram button callback
async def handle_single_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    action, row_str = query.data.split("|")
    row_idx = int(row_str)
    ws = await asyncio.to_thread(get_worksheet)

    if action == "reject":
        await asyncio.to_thread(ws.update_cell, row_idx, 11, "REJECTED")
        await query.edit_message_text(
            f"❌ Row {row_idx} marked as REJECTED. No email sent." + NEXT_INPUT_HINT
        )
        return

    await asyncio.to_thread(ws.update_cell, row_idx, 11, "APPROVED")
    dispatched = await asyncio.to_thread(send_approved_leads)
    await query.edit_message_text(
        "🚀 Approved & Dispatched!\n" + "\n".join(dispatched) + NEXT_INPUT_HINT
    )


# Step 3B: Batch Sheet approval command (/send_approved)
async def send_approved_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dispatched = await asyncio.to_thread(send_approved_leads)
    if not dispatched:
        await update.message.reply_text(
            "ℹ️ No rows marked APPROVED in Google Sheets." + NEXT_INPUT_HINT
        )
        return
    await update.message.reply_text(
        "🚀 Dispatched Approved Leads:\n" + "\n".join(dispatched) + NEXT_INPUT_HINT
    )


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN missing in .env")

    app = ApplicationBuilder().token(token).build()
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