"""Main entry point for ContentOS.

Loads configuration, initializes services, accepts inputs, runs the agent
pipeline, and presents the Human-in-the-Loop review gate in the console.
"""

import os
import sys
import time
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Map GOOGLE_API_KEY to GEMINI_API_KEY to force Developer API backend in Cloud Run
if "GOOGLE_API_KEY" in os.environ and "GEMINI_API_KEY" not in os.environ:
    os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]

# Check for CLOUD_RUN environment variable to bypass interactive input prompts
CLOUD_RUN_MODE = os.environ.get("CLOUD_RUN") == "true"


# Check for API credentials and log errors if missing/placeholders
google_key = os.environ.get("GOOGLE_API_KEY")
if not google_key or google_key == "your_gemini_api_key_here":
    print("Error: GOOGLE_API_KEY is missing or invalid in your .env file.", file=sys.stderr)
    print("Please set a valid Gemini API key to run ContentOS.", file=sys.stderr)
    sys.exit(1)

mcp_key = os.environ.get("MCP_SEARCH_API_KEY")
if not mcp_key or mcp_key == "your_search_api_key_here":
    print("Error: MCP_SEARCH_API_KEY is missing or invalid in your .env file.", file=sys.stderr)
    print("The MCP search tool failed to initialize.", file=sys.stderr)
    sys.exit(1)

# Import ADK modules after env validation
try:
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types
    from agents.orchestrator import orchestrator
except ImportError as e:
    print(f"Error: Failed to import Google ADK libraries. {e}", file=sys.stderr)
    print("Please run 'pip install -r requirements.txt' first.", file=sys.stderr)
    sys.exit(1)


async def run_contentos_pipeline(topic: str):
    """Initializes session services, runs the orchestrator graph, and runs the HITL loop.

    Args:
        topic: The content prompt or video idea.
    """
    start_time = time.time()

    print("[ContentOS] Initializing ADK Session Service...")
    session_service = InMemorySessionService()

    print("[ContentOS] Initializing MCP web_search tool...")
    # The web_search tool has been successfully validated via the MCP_SEARCH_API_KEY check

    # Initialize the Runner
    runner = Runner(
        agent=orchestrator,
        app_name="agents",
        session_service=session_service,
        auto_create_session=True
    )

    session_id = "main_cli_session"
    user_id = "default_user"

    # Pack initial topic inside the user content message
    user_msg = types.Content(parts=[types.Part(text=topic)])

    print(f"\n[ContentOS] Starting pipeline for topic: '{topic}'")
    print("=" * 60)

    current_message = user_msg

    while True:
        try:
            # Run the agent pipeline
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=current_message
            ):
                # Print progress events cleanly
                if event.message:
                    print(f"[{event.author or 'Agent'}] {event.message}")
                elif event.node_info and event.node_info.name:
                    print(f"[Pipeline] Running node: {event.node_info.name}")
        except Exception as e:
            err_str = str(e)
            if "API_KEY_INVALID" in err_str or "invalid api key" in err_str.lower() or "400" in err_str:
                print(f"\nError: Gemini API authentication failed. The GOOGLE_API_KEY might be invalid.\nDetails: {e}", file=sys.stderr)
            else:
                print(f"\nError: Pipeline execution failed.\nDetails: {e}", file=sys.stderr)
            sys.exit(1)

        # Retrieve the updated session
        session = await session_service.get_session(
            app_name="agents",
            user_id=user_id,
            session_id=session_id
        )

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

        if not unresolved:
            # No unresolved interrupts, pipeline finished successfully
            break

        # Extract arguments from the unresolved request_review call
        unresolved_fc = unresolved[-1]
        args = unresolved_fc.args or {}

        # Present structured content package to user
        print("\n" + "=" * 60)
        print("  HUMAN-IN-THE-LOOP REVIEW GATE")
        print("=" * 60)
        print(f"Hook:               {args.get('hook', 'N/A')}")
        print(f"Word Count:         {args.get('word_count', 'N/A')}")
        print(f"Estimated Duration: {args.get('estimated_duration', 'N/A')}")
        print("Titles:")
        for idx, t in enumerate(args.get("titles", []), 1):
            print(f"  {idx}. {t}")
        print(f"Tags:               {', '.join(args.get('tags', []))}")
        print(f"Thumbnail Brief:    {args.get('thumbnail_brief', 'N/A')}")
        print(f"Sources Cited:      {', '.join(args.get('sources_cited', []))}")
        if args.get("unverified_claims_detected"):
            print("WARNING: Unverified claims detected in script! (Not backed by research brief)")
        print("=" * 60)

        # Prompt user choice
        if CLOUD_RUN_MODE:
            print("[ContentOS] CLOUD_RUN mode is active: automatically approving the content package.")
            choice = "1"
        else:
            print("\nSelect an action:")
            print("1. APPROVE - Save the content package to the output folder")
            print("2. REVISE  - Send feedback back to a subagent for revision")
            print("3. REJECT  - Terminate the pipeline and discard draft")

            choice = ""
            while choice not in ["1", "2", "3"]:
                choice = input("Enter choice (1-3): ").strip()


        if choice == "1":
            action = "APPROVE"
            response_content = "APPROVE"
        elif choice == "2":
            action = "REVISE"
            print("\nSelect target agent for revision:")
            print("1. ResearchAgent - Re-run from research stage")
            print("2. ScriptAgent   - Re-run script drafting and SEO")
            print("3. SEOAgent      - Re-run SEO package generation")
            agent_choice = ""
            while agent_choice not in ["1", "2", "3"]:
                agent_choice = input("Enter target (1-3): ").strip()

            target_agent = "ScriptAgent"
            if agent_choice == "1":
                target_agent = "ResearchAgent"
            elif agent_choice == "2":
                target_agent = "ScriptAgent"
            elif agent_choice == "3":
                target_agent = "SEOAgent"

            notes = input("Enter revision notes/feedback: ").strip()
            response_content = f"REVISE: target={target_agent}, notes={notes}"
        else:
            action = "REJECT"
            response_content = "REJECT"

        # Create function response message to resume execution
        current_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=unresolved_fc.id,
                        name="request_review",
                        response={"result": response_content}
                    )
                )
            ]
        )
        print(f"\nResuming pipeline execution with choice: {action}...\n")

    # Pipeline finished: Display Summary
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
    print("  CONTENTOS PIPELINE RUN SUMMARY")
    print("=" * 60)
    print(f"Topic Processed:    {topic}")
    print(f"Status:             {status.upper()}")
    if saved_dir:
        print(f"Output Folder:      {saved_dir}")
    print(f"Script Word Count:  {word_count}")
    print("Titles Generated:")
    for idx, t in enumerate(titles, 1):
        print(f"  {idx}. {t}")
    print(f"Total Time:         {total_time:.2f} seconds")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    # Check for command line argument or prompt interactively
    if len(sys.argv) > 1:
        topic_arg = sys.argv[1].strip()
        if not topic_arg:
            print("Error: Empty topic string provided.", file=sys.stderr)
            sys.exit(1)
    elif CLOUD_RUN_MODE:
        topic_arg = os.environ.get("CONTENT_TOPIC", "AI Content Operations System").strip()
        print(f"[ContentOS] Running in CLOUD_RUN mode: using topic from environment/default: '{topic_arg}'")
    else:
        topic_arg = input("Enter video idea/prompt: ").strip()
        if not topic_arg:
            print("Error: Video topic cannot be empty.", file=sys.stderr)
            sys.exit(1)

    # Run the async pipeline loop
    asyncio.run(run_contentos_pipeline(topic_arg))
