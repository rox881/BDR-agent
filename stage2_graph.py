import os
from typing import TypedDict, Literal, cast
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, START, END

load_dotenv()


# 1. Shared Graph State
class AgentState(TypedDict):
    company: str
    city: str
    existing_leads: list[str]
    source_index: int          # Tracks which lead source (0..3) to query
    raw_results: list[dict]
    lead_name: str
    lead_role: str
    profile_url: str
    email: str
    phone_number: str
    qualification_score: int
    qualification_reason: str
    pitch: str
    follow_up: str
    retries: int


# 2. Pydantic Schemas
class LeadEvaluation(BaseModel):
    lead_name: str = Field(description="Full name of decision-maker, or 'NOT_FOUND'")
    lead_role: str = Field(description="Job title (e.g., Head of Events, HR Manager, Founder)")
    profile_url: str = Field(description="Source profile/page URL, or 'Not publicly mentioned'")
    email: str = Field(description="Public email if explicitly in snippets, else 'Not publicly mentioned'")
    phone_number: str = Field(description="Public phone number if explicitly in snippets, else 'Not publicly mentioned'")
    qualification_score: int = Field(description="Fit score from 1 to 10")
    qualification_reason: str = Field(description="One-line score reason")


class OutreachCopy(BaseModel):
    pitch: str = Field(description="Strictly 3-line personalized GoPratle pitch")
    follow_up: str = Field(description="Polite 2-line follow-up message for 3 days later")


# 3. Tools & Dual-Key LLM Setup (with automatic Groq fallback)
search_tool = TavilySearch(
    max_results=5,
    search_depth="basic",
    include_raw_content=False,  # Token optimization: prevents massive HTML/markdown payloads
)

extractor_primary = ChatGoogleGenerativeAI(
    model=os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-3.5-flash-lite"),
    api_key=os.getenv("GEMINI_EXTRACTION_KEY"),
    temperature=0.0,
    max_retries=2,
)

pitch_primary = ChatGoogleGenerativeAI(
    model=os.getenv("GEMINI_PITCH_MODEL", "gemini-3.5-flash-lite"),
    api_key=os.getenv("GEMINI_PITCH_KEY"),
    max_output_tokens=250,
    temperature=0.3,
    max_retries=2,
)

groq_fallback = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2, max_retries=2)

structured_extractor = extractor_primary.with_structured_output(LeadEvaluation).with_fallbacks(
    [groq_fallback.with_structured_output(LeadEvaluation)]
)
structured_writer = pitch_primary.with_structured_output(OutreachCopy).with_fallbacks(
    [groq_fallback.with_structured_output(OutreachCopy)]
)


# Token Optimizer: Strips Tavily noise and caps snippet size at 300 chars
def prune_search_results(raw_results: list[dict]) -> list[dict]:
    pruned = []
    for item in raw_results[:5]:
        if isinstance(item, dict):
            pruned.append({
                "title": item.get("title", "")[:120],
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:300],
            })
    return pruned


# 4. Node 1: Multi-Source Lead Search (LinkedIn -> Social -> Maps/Directories -> Event PR)
def search_lead(state: AgentState) -> dict:
    retries = state.get("retries", 0)
    idx = (state.get("source_index", 0) + retries) % 4
    company = state["company"]
    city = state["city"]

    sources = [
        ("LinkedIn Profiles", f'site:linkedin.com/in "{company}" {city} Events OR HR OR Admin OR Marketing OR Manager'),
        ("LinkedIn & Web", f'"{company}" {city} linkedin Manager OR Director OR Head OR Founder OR Operations'),
        ("Maps & Directories", f'"{company}" {city} contact email phone manager banquet events'),
        ("Event & PR Mentions", f'"{company}" {city} event launch corporate hospitality manager'),
    ]

    source_name, query = sources[idx]
    print(f"🔍 [Node: search_lead | Source: {source_name} | Attempt {retries + 1}] Query: {query}")

    response = search_tool.invoke({"query": query})
    raw = response.get("results", response) if isinstance(response, dict) else response
    pruned = prune_search_results(raw)
    print(f"📄 [Tavily] Retrieved {len(pruned)} snippets")
    return {"raw_results": pruned, "retries": retries + 1}

