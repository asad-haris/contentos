"""Research Agent for ContentOS.

Responsible for gathering information, verifying facts, and compiling structured briefs.
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

# Load the research-summarizer skill
SKILL_DIR = pathlib.Path(__file__).parent.parent / "skills" / "research-summarizer"
skill = load_skill_from_dir(SKILL_DIR)

class SourceInfo(BaseModel):
    """Structured details of a single research source."""
    title: str = Field(description="The title of the source article or document.")
    url: str = Field(description="The direct source URL.")
    key_claims: list[str] = Field(description="Key claims or arguments extracted from the source.")
    stats: list[str] = Field(description="Relevant statistics, data points, or metrics.")
    date: str = Field(description="Publication or update date of the source.")

class ResearchBrief(BaseModel):
    """The final structured research brief output format."""
    topic: str = Field(description="The video topic or content idea.")
    sources: list[SourceInfo] = Field(description="List of 3 to 5 high-quality sources.")
    summary: str = Field(description="A concise 150-word synthesis of all sources.")
    angles: list[str] = Field(description="Three potential video angles based on the research.")
    refine_required: bool = Field(default=False, description="Set to True if fewer than 2 sources are found.")
    refine_message: Optional[str] = Field(default=None, description="Message asking the user to refine the topic.")

from config import web_search

# Define Research Agent
research_agent = Agent(
    name="ResearchAgent",
    model=Gemini(model="gemini-2.5-flash"),
    instruction=(
        f"{skill.instructions}\n\n"
        "Your task is to call the `web_search` tool to gather 3-5 high-quality sources about the user's video topic.\n"
        "Analyze the results and synthesize the research brief into the requested output schema.\n\n"
        "GUARDRAIL RULES:\n"
        "1. If the `web_search` tool returns NO results or fewer than 2 sources, you MUST set `refine_required` to True and "
        "populate the `refine_message` with a message asking the user to refine their video topic. In this case, do NOT populate the other fields.\n"
        "2. If 2 or more sources are found, set `refine_required` to False and generate a complete brief with the summary and angles.\n"
        "3. WORD COUNT RULE: The `summary` field in the output brief MUST be a detailed synthesis between 130 and 180 words. Do NOT write a summary shorter than 100 words or longer than 200 words."
    ),
    tools=[web_search],
    output_schema=ResearchBrief,
    output_key="research_brief"
)

async def run_research(topic: str) -> dict:
    """Invokes the ResearchAgent to run the research workflow on a topic.

    Args:
        topic: The content topic/idea.

    Returns:
        A dictionary representing the structured research brief or refinement request.
    """
    session_service = InMemorySessionService()
    runner = Runner(
        agent=research_agent,
        app_name="agents",
        session_service=session_service,
        auto_create_session=True
    )
    
    user_msg = f"Video topic: {topic}"
    
    async for event in runner.run_async(
        user_id="default_user",
        session_id="research_session",
        new_message=types.Content(parts=[types.Part(text=user_msg)])
    ):
        pass
        
    session = await session_service.get_session(
        app_name="agents",
        user_id="default_user",
        session_id="research_session"
    )
    
    brief = session.state.get("research_brief")
    if brief:
        return brief.model_dump() if hasattr(brief, "model_dump") else brief
        
    return {
        "topic": topic,
        "sources": [],
        "summary": "An error occurred. No brief was generated.",
        "angles": [],
        "refine_required": True,
        "refine_message": "Failed to run research pipeline."
    }
