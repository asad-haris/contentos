"""Orchestrator Agent for ContentOS.

Coordinates the research, scriptwriting, SEO optimization, and review pipeline.
Uses Google ADK 2.0 graph workflow syntax with conditional routing and HITL.
"""

import os
import json
import logging
import datetime
from typing import Any, AsyncGenerator, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import Workflow, START, Edge, FunctionNode, DEFAULT_ROUTE
from google.adk.agents.context import Context
from google.adk.events.event import Event

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class ContentOsState(BaseModel):
    """Pydantic model representing the shared state of the ContentOS pipeline.
    
    Attributes:
        topic: The user's content prompt or video idea.
        research_brief: Compiled brief from ResearchAgent.
        script_package: Narration script and metadata from ScriptAgent.
        seo_package: Metadata package from SEOAgent.
        revision_loop_count: Tracks number of revision cycles (max 3).
        revision_target: Target agent for revision feedback.
        revision_notes: Feedback notes for the revision target.
    """
    topic: str = ""
    research_brief: dict = Field(default_factory=dict)
    script_package: dict = Field(default_factory=dict)
    seo_package: dict = Field(default_factory=dict)
    revision_loop_count: int = 0
    revision_target: str = ""
    revision_notes: str = ""
    orchestrator_output: dict = Field(default_factory=dict)
    review_output: dict = Field(default_factory=dict)

# ---------------------------------------------------------------------------
# Node Functions wrapping each Agent in the workflow
# ---------------------------------------------------------------------------

async def run_research_node(ctx: Context, node_input: Any) -> dict:
    """Wraps ResearchAgent execution inside the workflow.

    Args:
        ctx: Workflow execution context.
        node_input: Video topic string from START.

    Returns:
        Structured research brief dict.
    """
    # Initialize or retrieve topic from state
    topic = ctx.state.get("topic")
    if not topic:
        topic = str(node_input)
        ctx.state["topic"] = topic

    revision_target = ctx.state.get("revision_target")
    revision_notes = ctx.state.get("revision_notes") if revision_target == "ResearchAgent" else None

    # Guide research agent with revision feedback if looping back
    run_topic = topic
    if revision_notes:
        run_topic = f"{topic}\n\n[REVISION NOTE]: {revision_notes}"

    logger.info(f"Running ResearchAgent on topic: {topic}")
    try:
        from agents.research_agent import run_research
        brief = await run_research(run_topic)
    except Exception as e:
        logger.error(f"ResearchAgent failed: {e}")
        raise RuntimeError(f"ResearchAgent failed: {e}") from e

    # Guardrail check: Refusal or lack of sources
    if brief.get("refine_required"):
        raise ValueError(brief.get("refine_message") or "Fewer than 2 sources found. Please refine topic.")

    ctx.state["research_brief"] = brief

    # Clear revision info after applying it
    if revision_target == "ResearchAgent":
        ctx.state["revision_target"] = ""
        ctx.state["revision_notes"] = ""

    return brief

async def run_script_node(ctx: Context, node_input: Any) -> dict:
    """Wraps ScriptAgent execution inside the workflow.

    Args:
        ctx: Workflow execution context.
        node_input: Research brief from ResearchAgent.

    Returns:
        Structured script package dict.
    """
    brief = ctx.state.get("research_brief") or node_input
    if not brief:
        raise ValueError("Missing research brief for ScriptAgent.")

    revision_target = ctx.state.get("revision_target")
    revision_notes = ctx.state.get("revision_notes") if revision_target == "ScriptAgent" else None

    # Inject revision notes into scriptwriter brief if looping back
    if revision_notes:
        brief_copy = dict(brief)
        brief_copy["summary"] = f"{brief_copy.get('summary', '')}\n\n[REVISION FEEDBACK]: {revision_notes}"
        brief = brief_copy

    logger.info("Running ScriptAgent to write draft...")
    try:
        from agents.script_agent import run_script
        script_package = await run_script(brief)
    except Exception as e:
        logger.error(f"ScriptAgent failed: {e}")
        raise RuntimeError(f"ScriptAgent failed: {e}") from e

    ctx.state["script_package"] = script_package

    # Clear revision info after applying it
    if revision_target == "ScriptAgent":
        ctx.state["revision_target"] = ""
        ctx.state["revision_notes"] = ""

    return script_package

