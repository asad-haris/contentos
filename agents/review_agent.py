"""Review Agent for ContentOS.

Provides a Human-in-the-Loop (HITL) gate for script approval, revisions, or rejection.
"""

import os
import json
import re
import datetime
import logging
from typing import Optional, Any
from pydantic import BaseModel, Field
from google.adk.agents import Agent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService
from google.adk.tools.long_running_tool import LongRunningFunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

logger = logging.getLogger(__name__)

# Shared session service instance
_session_service: Optional[Any] = None

def get_session_service() -> Any:
    """Returns the persistent session service based on configuration."""
    global _session_service
    if _session_service is None:
        db_path = os.environ.get("SESSION_DB_PATH")
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")
        
        if os.environ.get("USE_VERTEX_AI_SESSION_SERVICE") == "true" and project:
            _session_service = VertexAiSessionService(project=project, location=location)
            logger.info("Initialized VertexAiSessionService")
        elif db_path:
            _session_service = SqliteSessionService(db_path)
            logger.info(f"Initialized SqliteSessionService with database: {db_path}")
        else:
            _session_service = InMemorySessionService()
            logger.info("Initialized InMemorySessionService (singleton)")
    return _session_service

class ReviewOutput(BaseModel):
    """The final structured output from the ReviewAgent."""
    status: str = Field(description="The status of the review: 'approved', 'revise', or 'rejected'.")
    saved_directory: Optional[str] = Field(default=None, description="The path where files were saved (if approved).")
    next_action: Optional[str] = Field(default=None, description="If status is 'revise', which agent to re-run (e.g. 'ScriptAgent', 'SEOAgent', 'ResearchAgent').")
    revision_notes: Optional[str] = Field(default=None, description="If status is 'revise', the feedback notes for revision.")
    message: str = Field(description="Status confirmation or exit message.")

def request_review(
    hook: str,
    word_count: int,
    estimated_duration: str,
    titles: list[str],
    tags: list[str],
    thumbnail_brief: str,
    sources_cited: list[str],
    unverified_claims_detected: bool,
    tool_context: ToolContext
) -> Optional[str]:
    """Presents the structured content package to the human for review and pauses for choice."""
    logger.debug(f"request_review called with hook: '{hook}'")
    tool_context.actions.skip_summarization = True
    return None

request_review_tool = LongRunningFunctionTool(func=request_review)

