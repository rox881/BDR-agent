
# 🚀 AI BDR Lead Enrichment & Outreach Agent

An autonomous, Human-in-the-Loop (HITL) Business Development Representative (BDR) agent built with **LangGraph**, **Gemini 3.5 Flash-Lite**, **Groq**, **Tavily**, **Google Sheets**, and **Telegram**.

The agent discovers event and corporate decision-makers across 4 web channels, qualifies leads, drafts personalized 3-line outreach pitches, and enforces human review before dispatching emails.

---

>
> ## 🎥 Live Demo
>
> <p align="center">
>   <a href="http://www.youtube.com/watch?v=6LRc3wePvQs" target="_blank">
>     <img src="https://i.ytimg.com/vi/6LRc3wePvQs/hqdefault.jpg" alt="End-to-End AI Sales & Lead Gen Agent Demo" width="720" />
>   </a>
> </p>
>
> <p align="center">
>   ▶️ <a href="http://www.youtube.com/watch?v=6LRc3wePvQs" target="_blank"><strong>Watch the full walkthrough on YouTube</strong></a>
> </p>

---

## ✨ Key Features

- **Resilient Hybrid Input Parser:** Understands both structured commands (`Find event leads for Zomato in Mumbai`) and natural phrasing (`Capgemini event leads Mumbai`) using a 0-token Regex fast-path + Gemini LLM fallback.
- **4-Source Search Rotation:** Automatically rotates queries across LinkedIn Profiles, LinkedIn/Web, Maps & Business Directories (Justdial/IndiaMART), and Event Press/PR.
- **Company-Scoped Deduplication:** Prevents contacting the same person twice within a company while allowing fresh searches across new companies.
- **Adaptive Human-in-the-Loop (HITL) Review:**
  - **1 Lead:** Instant 1-click `[ ✅ Approve & Send ]` / `[ ❌ Reject ]` buttons inside Telegram.
  - **2–5 Leads (Batch):** Logs drafts to Google Sheets as `PENDING_REVIEW` for bulk editing and dispatches approved rows via `/send_approved`.
- **Dual-Key Token Optimization:** Splits extraction and pitch generation across two Gemini API keys with automatic Groq (`llama-3.3-70b-versatile`) failover and 65% Tavily snippet pruning.

---

## 📚 Detailed Documentation (`docs/`)

| Document                                                                             | Description                                                                          |
| :----------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------- |
| [**01. System Architecture**](./docs/01_architecture.md)                        | 3-stage pipeline design, LangGraph state machine, and module responsibilities.       |
| [**02. HITL Workflow & Sheet Schema**](./docs/02_hitl_and_database.md)          | Single vs. batch approval flow and the 12-column Google Sheets CRM structure.        |
| [**03. Token Optimization & Search**](./docs/03_optimization_and_resilience.md) | Stage-by-stage token usage, payload pruning, dual-key setup, and venue fallbacks.    |
| [**04. Setup & Troubleshooting**](./docs/04_setup_and_troubleshooting.md)       | Installation, `.env` configuration, Google Service Account setup, and error fixes. |

---

## ⚡ Quick Start

```powershell
# 1. Activate virtual environment & install dependencies
.\tvenv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Run the Telegram BDR Agent
python -u main.py
```