async def run_seo_node(ctx: Context, node_input: Any) -> dict:
    """Wraps SEOAgent execution inside the workflow.

    Args:
        ctx: Workflow execution context.
        node_input: Script package from ScriptAgent.

    Returns:
        Structured SEO metadata package dict.
    """
    script_package = ctx.state.get("script_package") or node_input
    topic = ctx.state.get("topic")
    if not script_package or not topic:
        raise ValueError("Missing script package or topic for SEOAgent.")

    logger.info("Running SEOAgent to optimize titles and descriptions...")
    try:
        from agents.seo_agent import run_seo
        seo_package = await run_seo(script_package, topic)
    except Exception as e:
        logger.error(f"SEOAgent failed: {e}")
        raise RuntimeError(f"SEOAgent failed: {e}") from e

    ctx.state["seo_package"] = seo_package

    # Clear revision info after applying it
    if ctx.state.get("revision_target") == "SEOAgent":
        ctx.state["revision_target"] = ""
        ctx.state["revision_notes"] = ""

    return seo_package

async def run_review_node(ctx: Context, node_input: Any) -> dict:
    """Runs the ReviewAgent inside the workflow with full HITL support.

    Args:
        ctx: Workflow execution context.
        node_input: SEO package from SEOAgent.

    Returns:
        Structured review outcome dict.
    """
    topic = ctx.state.get("topic")
    research_brief = ctx.state.get("research_brief")
    script_package = ctx.state.get("script_package")
    seo_package = ctx.state.get("seo_package")

    if not topic or not research_brief or not script_package or not seo_package:
        raise ValueError("Missing required package data for ReviewAgent.")

    combined_msg = (
        f"Topic: {topic}\n\n"
        f"Research Brief:\n{json.dumps(research_brief, indent=2)}\n\n"
        f"Script Data:\n{json.dumps(script_package, indent=2)}\n\n"
        f"SEO Data:\n{json.dumps(seo_package, indent=2)}"
    )

    logger.info("Invoking ReviewAgent for human approval/revision/rejection...")
    from agents.review_agent import review_agent
    try:
        review_output = await ctx.run_node(review_agent, combined_msg)
    except Exception as e:
        logger.error(f"ReviewAgent failed: {e}")
        raise RuntimeError(f"ReviewAgent failed: {e}") from e

    # Extract dict from Pydantic model if returned
    logger.debug(f"review_output type: {type(review_output)}, value: {review_output}")
    if hasattr(review_output, "model_dump"):
        review_dict = review_output.model_dump()
    elif isinstance(review_output, dict):
        review_dict = review_output
    else:
        raise ValueError(f"Unexpected ReviewAgent output format: {type(review_output)}")

    status = review_dict.get("status")
    logger.debug(f"status: {status}, dict: {review_dict}")
    logger.info(f"Review outcome received: status={status}")

    if status == "approved":
        logger.info("Setting route to approved")
        ctx.route = "approved"
    elif status == "rejected":
        logger.info("Setting route to rejected")
        ctx.route = "rejected"
    elif status == "revise":
        # Increment revision loops count
        loop_count = ctx.state.get("revision_loop_count", 0) + 1
        ctx.state["revision_loop_count"] = loop_count

        if loop_count > 3:
            logger.warning("Max revision loops (3) exceeded. Rejecting pipeline.")
            raise ValueError("Max 3 revision loops reached. You must Approve or Reject this package.")

        next_action = review_dict.get("next_action")
        notes = review_dict.get("revision_notes") or ""

        ctx.state["revision_target"] = next_action
        ctx.state["revision_notes"] = notes

        # Set workflow routing
        if next_action == "ResearchAgent":
            logger.info("Setting route to revise_research")
            ctx.route = "revise_research"
        elif next_action == "ScriptAgent":
            logger.info("Setting route to revise_script")
            ctx.route = "revise_script"
        elif next_action == "SEOAgent":
            logger.info("Setting route to revise_seo")
            ctx.route = "revise_seo"
        else:
            logger.info("Setting route to revise_script (default)")
            ctx.route = "revise_script"  # Default fallback
    else:
        logger.info("Setting route to rejected (default)")
        ctx.route = "rejected"

    return review_dict


