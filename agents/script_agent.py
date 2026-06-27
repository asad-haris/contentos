"""Scriptwriting Agent for ContentOS.

Responsible for translating research briefs into engaging scripts tailored to the channel voice.
"""

import os
import pathlib
from typing import Optional
from pydantic import BaseModel, Field
from google.adk.agents import Agent
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

# Load the scriptwriting skill configuration
SKILL_DIR = pathlib.Path(__file__).parent.parent / "skills" / "scriptwriting"
skill = load_skill_from_dir(SKILL_DIR)

class ScriptOutput(BaseModel):
    """The structured script output format."""
    script: str = Field(description="The full formatted script, strict lowercase and structured.")
    word_count: int = Field(description="Total word count of the script narration.")
    estimated_duration: str = Field(description="Estimated video duration, e.g. '8-10 minutes'.")
    sources_cited: list[str] = Field(description="List of URLs cited/referenced in the script.")
    hook: str = Field(description="The isolated hook line (first 15 seconds) from the script.")

# Define the Script Agent
script_agent = Agent(
    name="ScriptAgent",
    model=Gemini(model="gemini-2.5-flash"),
    instruction=(
        f"{skill.instructions}\n\n"
        "Your task is to accept a research brief as input and generate a structured YouTube script.\n"
        "The script must follow these strict requirements:\n"
        "1. LENGTH: The narration text inside the script MUST be between 150 and 250 words total. Do not exceed this limit.\n"
        "2. STRUCTURE: Use exactly the following markdown section headers in the script to separate the parts:\n"
        "   - `# Hook` (for the intro)\n"
        "   - `# Section 1` (for the first point/argument)\n"
        "   - `# Section 2` (for the second point/argument)\n"
        "   - `# Section 3` (for the third point/argument)\n"
        "   - `# CTA` (for the call-to-action)\n"
        "3. VOICE: Tone must be smart older sibling who's done being polite. Direct and blunt. Script narration text (under the headers) must be in strict lowercase only.\n"
        "4. CITATIONS: You must explicitly cite the source URLs inside the script narration (e.g. 'according to https://example.com/source'). "
        "Cite at least 2 distinct URLs from the sources list in the research brief."
    ),
    output_schema=ScriptOutput,
    output_key="script_output"
)

def validate_script(script_data: dict, brief: dict) -> list[str]:
    """Validates that the generated script respects the required guardrails.

    Args:
        script_data: The output dictionary from the ScriptAgent.
        brief: The research brief dictionary containing original sources.

    Returns:
        A list of string descriptions for any failed validation checks.
    """
    errors = []
    
    # 1. Banned Hook starts check
    hook = script_data.get("hook", "").strip().lower()
    banned_starts = ["in today's video", "hey guys", "welcome back"]
    for prefix in banned_starts:
        if hook.startswith(prefix):
            errors.append(f"Hook starts with banned phrase: '{prefix}'")
            
    # 2. Citations check: make sure at least 2 sources from brief are cited in the script text
    brief_urls = [src.get("url") for src in brief.get("sources", []) if src.get("url")]
    script_text = script_data.get("script", "").lower()
    
    cited_count = 0
    for url in brief_urls:
        if url.lower() in script_text:
            cited_count += 1
            
    if cited_count < 2:
        errors.append(
            f"Script cites {cited_count} sources from the brief. "
            "You must cite at least 2 sources by embedding their URLs directly in the narration."
        )
        
    return errors

async def run_script(brief: dict, max_retries: int = 3) -> dict:
    """Invokes the ScriptAgent to generate a script and performs guardrail audits with corrective feedback.

    Args:
        brief: The research brief dictionary.
        max_retries: Maximum number of correction loops if validation fails.

    Returns:
        A dictionary matching the ScriptOutput schema.
    """
    session_service = InMemorySessionService()
    runner = Runner(
        agent=script_agent,
        app_name="agents",
        session_service=session_service,
        auto_create_session=True
    )
    
    user_msg = f"Research Brief:\n{brief}"
    
    for attempt in range(max_retries):
        async for event in runner.run_async(
            user_id="default_user",
            session_id="script_session",
            new_message=types.Content(parts=[types.Part(text=user_msg)])
        ):
            pass
            
        session = await session_service.get_session(
            app_name="agents",
            user_id="default_user",
            session_id="script_session"
        )
        
        script_data = session.state.get("script_output")
        if not script_data:
            break
            
        # Serialize to dict if it's a Pydantic object
        script_dict = script_data.model_dump() if hasattr(script_data, "model_dump") else script_data
        
        # Check guardrails
        errors = validate_script(script_dict, brief)
        if not errors:
            return script_dict
            
        # Compile corrective feedback message and retry
        user_msg = (
            f"Your previous output violated guardrail rules:\n"
            + "\n".join(f"- {err}" for err in errors)
            + "\n\nPlease rewrite and output the corrected script schema."
        )
        
    # Return last attempt or fallback
    session = await session_service.get_session(
        app_name="agents",
        user_id="default_user",
        session_id="script_session"
    )
    last_data = session.state.get("script_output")
    if last_data:
        return last_data.model_dump() if hasattr(last_data, "model_dump") else last_data
        
    return {
        "script": "failed to generate compliant script.",
        "word_count": 0,
        "estimated_duration": "0 minutes",
        "sources_cited": [],
        "hook": ""
    }
