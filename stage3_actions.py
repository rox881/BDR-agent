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
        print("⚠️ Email credentials not set—skipping SMTP send.")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL.strip()
        msg["To"] = to_email.strip()
        msg.set_content(body)

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SENDER_EMAIL.strip(), SENDER_PASSWORD.replace(" ", "").strip())
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"⚠️ SMTP Email skipped ({e})—falling back to Telegram + Sheets logging.")
        return False


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

def get_existing_leads() -> set[str]:
    """Returns a lowercase set of existing Lead Names and Contact URLs from the Sheet."""
    ws = get_worksheet()
    rows = ws.get_all_values()[1:]  # Skip header row
    existing = set()
    for row in rows:
        if len(row) >= 3 and row[2].strip():
            existing.add(row[2].strip().lower())          # Lead Name
        if len(row) >= 5 and row[4].strip():
            existing.add(row[4].strip().rstrip("/").lower())  # Contact / URL
    return existing