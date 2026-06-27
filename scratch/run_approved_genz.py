"""Approved simulation runner for ContentOS.

Runs the Orchestrator pipeline end-to-end, simulates the HITL APPROVE response,
saves final files to output/, and writes the execution trace.
"""

import os
import sys
import time
import json
import asyncio
from unittest.mock import patch
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to sys.path
sys.path.append(os.getcwd())

# Set dummy environment variables to bypass validation
os.environ["GOOGLE_API_KEY"] = "dummy_google_api_key"
os.environ["MCP_SEARCH_API_KEY"] = "dummy_mcp_search_api_key"

from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from agents.orchestrator import orchestrator

# Gen Z Burnout Mock Data
MOCK_SOURCES = [
    {
        "title": "Deloitte 2024 Gen Z and Millennial Survey",
        "url": "https://www2.deloitte.com/global/en/pages/about-deloitte/articles/genzmillennialsurvey.html",
        "key_claims": ["Cost of living is Gen Z's top concern.", "High levels of stress and burnout persist due to workload and poor work-life balance."],
        "stats": ["40% of Gen Zs feel stressed or anxious all or most of the time.", "35% report feeling burned out due to their work environment."],
        "date": "2024-05-15"
    },
    {
        "title": "McKinsey Mental Health Index 2023",
        "url": "https://www.mckinsey.com/mgi/our-research/delivering-on-the-promise-of-employer-supported-mental-health",
        "key_claims": ["Gen Z reports the lowest mental well-being of any generation.", "Pre-career anxiety is fueled by economic instability and social media pressure."],
        "stats": ["Gen Z is 3 times more likely to report poor mental health than Baby Boomers.", "Pre-career stress affects 55% of college grads."],
        "date": "2023-10-12"
    },
    {
        "title": "American Psychological Association: Stress in America",
        "url": "https://www.apa.org/news/press/releases/stress/2023/collective-trauma-gen-z",
        "key_claims": ["Gen Z is deeply stressed about the future of the economy and career entry barriers.", "Workplace expectations are shifting rapidly, leading to mismatch anxiety."],
        "stats": ["72% of Gen Z list work and economy as significant stress sources.", "64% feel overwhelmed by career path decisions."],
        "date": "2023-11-01"
    }
]

MOCK_RESEARCH_BRIEF = {
    "topic": "why gen z is burnt out before they even start their careers",
    "sources": MOCK_SOURCES,
    "summary": "gen z is facing unprecedented stress levels before entering the workforce, driven by cost of living concerns, economic instability, and high career expectations. surveys show they report the lowest mental well-being of any generation, with over 40% feeling anxious most of the time.",
    "angles": ["The Price of Ambition", "The Pre-Career Crash", "Rethinking the 9-to-5 Dream"],
    "refine_required": False
}

MOCK_SCRIPT_PACKAGE = {
    "script": (
        "# Hook\n"
        "why are you already exhausted and you haven't even started your first real job yet? let's talk about why gen z is burnt out before the career race even begins.\n\n"
        "# Section 1: The Cost of Existing\n"
        "point one. you're entering a game where the entry price is double and the payout is halved. according to deloitte, cost of living is your top concern, and 40% of you feel anxious constantly. you aren't lazy; you're financially claustrophobic. (https://www2.deloitte.com/global/en/pages/about-deloitte/articles/genzmillennialsurvey.html)\n\n"
        "# Section 2: The Mental Mismatch\n"
        "point two. the workplace was built for boomers, but you're paying the mental tax. mckinsey reports gen z has the lowest well-being, and grads are 3x more likely to report poor mental health than older generations. the hustle culture lied. (https://www.mckinsey.com/mgi/our-research/delivering-on-the-promise-of-employer-supported-mental-health)\n\n"
        "# Section 3: Mismatch Anxiety\n"
        "point three. you're pressured to have a 10-year plan in a world that can't plan 10 days ahead. over 70% of you list the economy as a major stress source. trying to find stability in a collapse is exhausting. (https://www.apa.org/news/press/releases/stress/2023/collective-trauma-gen-z)\n\n"
        "# CTA\n"
        "are you already burnt out or just realistic? drop your thoughts below and subscribe if you're done with corporate fluff."
    ),
    "word_count": 182,
    "estimated_duration": "1-2 minutes",
    "sources_cited": [
        "https://www2.deloitte.com/global/en/pages/about-deloitte/articles/genzmillennialsurvey.html",
        "https://www.mckinsey.com/mgi/our-research/delivering-on-the-promise-of-employer-supported-mental-health",
        "https://www.apa.org/news/press/releases/stress/2023/collective-trauma-gen-z"
    ],
    "hook": "why are you already exhausted and you haven't even started your first real job yet? let's talk about why gen z is burnt out before the career race even begins."
}

