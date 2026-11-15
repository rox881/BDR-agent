# 🛠️ Setup, Configuration & Troubleshooting Guide

## 1. Local Environment Setup (Windows PowerShell)

```powershell
# 1. Clone repository and navigate to project root
cd C:\Users\Gaurav\OneDrive\Documents\BDR_agent

# 2. Create and activate virtual environment
python -m venv tvenv
.\tvenv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt
```

### Required Packages (`requirements.txt`)

```text
python-telegram-bot[job-queue]>=22.0
python-dotenv
pydantic
langgraph
langchain-google-genai
langchain-groq
langchain-tavily
gspread
```

---

## 2. Environment Variables (`.env`)

Create a `.env` file in the root directory with the following keys:

```env
# 1. Telegram Bot (via @BotFather)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# 2. Web Search API ([https://tavily.com](https://tavily.com))
TAVILY_API_KEY=your_tavily_api_key

# 3. Dual Gemini API Keys (Splits RPM/TPM quota across nodes)
GEMINI_EXTRACTION_KEY=your_first_gemini_api_key
GEMINI_PITCH_KEY=your_second_gemini_api_key

# 4. Lightweight Model Configuration
GEMINI_EXTRACTION_MODEL=gemini-3.5-flash-lite
GEMINI_PITCH_MODEL=gemini-3.5-flash-lite

# 5. Automatic Failover LLM ([https://console.groq.com](https://console.groq.com))
GROQ_API_KEY=your_groq_api_key

# 6. Outbound Email / Sandbox Config (Optional override)
SMTP_EMAIL=your_sender_gmail@gmail.com
SMTP_APP_PASSWORD=your_16_char_google_app_password
TEST_RECIPIENT=your_test_inbox@gmail.com
```

---

## 3. Google Sheets & Service Account Setup

1. **Google Cloud Console:**
   - Enable the **Google Sheets API** and **Google Drive API**.
   - Create a Service Account, generate a JSON key, and save it in the project root as `credentials.json` (or the filename configured in `stage3_actions.py`).
2. **Spreadsheet Setup:**
   - Create a Google Sheet named **`GoPratle_BDR_Leads`**.
   - Copy the `client_email` address from your Service Account JSON and **Share** the sheet with that email as **Editor**.
   - Set **Row 1** headers to:
     `Company | City | Lead Name | Role | profile_url | Email | phone_number | Score | 3-Line Pitch | Follow-up Copy | Status | Follow-UP At`

---

## 4. Root-Cause Troubleshooting Reference

| Error / Symptom                                                                      | Root Cause                                                                                                                                    | Fix Applied                                                                                                                                                          |
| :----------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`KeyError: 'profile_url'`** in `stage3_actions.py`                       | Schema mismatch between `stage2_graph.py` output keys and `log_lead_for_review()`.                                                        | Updated `AgentState` and `LeadEvaluation` to output `profile_url`, `email`, and `phone_number`, and used safe `.get()` lookups in `stage3_actions.py`. |
| **`AttributeError: 'LeadEvaluation' object has no attribute 'profile_url'`** | `extract_and_qualify()` referenced `result.profile_url` before `class LeadEvaluation(BaseModel)` was updated.                           | Added `profile_url`, `email`, and `phone_number` fields directly to `LeadEvaluation`.                                                                        |
| **`groq.BadRequestError: 400 - tool_use_failed`**                            | When all candidates in search snippets were already contacted, the LLM replied in plain text instead of calling the forced JSON tool.         | Wrapped `structured_extractor.invoke()` in `try...except` inside `extract_and_qualify()` to safely return `lead_name = "NOT_FOUND"`.                         |
| **`NameError: name 'exclusions' is not defined`**                            | Leftover `{exclusions}` variable in `search_lead()` query f-strings after removing negative name filters.                                 | Removed `{exclusions}` from all 4 source query strings and delegated deduplication to `get_existing_leads(company)`.                                             |
| **`NameError: name 'Field' / 'Optional' is not defined`**                    | Missing imports in `stage1_bot.py` after adding the `LeadQuery` Pydantic schema.                                                          | Added `from typing import Optional` and `from pydantic import BaseModel, Field` at the top of `stage1_bot.py`.                                                 |
| **New company search returns `"No new unique leads found"`**                 | 1) Global deduplication injected previous companies' leads into new searches.2) Strict quotes failed on brand aliases (`TCS`, `Bikaner`). | 1) Scoped `get_existing_leads(company)` to filter by Column A (`Company`).2) Added brand-alias matching and `<Company> Management Desk` fallback.              |
| **Casual input rejected (`⚠️ Use format...`)**                             | Strict regex required exact `"for <Company> in <City>"` prepositions.                                                                       | Implemented 2-tier hybrid parser in `stage1_bot.py` (0-token Regex + `gemini-3.5-flash-lite` structured fallback).                                               |
| **`telegram.error.NetworkError: httpx.ConnectError`**                        | Transient local Wi-Fi/TLS drop during `await query.answer()` button acknowledgment.                                                         | Wrapped `await query.answer()` in `try...except Exception: pass` inside `main.py`.                                                                             |
| **`UserWarning: gemini-3.5-flash-lite uses fixed sampling defaults`**        | Passing `temperature` parameter to `gemini-3.5-flash-lite`.                                                                               | Safe warning; remove `temperature` parameter from `ChatGoogleGenerativeAI` initialization if you want clean console logs.                                        |
