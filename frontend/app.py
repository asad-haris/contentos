"""Flask frontend app for ContentOS.

Provides a premium dashboard to visualize the multi-agent production pipeline in real-time.
"""

import os
import sys
import uuid
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

# Premium Responsive HTML/CSS UI Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ContentOS - Multi-Agent Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <!-- marked.js for premium markdown script rendering -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-primary: #0a0c10;
            --bg-secondary: #121620;
            --accent-color: #6366f1;
            --accent-hover: #4f46e5;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --border-color: #1e293b;
        }
        body {
            margin: 0;
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            min-height: 100vh;
        }
        header {
            border-bottom: 1px solid var(--border-color);
            padding: 1.5rem 2rem;
            display: flex;
            justify-between: space-between;
            align-items: center;
            background: rgba(18, 22, 32, 0.8);
            backdrop-filter: blur(12px);
            position: sticky;
            top: 0;
            z-index: 10;
        }
        .header-title-container {
            display: flex;
            flex-direction: column;
        }
        h1 {
            margin: 0;
            font-size: 1.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a5b4fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .container {
            max-width: 1000px;
            margin: 3rem auto;
            padding: 0 1.5rem;
            flex-grow: 1;
        }
        .card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2.5rem;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            margin-bottom: 2rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: var(--text-muted);
        }
        textarea, input, select {
            width: 100%;
            background: #07090e;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            color: var(--text-main);
            font-family: inherit;
            font-size: 1rem;
            box-sizing: border-box;
            transition: border-color 0.2s;
        }
        textarea:focus, input:focus, select:focus {
            outline: none;
            border-color: var(--accent-color);
        }
        button {
            background: var(--accent-color);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 1rem 2rem;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s, transform 0.1s;
        }
        button:hover {
            background: var(--accent-hover);
        }
        button:active {
            transform: scale(0.98);
        }
        .status-panel {
            margin-top: 2rem;
            display: none;
        }
        .agent-node {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem;
            background: #0d1117;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            margin-bottom: 0.75rem;
            transition: transform 0.2s, border-color 0.2s;
        }
        .agent-node.clickable {
            cursor: pointer;
            border-color: rgba(99, 102, 241, 0.4);
        }
        .agent-node.clickable:hover {
            transform: translateX(5px);
            border-color: var(--accent-color);
            background: #161b26;
        }
        .agent-status {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: var(--text-muted);
            transition: all 0.3s;
        }
        .agent-status.active {
            background: #eab308;
            box-shadow: 0 0 10px #eab308;
            animation: pulse-yellow 1.5s infinite;
        }
        .agent-status.done {
            background: #22c55e;
            box-shadow: 0 0 10px #22c55e;
        }
        @keyframes pulse-yellow {
            0% { box-shadow: 0 0 0 0 rgba(234, 179, 8, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(234, 179, 8, 0); }
            100% { box-shadow: 0 0 0 0 rgba(234, 179, 8, 0); }
        }
        .agent-name {
            font-weight: 600;
        }
        .clickable-badge {
            margin-left: auto;
            font-size: 0.8rem;
            background: rgba(99, 102, 241, 0.15);
            color: #818cf8;
            padding: 0.25rem 0.6rem;
            border-radius: 12px;
            font-weight: 500;
            display: none;
        }
        .agent-node.clickable .clickable-badge {
            display: inline-block;
        }
        
        /* Modal styling */
        .modal {
            display: none;
            position: fixed;
            z-index: 100;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: auto;
            background-color: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(8px);
        }
        .modal-content {
            background-color: var(--bg-secondary);
            margin: 8% auto;
            padding: 2.5rem;
            border: 1px solid var(--border-color);
            border-radius: 16px;
            width: 85%;
            max-width: 800px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.8);
        }
        .close-btn {
            color: var(--text-muted);
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close-btn:hover {
            color: var(--text-main);
        }
        .modal-body {
            margin-top: 1.5rem;
            max-height: 500px;
            overflow-y: auto;
            line-height: 1.6;
        }
        .pre-wrap {
            white-space: pre-wrap;
            font-family: inherit;
        }
        
        /* Review Panel */
        .review-panel {
            display: none;
            background: rgba(99, 102, 241, 0.03);
            border: 1px dashed var(--accent-color);
            border-radius: 16px;
            padding: 2rem;
            margin-top: 2rem;
        }
        .review-actions {
            display: flex;
            gap: 1rem;
            margin-top: 1.5rem;
        }
        .btn-approve { background-color: #22c55e; }
        .btn-approve:hover { background-color: #16a34a; }
        .btn-reject { background-color: #ef4444; }
        .btn-reject:hover { background-color: #dc2626; }
        .revision-section {
            margin-top: 2rem;
            border-top: 1px solid var(--border-color);
            padding-top: 1.5rem;
        }
        .btn-revise { background-color: #f59e0b; }
        .btn-revise:hover { background-color: #d97706; }
        
        /* Lists and formatting inside modals */
        .source-item {
            background: #0d1117;
            padding: 1rem;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            margin-bottom: 0.75rem;
        }
        .source-link {
            color: #818cf8;
            text-decoration: none;
            word-break: break-all;
        }
        .source-link:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <header>
        <div class="header-title-container">
            <h1>ContentOS</h1>
        </div>
        <div style="color: var(--text-muted); font-size: 0.9rem;">Google ADK 2.0 Live Dashboard</div>
    </header>
    
    <div class="container">
        <div class="card">
            <h2 style="margin-top: 0; font-size: 1.75rem; font-weight: 600;">Produce New Content</h2>
            <p style="color: var(--text-muted); margin-bottom: 2rem;">
                Enter your topic or prompt. The real Orchestrator Agent will delegate research, scriptwriting, SEO optimization, and final review to specialized agents.
            </p>
            <div class="form-group">
                <label for="prompt">Content Prompt / Topic</label>
                <textarea id="prompt" rows="3" placeholder="e.g., Why Gen Z is burnt out before they even start their careers..."></textarea>
            </div>
            <button id="submit-btn" onclick="startRealProduction()">Generate Content</button>

            <div id="status-panel" class="status-panel">
                <h3 style="margin-bottom: 1.5rem; display: flex; align-items: center; gap: 0.5rem;">
                    <span>Production Pipeline</span>
                    <span id="pipeline-status" style="font-size: 0.9rem; font-weight: 500; color: var(--accent-color); padding: 0.2rem 0.5rem; background: rgba(99, 102, 241, 0.1); border-radius: 4px;">RUNNING</span>
                </h3>
                
                <div id="node-orchestrator" class="agent-node" onclick="viewNodeOutput('OrchestratorAgent')">
                    <div id="dot-orchestrator" class="agent-status"></div>
                    <span class="agent-name">Orchestrator Agent</span>
                    <span class="clickable-badge">View Output</span>
                </div>
                
                <div id="node-research" class="agent-node" onclick="viewNodeOutput('ResearchAgent')">
                    <div id="dot-research" class="agent-status"></div>
                    <span class="agent-name">Research Agent</span>
                    <span class="clickable-badge">View Output</span>
                </div>
                
                <div id="node-script" class="agent-node" onclick="viewNodeOutput('ScriptAgent')">
                    <div id="dot-script" class="agent-status"></div>
                    <span class="agent-name">Script Agent</span>
                    <span class="clickable-badge">View Output</span>
                </div>
                
                <div id="node-seo" class="agent-node" onclick="viewNodeOutput('SEOAgent')">
                    <div id="dot-seo" class="agent-status"></div>
                    <span class="agent-name">SEO Agent</span>
                    <span class="clickable-badge">View Output</span>
                </div>
                
                <div id="node-review" class="agent-node" onclick="viewNodeOutput('ReviewAgent')">
                    <div id="dot-review" class="agent-status"></div>
                    <span class="agent-name">Review Agent</span>
                    <span class="clickable-badge">View Output</span>
                </div>
            </div>
        </div>
        
        <!-- HITL Review Gate Panel -->
        <div id="review-panel" class="review-panel card">
            <h2 style="margin-top: 0; color: var(--accent-color); font-size: 1.5rem;">Human-In-The-Loop Review Gate</h2>
            <p style="color: var(--text-muted); margin-bottom: 1.5rem;">
                The agents have compiled a content draft. Review the summary details below, check for warnings, and choose to Approve, Reject, or request a Revision.
            </p>
            
            <div id="review-summary" style="background: #0d1117; padding: 1.5rem; border-radius: 8px; border: 1px solid var(--border-color); margin-bottom: 1.5rem;">
                <!-- Filled dynamically -->
            </div>
            
            <div class="review-actions">
                <button class="btn-approve" onclick="submitReviewAction('APPROVE')">Approve & Save Output</button>
                <button class="btn-reject" onclick="submitReviewAction('REJECT')">Reject & Discard Draft</button>
            </div>
            
            <div class="revision-section">
                <h3 style="margin-top: 0; font-size: 1.2rem;">Request Revision</h3>
                <div class="form-group">
                    <label for="revision-target">Target Agent for Revision</label>
                    <select id="revision-target" class="select-target">
                        <option value="ResearchAgent">ResearchAgent (Re-run from Research stage)</option>
                        <option value="ScriptAgent" selected>ScriptAgent (Re-draft script & SEO)</option>
                        <option value="SEOAgent">SEOAgent (Regenerate titles/tags only)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="revision-notes">Feedback & Specific Guidance</label>
                    <textarea id="revision-notes" rows="3" placeholder="Explain what changes are needed (e.g. adjust hook, include details about McKinsey sources, etc.)"></textarea>
                </div>
                <button class="btn-revise" onclick="submitReviewAction('REVISE')">Send Back for Revision</button>
            </div>
        </div>
    </div>
    
    <!-- Detail Modal -->
    <div id="detail-modal" class="modal">
        <div class="modal-content card">
            <span class="close-btn" onclick="closeModal()">&times;</span>
            <h2 id="modal-title" style="margin-top: 0; font-size: 1.5rem;">Agent Output</h2>
            <div id="modal-body" class="modal-body">
                <!-- Filled dynamically -->
            </div>
        </div>
    </div>

    <script>
        let currentSessionId = null;
        let pollInterval = null;
        let currentSessionData = null;

        function startRealProduction() {
            const prompt = document.getElementById("prompt").value.trim();
            if (!prompt) return alert("Please enter a prompt.");
            
            document.getElementById("submit-btn").disabled = true;
            document.getElementById("submit-btn").innerText = "Initializing...";
            document.getElementById("status-panel").style.display = "block";
            document.getElementById("review-panel").style.display = "none";
            document.getElementById("pipeline-status").innerText = "RUNNING";
            document.getElementById("pipeline-status").style.color = "var(--accent-color)";
            document.getElementById("pipeline-status").style.background = "rgba(99, 102, 241, 0.1)";

            // Reset UI nodes
            const steps = ['orchestrator', 'research', 'script', 'seo', 'review'];
            steps.forEach(s => {
                document.getElementById(`dot-${s}`).className = 'agent-status';
                document.getElementById(`node-${s}`).classList.remove('clickable');
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
                document.getElementById("submit-btn").innerText = "Generating...";
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
            document.getElementById("submit-btn").innerText = "Generate Content";
        }

        function pollSessionStatus() {
            if (!currentSessionId) return;
            
            fetch(`/api/session/${currentSessionId}`)
            .then(res => res.json())
            .then(data => {
                currentSessionData = data;
                updatePipelineUI(data);
            })
            .catch(err => console.error("Error polling session: ", err));
        }

        function updatePipelineUI(session) {
            const steps = [
                { name: 'OrchestratorAgent', id: 'orchestrator' },
                { name: 'ResearchAgent', id: 'research' },
                { name: 'ScriptAgent', id: 'script' },
                { name: 'SEOAgent', id: 'seo' },
                { name: 'ReviewAgent', id: 'review' }
            ];

            // 1. Identify current node and progress
            const currentNodeName = session.current_node;
            
            // Mark completed nodes based on output availability
            if (session.research_brief) {
                document.getElementById('dot-research').className = 'agent-status done';
                document.getElementById('node-research').classList.add('clickable');
                document.getElementById('dot-orchestrator').className = 'agent-status done';
                document.getElementById('node-orchestrator').classList.add('clickable');
            }
            if (session.script_package) {
                document.getElementById('dot-script').className = 'agent-status done';
                document.getElementById('node-script').classList.add('clickable');
            }
            if (session.seo_package) {
                document.getElementById('dot-seo').className = 'agent-status done';
                document.getElementById('node-seo').classList.add('clickable');
            }
            
            // Set active dot
            if (currentNodeName) {
                steps.forEach(step => {
                    if (step.name === currentNodeName) {
                        document.getElementById(`dot-${step.id}`).className = 'agent-status active';
                    }
                });
            }

            // 2. Handle specific statuses
            if (session.status === "waiting_for_review") {
                document.getElementById('dot-review').className = 'agent-status active';
                document.getElementById('node-review').classList.add('clickable');
                document.getElementById("pipeline-status").innerText = "AWAITING HUMAN REVIEW";
                document.getElementById("pipeline-status").style.color = "#f59e0b";
                document.getElementById("pipeline-status").style.background = "rgba(245, 158, 11, 0.1)";
                
                showReviewPanel(session.review_args);
            } else if (session.status === "approved" || session.status === "completed") {
                clearInterval(pollInterval);
                localStorage.removeItem("contentos_session_id");
                document.getElementById('dot-review').className = 'agent-status done';
                document.getElementById('node-review').classList.add('clickable');
                document.getElementById("pipeline-status").innerText = "APPROVED & COMPLETED";
                document.getElementById("pipeline-status").style.color = "#22c55e";
                document.getElementById("pipeline-status").style.background = "rgba(34, 197, 94, 0.1)";
                document.getElementById("review-panel").style.display = "none";
                resetLaunchButton();
                
                alert(`Content generation successfully approved! Output folder:\n${session.saved_directory}`);
            } else if (session.status === "rejected") {
                clearInterval(pollInterval);
                localStorage.removeItem("contentos_session_id");
                document.getElementById("pipeline-status").innerText = "REJECTED";
                document.getElementById("pipeline-status").style.color = "#ef4444";
                document.getElementById("pipeline-status").style.background = "rgba(239, 68, 68, 0.1)";
                document.getElementById("review-panel").style.display = "none";
                resetLaunchButton();
                
                alert("Content package draft was rejected.");
            } else if (session.status === "error") {
                clearInterval(pollInterval);
                localStorage.removeItem("contentos_session_id");
                document.getElementById("pipeline-status").innerText = "ERROR";
                document.getElementById("pipeline-status").style.color = "#ef4444";
                document.getElementById("pipeline-status").style.background = "rgba(239, 68, 68, 0.1)";
                document.getElementById("review-panel").style.display = "none";
                resetLaunchButton();
                
                alert("Execution error occurred: " + session.error_message);
            }
        }

        function showReviewPanel(args) {
            const panel = document.getElementById("review-panel");
            if (panel.style.display === "block") return; // already showing
            
            const summaryDiv = document.getElementById("review-summary");
            let titlesHtml = "";
            (args.titles || []).forEach((t, i) => {
                titlesHtml += `<div><strong>Title ${i+1}:</strong> ${t}</div>`;
            });
            
            let warningHtml = "";
            if (args.unverified_claims_detected) {
                warningHtml = `<div style="color: #f87171; border: 1px solid #ef4444; background: rgba(239, 68, 68, 0.1); padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-weight: 600;">
                                ⚠️ WARNING: Unverified claims detected in script! (Not backed by research brief)
                               </div>`;
            }
            
            summaryDiv.innerHTML = `
                ${warningHtml}
                <div style="margin-bottom: 0.75rem;"><strong>Hook:</strong> <span class="pre-wrap">${args.hook || 'N/A'}</span></div>
                <div style="margin-bottom: 0.75rem;"><strong>Word Count:</strong> ${args.word_count || 'N/A'} words</div>
                <div style="margin-bottom: 0.75rem;"><strong>Estimated Duration:</strong> ${args.estimated_duration || 'N/A'} seconds</div>
                <div style="margin-bottom: 0.75rem; border-top: 1px solid var(--border-color); padding-top: 0.75rem;">
                    <strong>SEO Title Suggestions:</strong>
                    <div style="margin-top: 0.5rem; padding-left: 1rem; display: flex; flex-direction: column; gap: 0.25rem;">
                        ${titlesHtml}
                    </div>
                </div>
                <div style="margin-bottom: 0.75rem;"><strong>SEO Tags:</strong> ${(args.tags || []).join(', ')}</div>
                <div style="margin-bottom: 0.75rem;"><strong>Thumbnail Design Brief:</strong> <span class="pre-wrap">${args.thumbnail_brief || 'N/A'}</span></div>
                <div><strong>Sources Cited:</strong> ${(args.sources_cited || []).join(', ')}</div>
            `;
            
            panel.style.display = "block";
        }

        function submitReviewAction(action) {
            if (!currentSessionId) return;
            
            const notes = document.getElementById("revision-notes").value;
            const target = document.getElementById("revision-target").value;
            
            const btn = document.querySelector("#review-panel button");
            const originalText = btn.innerText;
            btn.innerText = "Submitting...";
            
            fetch(`/api/session/${currentSessionId}/action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action, notes: notes, target: target })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    document.getElementById("review-panel").style.display = "none";
                    document.getElementById("revision-notes").value = "";
                    if (action === "REVISE") {
                        document.getElementById("pipeline-status").innerText = "ROUTING REVISION...";
                    }
                } else {
                    alert("Action failed: " + data.error);
                }
            })
            .catch(err => alert("Failed to connect to API."))
            .finally(() => btn.innerText = originalText);
        }

        function viewNodeOutput(nodeName) {
            if (!currentSessionData) return;
            const nodeEl = document.getElementById(`node-${nodeName.toLowerCase().replace('agent','')}`);
            if (!nodeEl || !nodeEl.classList.contains('clickable')) return;
            
            const titleEl = document.getElementById("modal-title");
            const bodyEl = document.getElementById("modal-body");
            
            if (nodeName === 'OrchestratorAgent') {
                titleEl.innerText = "Orchestrator Session Config";
                bodyEl.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                        <div><strong>Session ID:</strong> ${currentSessionId}</div>
                        <div><strong>Topic:</strong> ${currentSessionData.topic}</div>
                        <div><strong>Status:</strong> ${currentSessionData.status.toUpperCase()}</div>
                    </div>
                `;
            } else if (nodeName === 'ResearchAgent') {
                titleEl.innerText = "Research Agent - Gathered Sources & Brief";
                const brief = currentSessionData.research_brief || {};
                
                let sourcesHtml = "";
                const sources = brief.sources || [];
                if (sources.length === 0) {
                    sourcesHtml = "<div>No sources found.</div>";
                } else {
                    sources.forEach(src => {
                        sourcesHtml += `
                            <div class="source-item">
                                <div style="font-weight: 600; margin-bottom: 0.25rem;">${src.title || 'Source'}</div>
                                <a href="${src.url}" target="_blank" class="source-link">${src.url}</a>
                                <div style="color: var(--text-muted); font-size: 0.9rem; margin-top: 0.5rem;">${src.snippet || ''}</div>
                            </div>
                        `;
                    });
                }
                
                bodyEl.innerHTML = `
                    <div style="margin-bottom: 1.5rem;">
                        <h4 style="margin-top: 0; color: var(--accent-color);">Research Summary</h4>
                        <div class="pre-wrap">${brief.summary || 'No summary compiled.'}</div>
                    </div>
                    <div>
                        <h4 style="color: var(--accent-color);">Verified Web Sources</h4>
                        ${sourcesHtml}
                    </div>
                `;
            } else if (nodeName === 'ScriptAgent') {
                titleEl.innerText = "Script Agent - Narration Script";
                const scriptPkg = currentSessionData.script_package || {};
                const markdownContent = scriptPkg.content || "*No script draft created yet.*";
                
                bodyEl.innerHTML = `
                    <div style="display: flex; gap: 2rem; margin-bottom: 1.5rem; background: #0d1117; padding: 1rem; border-radius: 8px; border: 1px solid var(--border-color);">
                        <div><strong>Word Count:</strong> ${scriptPkg.word_count || 'N/A'} words</div>
                        <div><strong>Est. Duration:</strong> ${scriptPkg.estimated_duration || 'N/A'} seconds</div>
                    </div>
                    <div>
                        <h4 style="color: var(--accent-color); margin-top: 0;"> Narration Script Draft</h4>
                        <div style="background: #07090e; padding: 1.5rem; border-radius: 8px; border: 1px solid var(--border-color);">
                            ${marked.parse(markdownContent)}
                        </div>
                    </div>
                `;
            } else if (nodeName === 'SEOAgent') {
                titleEl.innerText = "SEO Agent - Metadata Package";
                const seoPkg = currentSessionData.seo_package || {};
                
                let titlesList = "";
                (seoPkg.titles || []).forEach((t, i) => {
                    titlesList += `<li>${t}</li>`;
                });
                
                bodyEl.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 1.5rem;">
                        <div>
                            <h4 style="margin-top: 0; color: var(--accent-color);">Suggested Video Titles</h4>
                            <ul style="padding-left: 1.25rem; line-height: 1.8;">${titlesList || '<li>No titles generated.</li>'}</ul>
                        </div>
                        <div>
                            <h4 style="margin-top: 0; color: var(--accent-color);">Tags</h4>
                            <div>${(seoPkg.tags || []).join(', ') || 'No tags generated.'}</div>
                        </div>
                        <div>
                            <h4 style="margin-top: 0; color: var(--accent-color);">Thumbnail Brief</h4>
                            <div class="pre-wrap">${seoPkg.thumbnail_brief || 'No thumbnail description generated.'}</div>
                        </div>
                        <div>
                            <h4 style="margin-top: 0; color: var(--accent-color);">Video Description</h4>
                            <div class="pre-wrap" style="background: #0d1117; padding: 1rem; border-radius: 8px; border: 1px solid var(--border-color); font-size: 0.95rem;">${seoPkg.description || 'No description generated.'}</div>
                        </div>
                    </div>
                `;
            } else if (nodeName === 'ReviewAgent') {
                titleEl.innerText = "Review Agent - Verification Logs";
                bodyEl.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                        <div><strong>Approval Status:</strong> ${currentSessionData.status.toUpperCase()}</div>
                        \${currentSessionData.saved_directory ? \`<div><strong>Output Directory:</strong> \${currentSessionData.saved_directory}</div>\` : ''}
                    </div>
                `;
            }
            
            document.getElementById("detail-modal").style.display = "block";
        }

        document.addEventListener("DOMContentLoaded", () => {
            window.closeModal = closeModal;
            
            // Check if there is an active session in progress on page load
            const savedSessionId = localStorage.getItem("contentos_session_id");
            if (savedSessionId) {
                currentSessionId = savedSessionId;
                document.getElementById("submit-btn").disabled = true;
                document.getElementById("submit-btn").innerText = "Generating...";
                document.getElementById("status-panel").style.display = "block";
                
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
    data = request.get_json() or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
        
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
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

@app.route("/api/session/<session_id>", methods=["GET"])
def get_session(session_id):
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
