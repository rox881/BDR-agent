import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
import gspread
from dotenv import load_dotenv
from telegram.ext import ContextTypes

load_dotenv()

SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "GoPratle_BDR_Leads")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_APP_PASSWORD")
TEST_RECIPIENT = os.getenv("TEST_RECIPIENT_EMAIL")


def get_worksheet():
    gc = gspread.service_account(filename="service_account.json")
    return gc.open(SHEET_NAME).sheet1


def send_sandbox_email(subject: str, body: str, to_email: str = TEST_RECIPIENT) -> bool:
    if not (SENDER_EMAIL and SENDER_PASSWORD and to_email):
        print("⚠️ Email credentials not set—skipping SMTP send (logging only).")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp.send_message(msg)
    return True


def log_lead_to_sheet(state: dict, followup_time: str) -> int:
    """Appends lead row to Google Sheet and returns the inserted row index."""
    ws = get_worksheet()
    row = [
        state["company"],
        state["city"],
        state["lead_name"],
        state["lead_role"],
        state["contact_info"],
        f"{state['qualification_score']}/10",
        state["pitch"],
        state["follow_up"],
        "INITIAL_SENT",
        followup_time,
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return len(ws.get_all_values())


async def scheduled_followup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fires automatically after the configured delay to send the follow-up."""
    data = context.job.data
    chat_id = data["chat_id"]
    row_idx = data["row_idx"]
    lead_name = data["lead_name"]
    company = data["company"]
    follow_up_text = data["follow_up"]

    # 1. Send follow-up email (sandbox)
    send_sandbox_email(
        subject=f"Re: Event support for {company} (GoPratle)",
        body=follow_up_text,
    )

    # 2. Update Google Sheet Status column (Column 9 = Status)
    try:
        ws = get_worksheet()
        ws.update_cell(row_idx, 9, "FOLLOWUP_SENT")
    except Exception as e:
        print(f"⚠️ Sheet status update error: {e}")

    # 3. Notify you on Telegram
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏰ **Scheduled Follow-Up Triggered!**\n"
            f"👤 **Lead:** {lead_name} ({company})\n"
            f"📊 **Sheet Row {row_idx}:** Updated to `FOLLOWUP_SENT`\n\n"
            f"✉️ **Follow-Up Sent:**\n_{follow_up_text}_"
        ),
        parse_mode="Markdown",
    )