async def run_approved_node(ctx: Context, node_input: Any) -> dict:
    """Terminal node for approved content packages."""
    logger.debug(f"run_approved_node executing. node_input: {node_input}")
    logger.info("Pipeline approved. ApprovedAgent executing...")
    outcome = node_input if isinstance(node_input, dict) else {}
    ctx.state["orchestrator_output"] = outcome
    return outcome

async def run_rejected_node(ctx: Context, node_input: Any) -> dict:
    """Terminal node for rejected content packages."""
    logger.debug(f"run_rejected_node executing. node_input: {node_input}")
    logger.info("Pipeline rejected. RejectedAgent executing...")
    outcome = {"status": "rejected", "message": "Content package rejected by user. Pipeline terminated."}
    ctx.state["orchestrator_output"] = outcome
    return outcome


# Define standard ADK nodes wrapping the Node functions
ResearchAgent = FunctionNode(func=run_research_node, name="ResearchAgent", rerun_on_resume=True)
ScriptAgent = FunctionNode(func=run_script_node, name="ScriptAgent", rerun_on_resume=True)
SEOAgent = FunctionNode(func=run_seo_node, name="SEOAgent", rerun_on_resume=True)
ReviewAgent = FunctionNode(func=run_review_node, name="ReviewAgent", rerun_on_resume=True)
ApprovedAgent = FunctionNode(func=run_approved_node, name="ApprovedAgent", rerun_on_resume=True)
RejectedAgent = FunctionNode(func=run_rejected_node, name="RejectedAgent", rerun_on_resume=True)


