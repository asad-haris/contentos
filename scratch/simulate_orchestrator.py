import os
import sys
import json
import asyncio
import shutil
import re
from pathlib import Path
from dotenv import load_dotenv
from unittest.mock import patch

# Load environment variables
load_dotenv()

# Add project root to sys.path
sys.path.append(os.getcwd())

from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from agents.orchestrator import orchestrator, OrchestratorAgent

# Mocked outputs for each step
MOCK_SOURCES = [
    {
        "title": "Quantum Computing for Everyone",
        "url": "https://example.edu/quantum-everyone",
        "key_claims": ["Qubits use superposition to represent 0 and 1 simultaneously."],
        "stats": ["Computes certain algorithms 100 million times faster."],
        "date": "2025-03-12"
    },
    {
        "title": "The Quantum Threat to Encryption",
        "url": "https://cybersecurity-journal.com/quantum-threat",
        "key_claims": ["Shor's algorithm can break RSA encryption."],
        "stats": ["RSA-2048 encryption could be broken in less than 24 hours."],
        "date": "2025-01-20"
    }
]

MOCK_RESEARCH_BRIEF = {
    "topic": "Explain quantum computing in simple terms for a teenager",
    "sources": MOCK_SOURCES,
    "summary": "quantum computing utilizes superposition and entanglement to calculate faster than classical computers.",
    "angles": ["Angle 1", "Angle 2", "Angle 3"],
    "refine_required": False
}

MOCK_SCRIPT_PACKAGE = {
    "script": "hook: what if a computer could do a million things at once? rennasks is here to break it down. qubits use superposition to exist as 0 and 1 simultaneously, according to https://example.edu/quantum-everyone. and they can break rsa encryption, according to https://cybersecurity-journal.com/quantum-threat. subscribe to our channel for more.",
    "word_count": 65,
    "estimated_duration": "45 seconds",
    "sources_cited": ["https://example.edu/quantum-everyone", "https://cybersecurity-journal.com/quantum-threat"],
    "hook": "what if a computer could do a million things at once?"
}

MOCK_SEO_PACKAGE = {
    "titles": ["how 5 qubits rule the world", "is quantum computing real?", "why quantum computers rule"],
    "description": "Explaining quantum computing in simple terms for teenagers.",
    "tags": ["quantum", "qubit", "superposition"],
    "thumbnail_brief": "A glowing quantum processor.",
    "chapter_markers": ["0:00 - Hook", "0:15 - Qubits"]
}

async def mock_generate_content_async(self, llm_request, stream=False):
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    # Detect which agent is calling by looking at system_instruction or prompt contents
    system_instr = ""
    if hasattr(llm_request, "config") and llm_request.config and llm_request.config.system_instruction:
        instr = llm_request.config.system_instruction
        if isinstance(instr, str):
            system_instr = instr.lower()
        elif hasattr(instr, "parts"):
            system_instr = "".join(p.text for p in instr.parts if p.text).lower()

    content_text = ""
    content_text = ""
    print(f"[Mock LLM Debug] contents:")
    for content in llm_request.contents:
        print(f"  role: {content.role}")
        if content.parts:
            for part in content.parts:
                if part.text:
                    print(f"    text: {part.text[:100]}...")
                if part.function_call:
                    print(f"    function_call: {part.function_call.name} (id: {part.function_call.id})")
                if part.function_response:
                    print(f"    function_response: {part.function_response.name} (id: {part.function_response.id}), response: {part.function_response.response}")
            content_text += "".join(p.text for p in content.parts if p.text).lower()

    # Determine caller agent using highly specific and robust keywords
    is_research = "web_search" in system_instr or "sources using the" in system_instr or "summarizer" in system_instr
    is_script = "sibling" in system_instr or "narration" in system_instr or "scriptwriting" in system_instr
    is_review = "reviewagent" in system_instr or "request_review" in system_instr or "unverified_claims" in system_instr
    is_seo = ("seo" in system_instr or "chapter_markers" in system_instr or "titles" in system_instr) and not is_review

    print(f"[Mock LLM Debug] system_instr: '{system_instr[:60]}...' matches: research={is_research}, script={is_script}, seo={is_seo}, review={is_review}")

    if is_research:
        # First turn: call web_search
        has_search_response = False
        for content in llm_request.contents:
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if part.function_response and part.function_response.name == "web_search":
                        has_search_response = True

        if has_search_response:
            # Second turn: return ResearchBrief JSON
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
                args={"query": "Explain quantum computing in simple terms for a teenager"}
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

    elif is_review:
        # Check if there is a function response for request_review and save_final_package
        has_approve = False
        has_revise = False
        has_reject = False
        has_save_package_response = False
        actual_saved_dir = "output/explain_quantum_computing_in_simple_terms_for_a_teenager_20260623_190857"

        for content in llm_request.contents:
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if part.function_response:
                        if part.function_response.name == "request_review":
                            res_val = part.function_response.response.get("result")
                            if res_val == "APPROVE":
                                has_approve = True
                            elif res_val == "REVISE":
                                has_revise = True
                            elif res_val == "REJECT":
                                has_reject = True
                        if part.function_response.name == "save_final_package":
                            has_save_package_response = True
                            tool_output = part.function_response.response.get("result", "")
                            match = re.search(r'(output/[a-zA-Z0-9_]+)', tool_output)
                            if match:
                                actual_saved_dir = match.group(1)

        if has_save_package_response:
            # Final approved output
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
                    "topic": "Explain quantum computing in simple terms for a teenager",
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
        elif has_revise:
            # Simulated revision targeting ScriptAgent
            text_content = json.dumps({
                "status": "revise",
                "next_action": "ScriptAgent",
                "revision_notes": "make the script hook slightly punchier.",
                "message": "Routing back for revision."
            })
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=text_content)]
                )
            )
        elif has_reject:
            text_content = json.dumps({
                "status": "rejected",
                "message": "Package was rejected. Stopping."
            })
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=text_content)]
                )
            )
        else:
            # Initial review pause
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

    elif is_seo:
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(MOCK_SEO_PACKAGE))]
            )
        )