def save_final_package(
    topic: str,
    research_brief_json: str,
    script_markdown: str,
    seo_package_json: str,
    approved_by: str = "human"
) -> str:
    """Saves the approved content package files to the output directory.

    Args:
        topic: The original video topic/idea.
        research_brief_json: Stringified JSON of the research brief.
        script_markdown: The markdown string of the final script.
        seo_package_json: Stringified JSON of the SEO metadata.
        approved_by: The name of the approver (default: 'human').

    Returns:
        A message confirming where the files were saved.
    """
    logger.debug(f"save_final_package running for topic: {topic}")
    # Create topic slug
    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower()).strip('_')
    if not slug:
        slug = "content_package"
        
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{slug}_{timestamp}"
    output_dir = os.path.join("output", folder_name)
    os.makedirs(output_dir, exist_ok=True)
    
    # Save script.md
    with open(os.path.join(output_dir, "script.md"), "w", encoding="utf-8") as f:
        f.write(script_markdown)
        
    # Save research_brief.json
    try:
        rb_data = json.loads(research_brief_json)
    except Exception:
        rb_data = {"raw_brief": research_brief_json}
    with open(os.path.join(output_dir, "research_brief.json"), "w", encoding="utf-8") as f:
        json.dump(rb_data, f, indent=2)
        
    # Save seo_package.json
    try:
        seo_data = json.loads(seo_package_json)
    except Exception:
        seo_data = {"raw_seo": seo_package_json}
    with open(os.path.join(output_dir, "seo_package.json"), "w", encoding="utf-8") as f:
        json.dump(seo_data, f, indent=2)
        
    # Save approval_log.json
    log_data = {
        "approved_by": approved_by,
        "timestamp": datetime.datetime.now().isoformat(),
        "topic": topic,
        "files_saved": ["script.md", "research_brief.json", "seo_package.json"]
    }
    with open(os.path.join(output_dir, "approval_log.json"), "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)
        
    return f"Successfully saved package to output/{folder_name}/"

# Define the Review Agent
review_agent = Agent(
    name="ReviewAgent",
    model=Gemini(model="gemini-2.5-flash"),
    include_contents="default",
    instruction=(
        "You are the ReviewAgent for ContentOS. Your job is to audit the generated content package "
        "(research brief, script, and SEO package) and present it to the human for approval using `request_review`.\n\n"
        "GUARDRAIL: Compare the script against the research brief's sources. If the script contains any unverified claims "
        "(claims not found in the source documents), you MUST set `unverified_claims_detected` to True in the `request_review` call.\n\n"
        "Wait for the human's response. Based on their response:\n"
        "- If they choose 'APPROVE', call `save_final_package` to write all files and output status='approved'.\n"
        "- If they choose 'REVISE', ask for revision notes and which agent to route back to, then output status='revise'.\n"
        "- If they choose 'REJECT', output status='rejected' and abort the pipeline."
    ),
    tools=[request_review_tool, save_final_package],
    output_schema=ReviewOutput,
    output_key="review_output"
)

async def run_review(
    topic: str,
    research_brief: dict,
    script_data: dict,
    seo_data: dict,
    human_response: Optional[str] = None
) -> dict:
    """Invokes the ReviewAgent and handles the HITL pause/resume flow.

    Args:
        topic: The original video topic/idea.
        research_brief: The research brief.
        script_data: The script details.
        seo_data: The SEO package details.
        human_response: Optional human review choice ('APPROVE', 'REVISE', 'REJECT'). If None,
                        the run will pause at the review interrupt.

    Returns:
        A dictionary matching the ReviewOutput schema, or a waiting status dictionary.
    """
    session_service = get_session_service()
    
    # Try to load existing session
    session = await session_service.get_session(
        app_name="agents",
        user_id="default_user",
        session_id="review_session"
    )
    
    unresolved_fc = None
    if session:
        # Check if already resolved and output exists
        review_data = session.state.get("review_output")
        if review_data:
            return review_data.model_dump() if hasattr(review_data, "model_dump") else review_data
            
        # Scan session events for any unresolved request_review call
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

    runner = Runner(
        agent=review_agent,
        app_name="agents",
        session_service=session_service,
        auto_create_session=True
    )

    if human_response:
        # Resuming execution
        if human_response not in ["APPROVE", "REVISE", "REJECT"]:
            human_response = "REJECT"
            
        if not unresolved_fc:
            raise ValueError("Cannot resume: no unresolved request_review call found in session history.")
            
        # Build the FunctionResponse to resume execution
        new_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=unresolved_fc.id,
                        name="request_review",
                        response={"result": human_response}
                    )
                )
            ]
        )
        
        async for event in runner.run_async(
            user_id="default_user",
            session_id="review_session",
            new_message=new_message
        ):
            pass
            
    else:
        # Starting or checking status
        if unresolved_fc:
            # Already paused at the gate, return waiting status and surface package details
            args = unresolved_fc.args or {}
            return {
                "status": "waiting_for_review",
                "saved_directory": None,
                "next_action": None,
                "revision_notes": None,
                "message": "Content package is holding at the review gate for approval.",
                "package_details": {
                    "hook": args.get("hook"),
                    "word_count": args.get("word_count"),
                    "estimated_duration": args.get("estimated_duration"),
                    "titles": args.get("titles"),
                    "tags": args.get("tags"),
                    "thumbnail_brief": args.get("thumbnail_brief"),
                    "sources_cited": args.get("sources_cited"),
                    "unverified_claims_detected": args.get("unverified_claims_detected")
                }
            }
            
        # Fresh run: pack content package inside initial user message
        user_msg = (
            f"Topic: {topic}\n\n"
            f"Research Brief:\n{json.dumps(research_brief, indent=2)}\n\n"
            f"Script Data:\n{json.dumps(script_data, indent=2)}\n\n"
            f"SEO Data:\n{json.dumps(seo_data, indent=2)}"
        )
        
        new_message = types.Content(parts=[types.Part(text=user_msg)])
        
        async for event in runner.run_async(
            user_id="default_user",
            session_id="review_session",
            new_message=new_message
        ):
            pass

    # Retrieve the final state after execution
    session = await session_service.get_session(
        app_name="agents",
        user_id="default_user",
        session_id="review_session"
    )
    
    review_data = session.state.get("review_output")
    if review_data:
        return review_data.model_dump() if hasattr(review_data, "model_dump") else review_data
        
    # Check if now waiting for review
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
        args = unresolved_fc.args or {}
        return {
            "status": "waiting_for_review",
            "saved_directory": None,
            "next_action": None,
            "revision_notes": None,
            "message": "Content package is holding at the review gate for approval.",
            "package_details": {
                "hook": args.get("hook"),
                "word_count": args.get("word_count"),
                "estimated_duration": args.get("estimated_duration"),
                "titles": args.get("titles"),
                "tags": args.get("tags"),
                "thumbnail_brief": args.get("thumbnail_brief"),
                "sources_cited": args.get("sources_cited"),
                "unverified_claims_detected": args.get("unverified_claims_detected")
            }
        }
        
    return {
        "status": "rejected",
        "saved_directory": None,
        "next_action": None,
        "revision_notes": None,
        "message": "Review run finished without approval outcome."
    }