class OrchestratorAgent(Workflow):
    """The main OrchestratorAgent for ContentOS.

    Coordinates sequential routing: Research -> Script -> SEO -> Review.
    Manages loops and exits based on human review outcomes.
    """

    def __init__(self, **kwargs):
        """Initializes OrchestratorAgent with state schema and defined graph edges."""
        kwargs.setdefault("state_schema", ContentOsState)

        edges = [
            # Main forward path
            (START, ResearchAgent),
            (ResearchAgent, ScriptAgent),
            (ScriptAgent, SEOAgent),
            (SEOAgent, ReviewAgent),

            # Branch back loops
            Edge(from_node=ReviewAgent, to_node=ResearchAgent, route="revise_research"),
            Edge(from_node=ReviewAgent, to_node=ScriptAgent, route="revise_script"),
            Edge(from_node=ReviewAgent, to_node=SEOAgent, route="revise_seo"),

            # Explicit terminal routes
            Edge(from_node=ReviewAgent, to_node=ApprovedAgent, route="approved"),
            Edge(from_node=ReviewAgent, to_node=RejectedAgent, route="rejected"),
        ]

        super().__init__(edges=edges, name="OrchestratorAgent", **kwargs)

    async def _run_impl(self, *, ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
        """Main orchestration loop wrapping Workflow execution and output trace logging.

        Args:
            ctx: Execution context.
            node_input: User video idea (string).

        Yields:
            Progress events.
        """
        trace = {
            "topic": node_input,
            "start_time": datetime.datetime.now().isoformat(),
            "steps": [],
            "status": "started"
        }

        # Initialize core workflow state
        ctx.state["topic"] = str(node_input)
        ctx.state["revision_loop_count"] = 0
        ctx.state["revision_target"] = ""
        ctx.state["revision_notes"] = ""

        try:
            async for event in super()._run_impl(ctx=ctx, node_input=node_input):
                yield event

            # Bubble up failed execution if caught
            if ctx.error:
                logger.error(f"_run_impl caught error: {ctx.error}")
                raise ctx.error

            logger.debug(f"_run_impl finished. ctx.interrupt_ids: {ctx.interrupt_ids}, ctx.output: {ctx.output}")
            trace["status"] = "completed" if not ctx.interrupt_ids else "paused"
            trace["state"] = ctx.state.to_dict()
            trace["output"] = ctx.output
            trace["end_time"] = datetime.datetime.now().isoformat()

            if ctx.output is not None:
                output_dict = ctx.output
                if hasattr(output_dict, "model_dump"):
                    output_dict = output_dict.model_dump()

                # Save the final orchestrator output to the session state
                logger.debug(f"Setting orchestrator_output in state to: {output_dict}")
                ctx.state["orchestrator_output"] = output_dict

                # Log clean exits based on approval / rejection
                if isinstance(output_dict, dict):
                    status = output_dict.get("status")
                    if status == "approved":
                        saved_dir = output_dict.get("saved_directory")
                        yield Event(
                            message=f"content package approved and saved to: {saved_dir}",
                            author="OrchestratorAgent"
                        )
                    elif status == "rejected":
                        yield Event(
                            message="content package rejected by user. clean exit.",
                            author="OrchestratorAgent"
                        )

        except Exception as e:
            error_msg = f"Pipeline execution failed. Node: {ctx.error_node_path or 'unknown'}. Error: {str(e)}"
            logger.error(error_msg)
            trace["status"] = "failed"
            trace["error"] = error_msg
            trace["end_time"] = datetime.datetime.now().isoformat()
            self._write_trace(ctx, trace)

            yield Event(
                message=f"pipeline error: {error_msg}",
                author="OrchestratorAgent"
            )
            raise RuntimeError(error_msg) from e

        self._write_trace(ctx, trace)

    def _write_trace(self, ctx: Context, trace: dict):
        """Logs the full execution trace to output/execution_log.json.

        Args:
            ctx: Execution context.
            trace: Dictionary containing trace information.
        """
        def serialize_for_json(val: Any) -> Any:
            if hasattr(val, "model_dump"):
                try:
                    return val.model_dump()
                except Exception:
                    return str(val)
            elif isinstance(val, dict):
                return {k: serialize_for_json(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [serialize_for_json(item) for item in val]
            elif isinstance(val, set):
                return [serialize_for_json(item) for item in val]
            return val

        try:
            steps = []
            seen_events = set()
            for event in ctx.session.events:
                if event.id in seen_events:
                    continue
                seen_events.add(event.id)

                node_name = event.node_info.name
                if not node_name:
                    continue

                step_info = {
                    "node": node_name,
                    "run_id": event.node_info.run_id,
                    "timestamp": datetime.datetime.fromtimestamp(event.timestamp).isoformat() if event.timestamp else datetime.datetime.now().isoformat(),
                }

                if event.output is not None:
                    step_info["output"] = event.output
                if event.content and event.content.parts:
                    step_info["content"] = [p.text for p in event.content.parts if p.text is not None]

                steps.append(step_info)

            trace["steps"] = steps

            os.makedirs("output", exist_ok=True)
            log_path = os.path.join("output", "execution_log.json")

            serialized_trace = serialize_for_json(trace)
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(serialized_trace, f, indent=2)

            logger.info(f"Execution trace written to {log_path}")
        except Exception as e:
            logger.error(f"Failed to write execution trace: {e}")


# Create orchestrator agent instance for app initialization
orchestrator = OrchestratorAgent()

# Main ADK Application entrypoint
app = App(
    root_agent=orchestrator,
    name="ContentOS_Orchestrator",
)

if __name__ == "__main__":
    print("ContentOS Orchestrator initialized successfully.")