# 5. Node 2: Extract Profile, Email, Phone & Score (Uses Gemini Key 1)
def extract_and_qualify(state: AgentState) -> dict:
    print("🧠 [Node: extract_and_qualify] Evaluating pruned snippets with Gemini Extractor...")
    recent_names = [x for x in state.get("existing_leads", []) if not x.startswith("http")][-15:]

    prompt = f"""
    Target Company: {state['company']} | City: {state['city']}
    ALREADY CONTACTED (DO NOT PICK): {recent_names}
    Search Snippets: {state['raw_results']}

    Task: Pick the single best NEW lead from the snippets.
    Rules:
    1. Match common brand aliases/abbreviations (e.g., 'TCS' = 'Tata Consultancy Services', 'Bikaner' = 'Bikanervala').
    2. Priority: Events/Banquet > Workplace/Admin > Marketing/Brand > HR > Operations/General Manager > Founder.
    3. FALLBACK: If snippets show the target company/venue directory page (e.g., Justdial/website) but no individual person's name is listed, set lead_name to "{state['company']} Management Desk", lead_role to "Venue / Operations Manager", and qualification_score to 6 (so we still capture their contact/URL).
    4. Only set lead_name to "NOT_FOUND" if the snippets are completely unrelated or already in ALREADY CONTACTED.
    5. Extract email and phone_number ONLY if explicitly in the snippets; otherwise output: "Not publicly mentioned".
    """
    try:
        result = cast(LeadEvaluation, structured_extractor.invoke(prompt))
        print(
            f"🎯 [Gemini Decision] Lead: {result.lead_name} ({result.lead_role}) | "
            f"Score: {result.qualification_score}/10 | Reason: {result.qualification_reason}"
        )
        return {
            "lead_name": result.lead_name,
            "lead_role": result.lead_role,
            "profile_url": result.profile_url,
            "email": result.email,
            "phone_number": result.phone_number,
            "qualification_score": result.qualification_score,
            "qualification_reason": result.qualification_reason,
        }
    except Exception as e:
        print(f"⚠️ Extractor fallback triggered ({e}) -> Marking NOT_FOUND.")
        return {
            "lead_name": "NOT_FOUND",
            "lead_role": "N/A",
            "profile_url": "Not publicly mentioned",
            "email": "Not publicly mentioned",
            "phone_number": "Not publicly mentioned",
            "qualification_score": 0,
            "qualification_reason": "No valid uncontacted candidate extracted.",
        }

# 6. Conditional Router: Rotates up to 3 different sources per lead search
def route_after_qualification(state: AgentState) -> Literal["search_lead", "generate_pitch"]:
    existing = set(state.get("existing_leads", []))
    is_duplicate = (
        state["lead_name"].strip().lower() in existing
        or state.get("profile_url", "").strip().rstrip("/").lower() in existing
    )
    if (state["lead_name"] == "NOT_FOUND" or is_duplicate or state["qualification_score"] < 5) and state["retries"] < 3:
        print("🔄 [Router] Missing/duplicate/weak lead -> Rotating to next lead source...")
        return "search_lead"
    return "generate_pitch"


# 7. Node 3: Generate Tailored 3-Line Pitch (Uses Gemini Key 2)
def generate_pitch(state: AgentState) -> dict:
    if state["lead_name"] == "NOT_FOUND":
        return {"pitch": "", "follow_up": ""}

    print("✍️ [Node: generate_pitch] Writing GoPratle pitch with Gemini Pro...")
    prompt = f"""
    Write outreach copy for GoPratle (marketplace connecting event hosts with vetted planners, DJs, and crew).
    Lead: {state['lead_name']} ({state['lead_role']}) at {state['company']} in {state['city']}.

    Rules:
    - 'pitch': Strictly 3 lines (Line 1: personalized hook; Line 2: GoPratle value; Line 3: low-friction question).
    - 'follow_up': Strictly 2 lines to send 3 days later if no reply.
    """
    copy = cast(OutreachCopy, structured_writer.invoke(prompt))
    return {"pitch": copy.pitch, "follow_up": copy.follow_up}


# 8. Compile Graph
def build_bdr_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("search_lead", search_lead)
    workflow.add_node("extract_and_qualify", extract_and_qualify)
    workflow.add_node("generate_pitch", generate_pitch)

    workflow.add_edge(START, "search_lead")
    workflow.add_edge("search_lead", "extract_and_qualify")
    workflow.add_conditional_edges("extract_and_qualify", route_after_qualification)
    workflow.add_edge("generate_pitch", END)

    return workflow.compile()


bdr_agent = build_bdr_graph()