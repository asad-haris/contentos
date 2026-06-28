"""Flask frontend app for ContentOS.

Provides a premium dashboard to visualize the multi-agent production pipeline in real-time.
"""

import os
import sys
import uuid
import time
import asyncio
import threading
from flask import Flask, render_template_string, request, jsonify
from dotenv import load_dotenv

load_dotenv()

# Map GOOGLE_API_KEY to GEMINI_API_KEY to force Developer API backend in Cloud Run
if "GOOGLE_API_KEY" in os.environ and "GEMINI_API_KEY" not in os.environ:
    os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]

app = Flask(__name__)

# Validate credentials
google_key = os.environ.get("GOOGLE_API_KEY")
if not google_key or google_key == "your_gemini_api_key_here":
    print("Warning: GOOGLE_API_KEY is missing or invalid. Live runs will fail.", file=sys.stderr)

try:
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types
    from google.adk.models import Gemini
    from agents.orchestrator import orchestrator
except ImportError as e:
    print(f"Error: Failed to import Google ADK libraries. {e}", file=sys.stderr)
    print("Please run 'pip install -r requirements.txt' first.", file=sys.stderr)
    sys.exit(1)

# Enable mock patching if requested or if credentials are empty/placeholder
mock_mode = os.environ.get("MOCK_PIPELINE", "false").lower() == "true" or not google_key or google_key == "your_gemini_api_key_here"
if mock_mode:
    print("WARNING: MOCK_MODE is enabled. All Gemini API calls will be mocked using evals.mock_data.", file=sys.stderr)
    try:
        from evals.mock_data import mock_generate_content_async
        Gemini.generate_content_async = mock_generate_content_async
    except Exception as e:
        print(f"Error enabling mock mode: {e}", file=sys.stderr)

# Global session store
SESSIONS = {}

def cleanup_old_sessions():
    """Removes sessions older than 30 minutes (1800 seconds) from the in-memory SESSIONS dict."""
    now = time.time()
    expired = []
    for sid, sdata in list(SESSIONS.items()):
        created = sdata.get("created_at", now)
        if now - created > 1800:
            expired.append(sid)
    for sid in expired:
        try:
            del SESSIONS[sid]
        except KeyError:
            pass

# Background event loop for running async ADK runners
background_loop = asyncio.new_event_loop()

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

loop_thread = threading.Thread(target=start_background_loop, args=(background_loop,), daemon=True)
loop_thread.start()