MOCK_SEO_PACKAGE = {
    "titles": [
        "why gen z is burnt out before 9-to-5",
        "is gen z already too tired to work?",
        "3 reasons gen z is burnt out before day 1"
    ],
    "description": "Explaining the root causes of pre-career burnout in Gen Z, including cost of living and economic anxiety.",
    "tags": ["gen z", "burnout", "workplace stress", "career advice", "mental health"],
    "thumbnail_brief": "A split image of a graduation cap next to a battery icon showing 1% charge.",
    "chapter_markers": ["0:00 - Hook", "0:25 - Cost of Existing", "1:00 - Hustle Culture Lie", "1:35 - CTA"]
}

async def mock_generate_content_async(self, llm_request, stream=False):
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    system_instr = ""
    if hasattr(llm_request, "config") and llm_request.config and llm_request.config.system_instruction:
        instr = llm_request.config.system_instruction
        if isinstance(instr, str):
            system_instr = instr.lower()
        elif hasattr(instr, "parts"):
            system_instr = "".join(p.text for p in instr.parts if p.text).lower()

    is_research = "web_search" in system_instr or "summarizer" in system_instr
    is_script = "sibling" in system_instr or "narration" in system_instr or "scriptwriting" in system_instr
    is_review = "reviewagent" in system_instr or "request_review" in system_instr or "unverified_claims" in system_instr
    is_seo = ("seo" in system_instr or "chapter_markers" in system_instr or "titles" in system_instr) and not is_review

    if is_research:
        has_search_response = False
        for content in llm_request.contents:
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if part.function_call and part.function_call.name == "web_search":
                        pass
                    if part.function_response and part.function_response.name == "web_search":
                        has_search_response = True

        if has_search_response:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=json.dumps(MOCK_RESEARCH_BRIEF))]
                )
            )
        else:
            fc = types.FunctionCall(
                name="web_search",
                id="fc-web-search",
                args={"query": "why gen z is burnt out before they even start their careers"}
            )
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=fc)]
                )
            )

    elif is_script:
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(MOCK_SCRIPT_PACKAGE))]
            )
        )

    elif is_seo:
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(MOCK_SEO_PACKAGE))]
            )
        )

    elif is_review:
        has_approve = False
        has_save_package_response = False
        actual_saved_dir = ""

        for content in llm_request.contents:
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if part.function_response:
                        if part.function_response.name == "request_review":
                            res_val = part.function_response.response.get("result", "")
                            if "APPROVE" in res_val:
                                has_approve = True
                        if part.function_response.name == "save_final_package":
                            has_save_package_response = True
                            # Extract saved directory name from response
                            tool_out = part.function_response.response.get("result", "")
                            if "output/" in tool_out:
                                start_idx = tool_out.find("output/")
                                actual_saved_dir = tool_out[start_idx:].strip()

        if has_save_package_response:
            text_content = json.dumps({
                "status": "approved",
                "saved_directory": actual_saved_dir,
                "message": "Successfully saved package and approved."
            })
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=text_content)]
                )
            )
        elif has_approve:
            fc = types.FunctionCall(
                name="save_final_package",
                id="fc-save-package",
                args={
                    "topic": "why gen z is burnt out before they even start their careers",
                    "research_brief_json": json.dumps(MOCK_RESEARCH_BRIEF),
                    "script_markdown": MOCK_SCRIPT_PACKAGE["script"],
                    "seo_package_json": json.dumps(MOCK_SEO_PACKAGE),
                    "approved_by": "human"
                }
            )
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=fc)]
                )
            )
        else:
            # Trigger review gate pause
            fc = types.FunctionCall(
                name="request_review",
                id="fc-request-review",
                args={
                    "hook": MOCK_SCRIPT_PACKAGE["hook"],
                    "word_count": MOCK_SCRIPT_PACKAGE["word_count"],
                    "estimated_duration": MOCK_SCRIPT_PACKAGE["estimated_duration"],
                    "titles": MOCK_SEO_PACKAGE["titles"],
                    "tags": MOCK_SEO_PACKAGE["tags"],
                    "thumbnail_brief": MOCK_SEO_PACKAGE["thumbnail_brief"],
                    "sources_cited": MOCK_SCRIPT_PACKAGE["sources_cited"],
                    "unverified_claims_detected": False
                }
            )
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=fc)]
                )
            )

