# ContentOS — AI Content Operations Platform

ContentOS is a multi-agent AI content production system that turns a video idea into a complete script, SEO package, and content brief using Google ADK 2.0.

---

## 🏗️ Architecture Workflow

The ContentOS pipeline executes as an asynchronous directed graph, delegating tasks across 4 specialized agent nodes coordinated by the root Orchestrator, with an integrated Human-in-the-Loop (HITL) gate before final publication:

```
[User Input] 
     │
     ▼
[OrchestratorAgent] ──(routes state)──► [ResearchAgent] (MCP web_search)
     ▲                                         │
     │                                     (returns brief)
     │                                         ▼
     ├───────────────────────────────── [ScriptAgent] (RennAsks tone compliance)
     │                                         │
     │                                     (returns draft)
     │                                         ▼
     ├───────────────────────────────── [SEOAgent] (metadata & thumbnail design)
     │                                         │
     │                                     (returns package)
     │                                         ▼
     └───────────────────────────────── [ReviewAgent (HITL Gate)]
                                               │
                       ┌───────────────────────┴───────────────────────┐
                       ▼                                               ▼
                  [APPROVED]                                       [REVISE] (loops back)
                       │                                               │
                       ▼                                               ▼
              [Export to output/]                                (max 3 revision cycles)
```

---

## 🚀 Key Course Concepts Used

*   **Google ADK 2.0 Graph Workflows:** Built using the Google Agent Development Kit 2.0 to define complex, stateful asynchronous execution graphs with looping edges, routing context, and session checkpointing.
*   **Agent Skills (Progressive Disclosure):** Employs declarative skills configuration defining prompt guidelines and system instructions, dynamically loading agent capabilities only when invoked.
*   **Model Context Protocol (MCP):** Integrates standard Brave Web Search protocol (`web_search` tool) to query active search instances with timeout safety and robust local database fallback mappings.
*   **HITL Security Gate:** Pauses workflow execution state synchronously at `ReviewAgent` via non-blocking async loops and `threading.Event` signaling, exposing endpoints to resume/revise/approve drafts from the dashboard.
*   **Google Cloud Run Deployment:** Standardized production deployment with multi-stage Docker caching, wildcard host binding, and gunicorn multi-threaded session affinity configuration.

---

## 📂 Project Structure

```text
contentos/
├── .env.example          # Environment template for local secrets setup
├── .gitignore            # Git exclusion rules (safeguarding .env and cache dirs)
├── Dockerfile            # Optimized production slim-base container build
├── README.md             # Project documentation (this file)
├── main.py               # Main terminal application & console HITL loop
├── requirements.txt      # Production Python packages and dependencies
├── agents/               # ADK 2.0 Agents definitions directory
│   ├── __init__.py       # Package entry exports
│   ├── orchestrator.py   # Root OrchestratorAgent graph & loops
│   ├── research_agent.py # ResearchAgent (MCP search brief compile)
│   ├── script_agent.py   # ScriptAgent (RennAsks voice narration draft)
│   ├── seo_agent.py      # SEOAgent (title, description, tags, thumbnail brief)
│   └── review_agent.py   # ReviewAgent (HITL gate & function definitions)
├── config/               # Platform configurations
│   ├── __init__.py
│   └── mcp_config.py     # Brave Search MCP parameters & fallback DB rules
├── evals/                # Automated testing & evaluation framework
│   ├── eval_config.yaml  # Metrics scoring weights & auto-fail rules
│   ├── eval_runner.py    # Live/Mock evaluation execution engine
│   ├── evalset.json      # 5 formal test cases for topic generation
│   └── mock_data.py      # Simulation datasets and mock LLM async handlers
├── frontend/             # Premium responsive Web Dashboard
│   └── app.py            # Flask server, API endpoints, and HTML/CSS template
└── output/               # Timestamped approved content outputs
```

---

## ⚡ Setup & Installation

Follow these steps to run ContentOS on your local system:

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/asad-haris/contentos.git
    cd contentos
    ```

2.  **Install Dependencies:**
    Initialize your virtual environment and install the required modules:
    ```bash
    python -m venv .venv
    .venv\Scripts\activate      # On Windows
    # source .venv/bin/activate  # On macOS/Linux
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables:**
    Copy the sample configuration file and add your credentials:
    ```bash
    copy .env.example .env
    ```
    Open `.env` and fill in your details:
    *   `GOOGLE_API_KEY`: Your Gemini API developer key.
    *   `MCP_SEARCH_API_KEY`: Brave Search API key (optional fallback is used if omitted).

4.  **Launch the Application:**
    *   **Interactive CLI Mode:**
        ```bash
        python main.py
        ```
    *   **Immediate Topic Generation:**
        ```bash
        python main.py "Why Gen Z is burnt out"
        ```
    *   **Live Dashboard Frontend:**
        ```bash
        python frontend/app.py
        ```
        Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## 🌐 Live Service URL

*   **Production Deployment URL:** [https://contentos-535767604287.us-central1.run.app](https://contentos-535767604287.us-central1.run.app)

---

## 📈 Evaluation Results

*   **Offline/Mock Simulation Suite:** `100/100` (All 5 test cases passing evaluation constraints).
*   **Live/Real Pipeline Execution:** Evaluation harness built and fully integrated with 5 custom test cases. Real pipeline evaluation is pending API quota reset.