async def run_simulation():
    print("--- STARTING ORCHESTRATOR PIPELINE SIMULATION ---")

    session_service = InMemorySessionService()
    runner = Runner(
        agent=orchestrator,
        app_name="ContentOS",
        session_service=session_service,
        auto_create_session=True
    )

    user_msg = types.Content(parts=[types.Part(text="Explain quantum computing in simple terms for a teenager")])

    with patch.object(Gemini, "generate_content_async", new=mock_generate_content_async):
        # 1. Start pipeline run (expecting pause at ReviewAgent)
        print("\n[Step 1] Launching Orchestrator pipeline (expecting pause at ReviewAgent)...")
        
        # We collect events to verify flow
        events = []
        async for event in runner.run_async(
            user_id="default_user",
            session_id="orch_session_1",
            new_message=user_msg
        ):
            events.append(event)
            print(f"Event: node={event.node_info.name or 'Orchestrator'} path={event.node_info.path}")

        session = await session_service.get_session(
            app_name="ContentOS",
            user_id="default_user",
            session_id="orch_session_1"
        )

        # Get latest review node status or unresolved call
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
        if not unresolved:
            print("FAIL: Expected pipeline to pause at request_review HITL gate.")
            return

        unresolved_fc = unresolved[-1]
        print(f"SUCCESS: Paused at HITL gate with call ID: {unresolved_fc.id}")

        # 2. Resume execution with APPROVE response
        print("\n[Step 2] Resuming pipeline with 'APPROVE' response...")
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
            user_id="default_user",
            session_id="orch_session_1",
            new_message=resume_msg
        ):
            print(f"Event: node={event.node_info.name or 'Orchestrator'} path={event.node_info.path}")

        session = await session_service.get_session(
            app_name="ContentOS",
            user_id="default_user",
            session_id="orch_session_1"
        )

        # Output should be set and should contain status approved
        print(f"Final Output: {session.state.get('orchestrator_output')}")
        review_data = session.state.get("orchestrator_output")
        review_dict = review_data.model_dump() if hasattr(review_data, "model_dump") else review_data
        
        if review_dict and review_dict.get("status") == "approved":
            print("SUCCESS: Pipeline approved and finished successfully!")
            saved_dir = review_dict.get("saved_directory")
            if saved_dir and os.path.exists(saved_dir):
                print(f"Verification: Files saved in {saved_dir}: {os.listdir(saved_dir)}")
                shutil.rmtree(saved_dir)
                print("Cleaned up saved files.")
        else:
            print("FAIL: Expected output status 'approved'")
            return

        # 3. Verify execution trace log
        log_path = "output/execution_log.json"
        if os.path.exists(log_path):
            print(f"\n[Verification] Checking execution log: {log_path}")
            with open(log_path, "r", encoding="utf-8") as f:
                trace = json.load(f)
            print(f"Trace status: {trace.get('status')}")
            print(f"Number of steps recorded: {len(trace.get('steps', []))}")
            for step in trace.get("steps", []):
                print(f"  Step: Node={step.get('node')} RunID={step.get('run_id')}")
        else:
            print("FAIL: Execution trace log not found on disk.")
            return

    print("\n--- ORCHESTRATOR PIPELINE SIMULATION COMPLETED SUCCESSFULLY ---")

if __name__ == "__main__":
    asyncio.run(run_simulation())
