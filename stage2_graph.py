import os
from typing import TypedDict, Literal ,cast
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, START, END

load_dotenv()

# 1. Shared Graph State (The clipboard passed between all nodes)
class AgentState(TypedDict,total=False):
    company: str
    city: str
    raw_results: list[dict]
    lead_name: str
    lead_role: str
    contact_info: str
    qualification_score: int
    qualification_reason: str
    pitch: str
    follow_up: str
    retries: int

# 2. Pydantic Schemas (Enforces strict JSON output from Groq)
class LeadEvaluation(BaseModel):
    lead_name: str = Field(description="Full name of the best decision-maker, or 'NOT_FOUND'")
    lead_role: str = Field(description="Job title (e.g., Head of Events, HR Manager, Founder)")
    contact_info: str = Field(description="LinkedIn profile URL or email found in search results")
    qualification_score: int = Field(description="Fit score from 1 to 10 for booking corporate events")
    qualification_reason: str = Field(description="One-line reason for the score")

class OutreachCopy(BaseModel):
    pitch: str = Field(description="Strictly 3-line personalized GoPratle pitch")
    follow_up: str = Field(description="Polite 2-line follow-up message for 3 days later")

# Initialize Tools & LLM
search_tool = TavilySearch(max_results=5, search_depth="basic")
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.2)

# 3. Node 1: Search Web & LinkedIn for Decision-Makers
def search_lead(state: AgentState) -> dict:
    retries = state.get("retries", 0)
    if retries == 0:
        query = f'site:linkedin.com/in "{state["company"]}" "{state["city"]}" ("Events" OR "Workplace" OR "HR" OR "Admin")'
    else:
        # Broader fallback query if first attempt missed
        query = f'"{state["company"]}" "{state["city"]}" ("Founder" OR "HR Head" OR "People Operations") LinkedIn'

    print(f"🔍 [Node: search_lead | Attempt {retries + 1}] Query: {query}")
    response = search_tool.invoke({"query": query})
    results = response.get("results", response) if isinstance(response, dict) else response
    return {"raw_results": results, "retries": retries + 1}

# 4. Node 2: Extract Profile & Score Lead Potential (1-10)
def extract_and_qualify(state: AgentState) -> dict:
    print("🧠 [Node: extract_and_qualify] Evaluating search snippets...")
    structured_llm = llm.with_structured_output(LeadEvaluation)
    prompt = f"""
    Target Company: {state['company']} | City: {state['city']}
    Search Results: {state['raw_results']}

    Pick the single best decision-maker for corporate events/offsites (Priority: Events > Workplace/Admin > HR > Founder).
    Score 1-10 based on: Role relevance (+4), City match (+3), Company event potential (+3).
    Never invent URLs or names not in the search results.
    """
    result = cast(LeadEvaluation, structured_llm.invoke(prompt))
    return {
        "lead_name": result.lead_name,
        "lead_role": result.lead_role,
        "contact_info": result.contact_info,
        "qualification_score": result.qualification_score,
        "qualification_reason": result.qualification_reason,
    }

# 5. Conditional Edge: Retry search once if lead is missing or weak
def route_after_qualification(state: AgentState) -> Literal["search_lead", "generate_pitch"]:
    if (state["lead_name"] == "NOT_FOUND" or state["qualification_score"] < 5) and state["retries"] < 2:
        print("🔄 [Router] Low score or missing lead -> Looping back to search_lead...")
        return "search_lead"
    return "generate_pitch"

# 6. Node 3: Generate Tailored 3-Line GoPratle Pitch + Follow-Up
def generate_pitch(state: AgentState) -> dict:
    print("✍️ [Node: generate_pitch] Writing GoPratle outreach copy...")
    structured_llm = llm.with_structured_output(OutreachCopy)
    prompt = f"""
    Write outreach copy for GoPratle (a marketplace connecting event hosts with vetted planners, DJs, and crew).
    Lead: {state['lead_name']} ({state['lead_role']}) at {state['company']} in {state['city']}.

    Rules:
    - 'pitch': Exactly 3 lines (Line 1: personalized hook; Line 2: GoPratle value; Line 3: low-friction question).
    - 'follow_up': Exactly 2 lines to send 3 days later if no reply.
    """
    copy = cast(OutreachCopy, structured_llm.invoke(prompt))
    return {"pitch": copy.pitch, "follow_up": copy.follow_up}

# 7. Assemble & Compile the Graph
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

# Standalone test block
if __name__ == "__main__":
    output = bdr_agent.invoke({"company": "Zomato", "city": "Gurgaon", "retries": 0})
    print("\n✅ FINAL GRAPH OUTPUT:")
    for key in ["lead_name", "lead_role", "contact_info", "qualification_score", "pitch", "follow_up"]:
        print(f"{key}: {output.get(key)}")