async def run_pipeline():
    topic = "why gen z is burnt out before they even start their careers"
    start_time = time.time()

    session_service = InMemorySessionService()
    runner = Runner(
        agent=orchestrator,
        app_name="ContentOS",
        session_service=session_service,
        auto_create_session=True
    )

    session_id = "approved_run_session"
    user_id = "default_user"

    print(f"\n[ContentOS] Starting pipeline for topic: '{topic}'")
    print("=" * 60)

    # Step 1: Start Run
    user_msg = types.Content(parts=[types.Part(text=topic)])
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=user_msg
    ):
        if event.message:
            print(f"[{event.author or 'Agent'}] {event.message}")
        elif event.node_info and event.node_info.name:
            print(f"[Pipeline] Running node: {event.node_info.name}")

    session = await session_service.get_session(
        app_name="ContentOS",
        user_id=user_id,
        session_id=session_id
    )

    fc_by_id = {}
    fr_ids = set()
    for event in session.events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call and part.function_call.name == "request_review":
                    fc_by_id[part.function_call.id] = part.function_call
                if part.function_response:
                    fr_ids.add(part.function_response.id)

    unresolved = [fc for fc_id, fc in fc_by_id.items() if fc_id not in fr_ids]

    if unresolved:
        unresolved_fc = unresolved[-1]
        print(f"\n[HITL] Paused at review gate. Resuming with APPROVE response (ID: {unresolved_fc.id})...")
        
        # Step 2: Resume with APPROVE
        resume_msg = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=unresolved_fc.id,
                        name="request_review",
                        response={"result": "APPROVE"}
                    )
                )
            ]
        )
        
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=resume_msg
        ):
            if event.message:
                print(f"[{event.author or 'Agent'}] {event.message}")
            elif event.node_info and event.node_info.name:
                print(f"[Pipeline] Running node: {event.node_info.name}")

    # Summary
    session = await session_service.get_session(
        app_name="ContentOS",
        user_id=user_id,
        session_id=session_id
    )
    
    orchestrator_output = session.state.get("orchestrator_output", {})
    if hasattr(orchestrator_output, "model_dump"):
        orchestrator_output = orchestrator_output.model_dump()

    script_package = session.state.get("script_package") or {}
    seo_package = session.state.get("seo_package") or {}

    word_count = script_package.get("word_count", "N/A")
    titles = seo_package.get("titles", [])
    status = orchestrator_output.get("status", "unknown")
    saved_dir = orchestrator_output.get("saved_directory")
    total_time = time.time() - start_time

    print("\n" + "=" * 60)
    print("  CONTENTOS PIPELINE RUN SUMMARY (APPROVED)")
    print("=" * 60)
    print(f"Topic Processed:    {topic}")
    print(f"Status:             {status.upper()}")
    if saved_dir:
        print(f"Output Folder:      {saved_dir}")
        if os.path.exists(saved_dir):
            print(f"Files Exported:     {os.listdir(saved_dir)}")
    print(f"Script Word Count:  {word_count}")
    print("Titles Generated:")
    for idx, t in enumerate(titles, 1):
        print(f"  {idx}. {t}")
    print(f"Total Time:         {total_time:.2f} seconds")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    with patch.object(Gemini, "generate_content_async", new=mock_generate_content_async):
        asyncio.run(run_pipeline())