def to_dict(obj):
    """Helper to convert Pydantic or complex objects to dictionaries for JSON serialization."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif hasattr(obj, "dict"):
        return obj.dict()
    elif isinstance(obj, list):
        return [to_dict(x) for x in obj]
    elif isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj

async def run_pipeline(session_id, topic):
    loop = asyncio.get_running_loop()
    try:
        session_service = InMemorySessionService()
        runner = Runner(
            agent=orchestrator,
            app_name="agents",
            session_service=session_service,
            auto_create_session=True
        )
        
        user_id = "default_user"
        current_message = types.Content(parts=[types.Part(text=topic)])
        
        while True:
            try:
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=current_message
                ):
                    # Track progress
                    if event.node_info and event.node_info.name:
                        SESSIONS[session_id]["current_node"] = event.node_info.name
                        
                    # Periodically extract data from session state
                    session = await session_service.get_session(
                        app_name="agents",
                        user_id=user_id,
                        session_id=session_id
                    )
                    if session.state:
                        if "research_brief" in session.state:
                            SESSIONS[session_id]["research_brief"] = to_dict(session.state["research_brief"])
                        if "script_package" in session.state:
                            SESSIONS[session_id]["script_package"] = to_dict(session.state["script_package"])
                        if "seo_package" in session.state:
                            SESSIONS[session_id]["seo_package"] = to_dict(session.state["seo_package"])
            except Exception as e:
                SESSIONS[session_id]["status"] = "error"
                SESSIONS[session_id]["error_message"] = str(e)
                print(f"Error in pipeline {session_id}: {e}", file=sys.stderr)
                return

            # Retrieve final session to scan for unresolved calls
            session = await session_service.get_session(
                app_name="agents",
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

            if not unresolved:
                # Execution finished successfully
                break
                
            unresolved_fc = unresolved[-1]
            SESSIONS[session_id]["status"] = "waiting_for_review"
            SESSIONS[session_id]["current_node"] = "ReviewAgent"
            SESSIONS[session_id]["review_args"] = unresolved_fc.args or {}
            
            # Block until user action event is set
            SESSIONS[session_id]["resume_event"].clear()
            await loop.run_in_executor(None, SESSIONS[session_id]["resume_event"].wait)
            
            # Read selection from state
            action = SESSIONS[session_id]["user_action"]
            if action == "APPROVE":
                response_content = "APPROVE"
            elif action == "REVISE":
                target_agent = SESSIONS[session_id].get("user_target", "ScriptAgent")
                notes = SESSIONS[session_id].get("user_notes", "")
                response_content = f"REVISE: target={target_agent}, notes={notes}"
            else:
                response_content = "REJECT"
                
            # Create response and loop back
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
            SESSIONS[session_id]["status"] = "running"
            
        # Final exit summary mapping
        orchestrator_output = session.state.get("orchestrator_output", {})
        if hasattr(orchestrator_output, "model_dump"):
            orchestrator_output = orchestrator_output.model_dump()
            
        status = orchestrator_output.get("status", "completed")
        SESSIONS[session_id]["status"] = status
        SESSIONS[session_id]["saved_directory"] = orchestrator_output.get("saved_directory")
        SESSIONS[session_id]["current_node"] = None
        
    except Exception as e:
        SESSIONS[session_id]["status"] = "error"
        SESSIONS[session_id]["error_message"] = str(e)
        print(f"Global pipeline exception {session_id}: {e}", file=sys.stderr)

# Premium Brutalist Minimalist HTML/CSS UI Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CONTENTOS</title>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
    <!-- marked.js for premium markdown script rendering -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg: #0a0a0a;
            --fg: #f0f0f0;
            --accent: #ffffff;
            --highlight: #7c6af7;
            --border: #222222;
            --border-hover: #ffffff;
            --dim: #555555;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            border-radius: 0 !important; /* brutalist: strictly no rounded corners */
        }

        body {
            background-color: var(--bg);
            color: var(--fg);
            font-family: 'Space Grotesk', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 14px;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }

        /* Utility style for section headers */
        .label {
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 0.2em;
            color: var(--dim);
            font-weight: 700;
            margin-bottom: 0.75rem;
            display: block;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border);
            height: 60px;
        }

        header h1 {
            font-size: 1.25rem;
            font-weight: 700;
            letter-spacing: 0.1em;
        }

        .header-tag {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.7rem;
            color: var(--dim);
        }

        /* Layout Grid */
        .main-layout {
            display: flex;
            flex: 1;
            height: calc(100vh - 60px);
            overflow: hidden;
        }

        .panel-left {
            width: 40%;
            border-right: 1px solid var(--border);
            padding: 2rem;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            gap: 2.5rem;
        }

        .panel-right {
            width: 60%;
            padding: 2rem;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            position: relative;
        }

        /* Input section styling */
        textarea {
            width: 100%;
            background-color: #111111;
            border: 1px solid var(--border);
            color: var(--fg);
            font-family: inherit;
            font-size: 1rem;
            padding: 1rem;
            resize: none;
            outline: none;
            transition: border-color 0.2s;
        }

        textarea:focus {
            border-color: var(--border-hover);
        }

        button {
            display: block;
            width: 100%;
            background-color: var(--accent);
            color: #000000;
            border: 1px solid var(--accent);
            padding: 1rem;
            font-family: inherit;
            font-weight: 700;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            cursor: pointer;
            transition: all 0.2s;
        }

        button:hover {
            background-color: var(--bg);
            color: var(--accent);
            border-color: var(--accent);
        }

        button:disabled {
            background-color: var(--border);
            color: var(--dim);
            border-color: var(--border);
            cursor: not-allowed;
        }

        .status-text {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: var(--highlight);
            text-transform: uppercase;
        }

        /* Agent status list */
        .agent-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .agent-row {
            display: flex;
            align-items: center;
            padding: 1rem;
            border: 1px solid var(--border);
            background-color: #0d0d0d;
        }

        .agent-status-dot {
            width: 8px;
            height: 8px;
            margin-right: 1rem;
            background-color: #333333; /* default idle */
        }

        .agent-status-dot.active {
            background-color: #eab308; /* yellow */
            box-shadow: 0 0 8px #eab308;
        }

        .agent-status-dot.done {
            background-color: #22c55e; /* green */
            box-shadow: 0 0 8px #22c55e;
        }

        .agent-status-dot.failed {
            background-color: #ef4444; /* red */
            box-shadow: 0 0 8px #ef4444;
        }

        .agent-name-label {
            font-weight: 700;
            font-size: 0.8rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }

        .view-link {
            margin-left: auto;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.7rem;
            color: var(--highlight);
            text-decoration: none;
            text-transform: uppercase;
            border-bottom: 1px dashed var(--highlight);
            cursor: pointer;
        }

        .view-link:hover {
            color: var(--accent);
            border-bottom-style: solid;
        }

        /* Right panel content states */
        .state-empty {
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            flex: 1;
            color: var(--dim);
            font-family: 'JetBrains Mono', monospace;
            font-size: 1rem;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .review-card {
            display: none;
            flex-direction: column;
            gap: 1.5rem;
            animation: fadeIn 0.3s;
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        .hook-text {
            font-size: 1.5rem;
            font-weight: 700;
            line-height: 1.4;
            color: #ffffff;
            border-left: 4px solid var(--highlight);
            padding-left: 1.5rem;
            margin: 0.5rem 0;
        }

        .metadata-row {
            display: flex;
            gap: 2rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: var(--dim);
        }

        .titles-list {
            list-style-type: none;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .titles-list li {
            padding: 0.75rem 1rem;
            background-color: #111111;
            border-left: 2px solid var(--accent);
            font-size: 0.95rem;
        }

        .tags-container {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }

        .tag-chip {
            background-color: var(--bg);
            border: 1px solid var(--border);
            padding: 0.4rem 0.8rem;
            font-size: 0.75rem;
            font-family: 'JetBrains Mono', monospace;
            color: var(--fg);
        }

        .brief-block {
            border: 1px solid var(--border);
            background-color: #0f0f0f;
            padding: 1.5rem;
            font-size: 0.9rem;
            line-height: 1.6;
        }

        .sources-list {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
        }

        .source-a {
            color: var(--highlight);
            text-decoration: none;
            word-break: break-all;
        }

        .source-a:hover {
            color: var(--accent);
            text-decoration: underline;
        }

        .review-button-row {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
        }

        .btn-approve {
            background-color: #22c55e;
            border-color: #22c55e;
            color: #ffffff;
        }

        .btn-approve:hover {
            background-color: var(--bg);
            color: #22c55e;
        }

        .btn-reject {
            background-color: #ef4444;
            border-color: #ef4444;
            color: #ffffff;
            width: 30%;
        }

        .btn-reject:hover {
            background-color: var(--bg);
            color: #ef4444;
        }

        .revision-form {
            border-top: 1px solid var(--border);
            padding-top: 1.5rem;
            margin-top: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .select-target {
            width: 100%;
            background-color: #111111;
            border: 1px solid var(--border);
            color: var(--fg);
            padding: 0.75rem;
            outline: none;
            font-family: inherit;
        }

        .btn-revise {
            background-color: var(--highlight);
            border-color: var(--highlight);
            color: #ffffff;
        }

        .btn-revise:hover {
            background-color: var(--bg);
            color: var(--highlight);
        }

        /* Modal Overlay */
        .modal {
            display: none;
            position: fixed;
            z-index: 100;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.85);
            backdrop-filter: blur(4px);
        }

        .modal-content {
            background-color: var(--bg);
            border: 1px solid var(--border);
            width: 80%;
            max-width: 800px;
            margin: 5% auto;
            display: flex;
            flex-direction: column;
            height: 80vh;
        }

        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border);
        }

        .modal-title {
            font-size: 1rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-weight: 700;
        }

        .modal-close {
            background: none;
            border: none;
            color: var(--fg);
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0.25rem;
            width: auto;
        }

        .modal-close:hover {
            color: var(--highlight);
        }

        .modal-body {
            flex: 1;
            overflow-y: auto;
            padding: 2rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
            line-height: 1.7;
            white-space: pre-wrap;
        }

        /* Markdown styling inside Modal */
        .markdown-output {
            white-space: normal;
            font-family: inherit;
        }

        .markdown-output h1, .markdown-output h2, .markdown-output h3 {
            margin: 1.5rem 0 0.75rem 0;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #ffffff;
        }

        .markdown-output h1 { font-size: 1.2rem; }
        .markdown-output h2 { font-size: 1rem; }
        .markdown-output p {
            margin-bottom: 1rem;
            color: #d0d0d0;
        }
    </style>
</head>
<body>
    <header>
        <h1>CONTENTOS</h1>
        <div class="header-tag">Google ADK 2.0 • Multi-Agent System</div>
    </header>

    <div class="main-layout">
        <!-- LEFT PANEL -->
        <div class="panel-left">
            <div>
                <span class="label">INPUT</span>
                <textarea id="prompt" rows="4" placeholder="Enter topic / idea prompt..."></textarea>
                <button id="submit-btn" style="margin-top: 1rem;" onclick="startRealProduction()">GENERATE →</button>
                <div style="margin-top: 0.75rem; display: flex; justify-content: space-between; align-items: center;">
                    <span class="label" style="margin-bottom: 0;">Status:</span>
                    <span id="pipeline-status" class="status-text">IDLE</span>
                </div>
            </div>

            <div id="status-panel" style="display: none; flex-direction: column; gap: 0.5rem; flex: 1;">
                <span class="label">PIPELINE STATUS</span>
                <div class="agent-list">
                    <div id="node-orchestrator" class="agent-row">
                        <div id="dot-orchestrator" class="agent-status-dot"></div>
                        <span class="agent-name-label">Orchestrator Agent</span>
                        <span id="view-orchestrator" class="view-link" style="display: none;" onclick="viewNodeOutput('OrchestratorAgent')">VIEW OUTPUT</span>
                    </div>
                    <div id="node-research" class="agent-row">
                        <div id="dot-research" class="agent-status-dot"></div>
                        <span class="agent-name-label">Research Agent</span>
                        <span id="view-research" class="view-link" style="display: none;" onclick="viewNodeOutput('ResearchAgent')">VIEW OUTPUT</span>
                    </div>
                    <div id="node-script" class="agent-row">
                        <div id="dot-script" class="agent-status-dot"></div>
                        <span class="agent-name-label">Script Agent</span>
                        <span id="view-script" class="view-link" style="display: none;" onclick="viewNodeOutput('ScriptAgent')">VIEW OUTPUT</span>
                    </div>
                    <div id="node-seo" class="agent-row">
                        <div id="dot-seo" class="agent-status-dot"></div>
                        <span class="agent-name-label">SEO Agent</span>
                        <span id="view-seo" class="view-link" style="display: none;" onclick="viewNodeOutput('SEOAgent')">VIEW OUTPUT</span>
                    </div>
                    <div id="node-review" class="agent-row">
                        <div id="dot-review" class="agent-status-dot"></div>
                        <span class="agent-name-label">Review Agent</span>
                        <span id="view-review" class="view-link" style="display: none;" onclick="viewNodeOutput('ReviewAgent')">VIEW OUTPUT</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- RIGHT PANEL -->
        <div class="panel-right">
            <div id="state-empty" class="state-empty">
                AWAITING INPUT
            </div>

            <!-- HITL Review Gate Panel -->
            <div id="review-panel" class="review-card">
                <div>
                    <span class="label">HUMAN REVIEW REQUIRED</span>
                    <div id="review-warning" style="display: none;"></div>
                    <div id="review-hook" class="hook-text"></div>
                    <div class="metadata-row" style="margin-top: 1rem;">
                        <span id="review-wordcount"></span>
                        <span id="review-duration"></span>
                    </div>
                </div>

                <div>
                    <span class="label">SEO TITLE SUGGESTIONS</span>
                    <ol id="review-titles" class="titles-list"></ol>
                </div>

                <div>
                    <span class="label">SEO TAGS</span>
                    <div id="review-tags" class="tags-container"></div>
                </div>

                <div>
                    <span class="label">THUMBNAIL BRIEF</span>
                    <div id="review-thumbnail" class="brief-block"></div>
                </div>

                <div>
                    <span class="label">SOURCES CITED</span>
                    <div id="review-sources" class="sources-list"></div>
                </div>

                <div class="review-button-row">
                    <button class="btn-approve" onclick="submitReviewAction('APPROVE')">APPROVE →</button>
                    <button class="btn-reject" onclick="submitReviewAction('REJECT')">REJECT</button>
                </div>

                <div class="revision-form">
                    <span class="label">REQUEST REVISION</span>
                    <select id="revision-target" class="select-target">
                        <option value="ResearchAgent">ResearchAgent (Re-run from Research stage)</option>
                        <option value="ScriptAgent" selected>ScriptAgent (Re-draft script & SEO)</option>
                        <option value="SEOAgent">SEOAgent (Regenerate titles/tags only)</option>
                    </select>
                    <textarea id="revision-notes" rows="3" placeholder="Specify changes required..."></textarea>
                    <button class="btn-revise" onclick="submitReviewAction('REVISE')">SEND BACK</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Detail Modal -->
    <div id="detail-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modal-title" class="modal-title">Agent Output</h2>
                <button class="modal-close" onclick="closeModal()">✕</button>
            </div>
            <div id="modal-body" class="modal-body"></div>
        </div>
    </div>

    <script>
        let currentSessionId = null;
        let pollInterval = null;
        let currentSessionData = null;

        function startRealProduction() {
            const prompt = document.getElementById("prompt").value.trim();
            if (!prompt) return alert("Please enter a prompt.");
            
            // Clear any active polling and local storage state
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
            localStorage.removeItem("contentos_session_id");
            currentSessionId = null;
            
            document.getElementById("submit-btn").disabled = true;
            document.getElementById("submit-btn").innerText = "INITIALIZING...";
            document.getElementById("status-panel").style.display = "flex";
            document.getElementById("review-panel").style.display = "none";
            document.getElementById("state-empty").style.display = "flex";
            document.getElementById("state-empty").innerText = "PIPELINE RUNNING...";
            document.getElementById("pipeline-status").innerText = "RUNNING";
            document.getElementById("pipeline-status").style.color = "var(--highlight)";

            // Reset UI nodes
            const steps = ['orchestrator', 'research', 'script', 'seo', 'review'];
            steps.forEach(s => {
                document.getElementById(`dot-${s}`).className = 'agent-status-dot';
                document.getElementById(`view-${s}`).style.display = 'none';
            });
            
            fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: prompt })
            })
            .then(res => res.json())
            .then(data => {
                if (data.error) {
                    alert("Error launching pipeline: " + data.error);
                    resetLaunchButton();
                    return;
                }
                currentSessionId = data.session_id;
                localStorage.setItem("contentos_session_id", currentSessionId);
                document.getElementById("submit-btn").innerText = "GENERATING...";
                // Start polling
                pollInterval = setInterval(pollSessionStatus, 1500);
            })
            .catch(err => {
                alert("Failed to connect to backend api.");
                resetLaunchButton();
            });
        }

        function resetLaunchButton() {
            document.getElementById("submit-btn").disabled = false;
            document.getElementById("submit-btn").innerText = "GENERATE →";
        }

        function pollSessionStatus() {
            if (!currentSessionId) return;
            
            fetch(`/api/session/${currentSessionId}`)
            .then(res => {
                if (!res.ok) {
                    throw new Error("Session invalid or not found");
                }
                return res.json();
            })
            .then(data => {
                currentSessionData = data;
                updatePipelineUI(data);
            })
            .catch(err => {
                console.error("Error polling session: ", err);
                // Clear stuck state if session doesn't exist or is invalid
                if (pollInterval) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                }
                localStorage.removeItem("contentos_session_id");
                currentSessionId = null;
                resetLaunchButton();
                document.getElementById("pipeline-status").innerText = "IDLE";
                document.getElementById("pipeline-status").style.color = "var(--dim)";
                document.getElementById("state-empty").style.display = "flex";
                document.getElementById("state-empty").innerText = "AWAITING INPUT";
                document.getElementById("status-panel").style.display = "none";
            });
        }

        function updatePipelineUI(session) {
            const steps = [
                { name: 'OrchestratorAgent', id: 'orchestrator' },
                { name: 'ResearchAgent', id: 'research' },
                { name: 'ScriptAgent', id: 'script' },
                { name: 'SEOAgent', id: 'seo' },
                { name: 'ReviewAgent', id: 'review' }
            ];

            const currentNodeName = session.current_node;
            
            // Mark completed nodes based on output availability
            if (session.research_brief) {
                document.getElementById('dot-research').className = 'agent-status-dot done';
                document.getElementById('view-research').style.display = 'inline-block';
                document.getElementById('dot-orchestrator').className = 'agent-status-dot done';
                document.getElementById('view-orchestrator').style.display = 'inline-block';
            }
            if (session.script_package) {
                document.getElementById('dot-script').className = 'agent-status-dot done';
                document.getElementById('view-script').style.display = 'inline-block';
            }
            if (session.seo_package) {
                document.getElementById('dot-seo').className = 'agent-status-dot done';
                document.getElementById('view-seo').style.display = 'inline-block';
            }
            
            // Set active dot
            if (currentNodeName) {
                steps.forEach(step => {
                    if (step.name === currentNodeName) {
                        document.getElementById(`dot-${step.id}`).className = 'agent-status-dot active';
                    }
                });
            }

            // Handle statuses
            if (session.status === "waiting_for_review") {
                document.getElementById('dot-review').className = 'agent-status-dot active';
                document.getElementById('view-review').style.display = 'inline-block';
                document.getElementById("pipeline-status").innerText = "AWAITING HUMAN REVIEW";
                document.getElementById("pipeline-status").style.color = "var(--highlight)";
                
                showReviewPanel(session.review_args);
            } else if (session.status === "approved" || session.status === "completed") {
                clearInterval(pollInterval);
                document.getElementById('dot-review').className = 'agent-status-dot done';
                document.getElementById('view-review').style.display = 'inline-block';
                document.getElementById("pipeline-status").innerText = "APPROVED & COMPLETED";
                document.getElementById("pipeline-status").style.color = "#22c55e";
                document.getElementById("review-panel").style.display = "none";
                document.getElementById("state-empty").style.display = "flex";
                document.getElementById("state-empty").innerText = "PIPELINE COMPLETED - APPROVED";
                resetLaunchButton();
                
                alert(`Content generation successfully approved! Output folder:\n${session.saved_directory}`);
            } else if (session.status === "rejected") {
                clearInterval(pollInterval);
                document.getElementById("pipeline-status").innerText = "REJECTED";
                document.getElementById("pipeline-status").style.color = "#ef4444";
                document.getElementById("review-panel").style.display = "none";
                document.getElementById("state-empty").style.display = "flex";
                document.getElementById("state-empty").innerText = "PIPELINE TERMINATED - REJECTED";
                resetLaunchButton();
                
                alert("Content package draft was rejected.");
            } else if (session.status === "error") {
                clearInterval(pollInterval);
                document.getElementById("pipeline-status").innerText = "ERROR";
                document.getElementById("pipeline-status").style.color = "#ef4444";
                document.getElementById("review-panel").style.display = "none";
                document.getElementById("state-empty").style.display = "flex";
                document.getElementById("state-empty").innerText = "PIPELINE FAILED - ERROR";
                resetLaunchButton();
                
                alert("Execution error occurred: " + session.error_message);
            }
        }

        function showReviewPanel(args) {
            document.getElementById("state-empty").style.display = "none";
            const panel = document.getElementById("review-panel");
            if (panel.style.display === "flex") return; 
            
            // Warnings
            const warningEl = document.getElementById("review-warning");
            if (args.unverified_claims_detected) {
                warningEl.style.display = "block";
                warningEl.innerHTML = `<div style="color: #ef4444; border: 1px solid #ef4444; background: rgba(239, 68, 68, 0.05); padding: 1rem; margin-bottom: 1.5rem; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.05em;">
                                        ⚠️ WARNING: UNVERIFIED CLAIMS DETECTED IN SCRIPT (NOT BACKED BY SOURCES)
                                       </div>`;
            } else {
                warningEl.style.display = "none";
            }
            
            document.getElementById("review-hook").innerText = args.hook || 'N/A';
            document.getElementById("review-wordcount").innerText = `WORD COUNT: ${args.word_count || 'N/A'}`;
            document.getElementById("review-duration").innerText = `EST. DURATION: ${args.estimated_duration || 'N/A'}`;
            
            // Titles
            const titlesOl = document.getElementById("review-titles");
            titlesOl.innerHTML = "";
            (args.titles || []).forEach(t => {
                const li = document.createElement("li");
                li.innerText = t;
                titlesOl.appendChild(li);
            });
            
            // Tags
            const tagsDiv = document.getElementById("review-tags");
            tagsDiv.innerHTML = "";
            (args.tags || []).forEach(tag => {
                const span = document.createElement("span");
                span.className = "tag-chip";
                span.innerText = tag;
                tagsDiv.appendChild(span);
            });
            
            document.getElementById("review-thumbnail").innerText = args.thumbnail_brief || 'N/A';
            
            // Sources
            const sourcesDiv = document.getElementById("review-sources");
            sourcesDiv.innerHTML = "";
            (args.sources_cited || []).forEach(src => {
                const a = document.createElement("a");
                a.href = src;
                a.target = "_blank";
                a.className = "source-a";
                a.innerText = src;
                sourcesDiv.appendChild(a);
            });
            
            panel.style.display = "flex";
        }

        function submitReviewAction(action) {
            if (!currentSessionId) return;
            
            const notes = document.getElementById("revision-notes").value;
            const target = document.getElementById("revision-target").value;
            
            fetch(`/api/session/${currentSessionId}/action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action, notes: notes, target: target })
            })
            .then(res => {
                if (!res.ok) {
                    throw new Error("Action failed. Session might have expired.");
                }
                return res.json();
            })
            .then(data => {
                if (data.success) {
                    document.getElementById("review-panel").style.display = "none";
                    document.getElementById("state-empty").style.display = "flex";
                    document.getElementById("revision-notes").value = "";
                    if (action === "REVISE") {
                        document.getElementById("pipeline-status").innerText = "ROUTING REVISION...";
                        document.getElementById("state-empty").innerText = "ROUTING REVISION BACK...";
                    }
                } else {
                    alert("Action failed: " + data.error);
                }
            })
            .catch(err => alert("Failed to connect to API: " + err.message));
        }

        function closeModal() {
            document.getElementById("detail-modal").style.display = "none";
        }

        function viewNodeOutput(nodeName) {
            if (!currentSessionData) return;
            
            const titleEl = document.getElementById("modal-title");
            const bodyEl = document.getElementById("modal-body");
            
            bodyEl.className = "modal-body";
            
            if (nodeName === 'OrchestratorAgent') {
                titleEl.innerText = "ORCHESTRATOR CONFIGURATION";
                bodyEl.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 1rem;">
                        <div><strong>SESSION ID:</strong> ${currentSessionId}</div>
                        <div><strong>TOPIC IDEA:</strong> ${currentSessionData.topic}</div>
                        <div><strong>CURRENT STATUS:</strong> ${currentSessionData.status.toUpperCase()}</div>
                    </div>
                `;
            } else if (nodeName === 'ResearchAgent') {
                titleEl.innerText = "RESEARCH AGENT BRIEF & SOURCES";
                const brief = currentSessionData.research_brief || {};
                
                let sourcesHtml = "";
                const sources = brief.sources || [];
                if (sources.length === 0) {
                    sourcesHtml = "<div>No sources found.</div>";
                } else {
                    sources.forEach(src => {
                        sourcesHtml += `
                            <div style="border: 1px solid var(--border); padding: 1rem; margin-bottom: 1rem; background-color: #0f0f0f;">
                                <div style="font-weight: 700; margin-bottom: 0.5rem; text-transform: uppercase;">${src.title || 'Source'}</div>
                                <a href="${src.url}" target="_blank" class="source-a">${src.url}</a>
                                <div style="color: var(--dim); font-size: 0.8rem; margin-top: 0.5rem; font-family: sans-serif;">${src.snippet || ''}</div>
                            </div>
                        `;
                    });
                }
                
                bodyEl.innerHTML = `
                    <div style="margin-bottom: 2rem;">
                        <span class="label">Research Summary</span>
                        <div style="line-height: 1.6; font-family: sans-serif; font-size: 0.95rem;">${brief.summary || 'No summary compiled.'}</div>
                    </div>
                    <div>
                        <span class="label">Verified Web Sources</span>
                        ${sourcesHtml}
                    </div>
                `;
            } else if (nodeName === 'ScriptAgent') {
                titleEl.innerText = "SCRIPT AGENT NARRATION DRAFT";
                const scriptPkg = currentSessionData.script_package || {};
                const markdownContent = scriptPkg.content || "*No script draft created yet.*";
                
                bodyEl.className = "modal-body markdown-output";
                bodyEl.innerHTML = `
                    <div style="display: flex; gap: 2rem; margin-bottom: 2rem; border: 1px solid var(--border); padding: 1rem; background-color: #0f0f0f;">
                        <div><strong>WORD COUNT:</strong> ${scriptPkg.word_count || 'N/A'}</div>
                        <div><strong>EST. DURATION:</strong> ${scriptPkg.estimated_duration || 'N/A'}</div>
                    </div>
                    <div>
                        <span class="label">Draft Script Markdown</span>
                        <div style="line-height: 1.6; font-family: sans-serif; font-size: 0.95rem;">
                            ${marked.parse(markdownContent)}
                        </div>
                    </div>
                `;
            } else if (nodeName === 'SEOAgent') {
                titleEl.innerText = "SEO AGENT METADATA PACKAGE";
                const seoPkg = currentSessionData.seo_package || {};
                
                let titlesList = "";
                (seoPkg.titles || []).forEach((t, i) => {
                    titlesList += `<li style="padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-family: sans-serif;">${t}</li>`;
                });
                
                bodyEl.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 2rem;">
                        <div>
                            <span class="label">Suggested Video Titles</span>
                            <ol style="padding-left: 1.5rem;">${titlesList || '<li>No titles generated.</li>'}</ol>
                        </div>
                        <div>
                            <span class="label">Video Tags</span>
                            <div>${(seoPkg.tags || []).join(', ') || 'No tags generated.'}</div>
                        </div>
                        <div>
                            <span class="label">Thumbnail Design Brief</span>
                            <div style="font-family: sans-serif; line-height: 1.6;">${seoPkg.thumbnail_brief || 'No thumbnail description generated.'}</div>
                        </div>
                        <div>
                            <span class="label">Video Description</span>
                            <div style="background-color: #0f0f0f; border: 1px solid var(--border); padding: 1.5rem; font-family: sans-serif; font-size: 0.9rem; line-height: 1.6;">${seoPkg.description || 'No description generated.'}</div>
                        </div>
                    </div>
                `;
            } else if (nodeName === 'ReviewAgent') {
                titleEl.innerText = "REVIEW AGENT AUDIT LOGS";
                bodyEl.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 1rem;">
                        <div><strong>APPROVAL STATUS:</strong> ${currentSessionData.status.toUpperCase()}</div>
                        ${currentSessionData.saved_directory ? `<div><strong>SAVED DIRECTORY:</strong> ${currentSessionData.saved_directory}</div>` : ''}
                    </div>
                `;
            }
            
            document.getElementById("detail-modal").style.display = "block";
        }

        document.addEventListener("DOMContentLoaded", () => {
            // Check if there is an active session in progress on page load
            const savedSessionId = localStorage.getItem("contentos_session_id");
            if (savedSessionId) {
                currentSessionId = savedSessionId;
                document.getElementById("submit-btn").disabled = true;
                document.getElementById("submit-btn").innerText = "GENERATING...";
                document.getElementById("status-panel").style.display = "flex";
                document.getElementById("state-empty").innerText = "PIPELINE RUNNING...";
                
                // Trigger immediate poll and resume interval
                pollSessionStatus();
                pollInterval = setInterval(pollSessionStatus, 1500);
            }
        });
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/generate", methods=["POST"])
def generate():
    cleanup_old_sessions()
    data = request.get_json() or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
        
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "created_at": time.time(),
        "status": "running",
        "topic": prompt,
        "current_node": "OrchestratorAgent",
        "research_brief": None,
        "script_package": None,
        "seo_package": None,
        "resume_event": threading.Event(),
        "user_action": None,
        "user_notes": None,
        "user_target": None,
        "review_args": None,
        "saved_directory": None,
        "error_message": None
    }
    
    asyncio.run_coroutine_threadsafe(run_pipeline(session_id, prompt), background_loop)
    return jsonify({"session_id": session_id})

@app.route("/status/<session_id>", methods=["GET"])
@app.route("/api/session/<session_id>", methods=["GET"])
def get_session(session_id):
    cleanup_old_sessions()
    session_data = SESSIONS.get(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
        
    resp = {
        "session_id": session_id,
        "status": session_data["status"],
        "topic": session_data["topic"],
        "current_node": session_data["current_node"],
        "research_brief": session_data["research_brief"],
        "script_package": session_data["script_package"],
        "seo_package": session_data["seo_package"],
        "review_args": session_data["review_args"],
        "saved_directory": session_data["saved_directory"],
        "error_message": session_data["error_message"]
    }
    return jsonify(resp)

@app.route("/api/session/<session_id>/action", methods=["POST"])
def session_action(session_id):
    cleanup_old_sessions()
    session_data = SESSIONS.get(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
        
    data = request.get_json() or {}
    action = data.get("action", "").upper()
    if action not in ["APPROVE", "REVISE", "REJECT"]:
        return jsonify({"error": "Invalid action. Must be APPROVE, REVISE, or REJECT"}), 400
        
    session_data["user_action"] = action
    session_data["user_notes"] = data.get("notes", "")
    session_data["user_target"] = data.get("target", "ScriptAgent")
    
    session_data["resume_event"].set()
    return jsonify({"success": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask server on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
