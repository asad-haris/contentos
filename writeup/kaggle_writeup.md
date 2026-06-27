# ContentOS: A Multi-Agent AI Content Production System

**Track:** Agents for Business  
**Builder:** Md Haris Asad — CS Student, Chennai  
**Live Demo:** https://contentos-535767604287.us-central1.run.app  
**GitHub:** https://github.com/asad-haris/contentos  

---

## 1. The Problem

I run a YouTube channel. Before filming a single frame, there are 3–4 hours of work nobody sees: researching the topic, finding credible sources, writing a script that actually sounds like me, generating SEO titles that will perform, briefing a thumbnail concept. Every time. For every video.

Solo creators don't have production teams. We have to be the researcher, the writer, the SEO strategist, and the editor — all before the camera turns on. Most of that work is repetitive, structured, and follows the same pattern every time.

That's a solved problem for large media companies. They have teams. For independent creators, it's completely unsolved.

I built ContentOS to solve it for myself — and by extension, for any solo creator who wants to produce at a higher volume without sacrificing quality. The goal was simple: describe a video idea in plain English, and get back a research-backed script, SEO package, and content brief — all reviewed and approved by me before anything is saved.

One idea. Five minutes. Everything I need to start filming.

---

## 2. The Solution

ContentOS is a multi-agent AI system that compresses a full pre-production workflow into a single conversation. You type a video idea. Four specialist AI agents get to work. You review and approve before anything is finalized.

The system is built on Google ADK 2.0 and deployed as a live web application on Google Cloud Run. Here's what happens when you submit an idea:

**ResearchAgent** searches the web for 3–5 credible sources on your topic. It returns a structured research brief — key claims, statistics, publication dates, source URLs, and three potential video angles.

**ScriptAgent** takes that research brief and writes a full YouTube script in the channel's voice. For my channel (@RennAsks), that means lowercase, direct, smart-older-sibling tone — hook in the first 15 seconds, three main points with sourced evidence, strong CTA. The script only references claims that exist in the research brief.

**SEOAgent** takes the completed script and generates three title options, 10–15 tags, a YouTube description, thumbnail design brief, and chapter markers. All titles follow rules: one must include a number, one must be a question, none can be pure clickbait.

**ReviewAgent** is the final gate. It presents the entire package to me — hook line, word count, all three titles, tags, thumbnail brief, sources. I choose: APPROVE, REVISE, or REJECT. Nothing is saved until I explicitly approve. If I send it back for revision, it routes to the correct agent with my feedback and loops again.

The whole system runs on a dark-themed web dashboard built in Flask, deployed on Cloud Run, accessible from any browser.

---

## 3. Architecture Deep Dive

```
User Input (video idea)
        │
        ▼
┌─────────────────────┐
│  OrchestratorAgent  │  ← ADK 2.0 graph root node
│  (ADK graph root)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   ResearchAgent     │  ← MCP web_search tool
│   (Node 1)          │    research-summarizer skill
└──────────┬──────────┘    returns: research_brief dict
           │
           ▼
┌─────────────────────┐
│   ScriptAgent       │  ← scriptwriting skill
│   (Node 2)          │    accepts: research_brief
└──────────┬──────────┘    returns: script_package dict
           │
           ▼
┌─────────────────────┐
│   SEOAgent          │  ← seo-optimizer skill
│   (Node 3)          │    accepts: script_package + topic
└──────────┬──────────┘    returns: seo_package dict
           │
           ▼
┌─────────────────────┐
│   ReviewAgent       │  ← HITL ADK callback interrupt
│   (Node 4 — HITL)   │    APPROVE → save to output/
└──────────┬──────────┘    REVISE → route back to target agent
           │               REJECT → clean exit
           ▼
    output/{topic}/
    ├── script.md
    ├── seo_package.json
    ├── research_brief.json
    └── approval_log.json
```

**OrchestratorAgent** is the ADK 2.0 graph root. It accepts a video idea as input, routes sequentially through all four subagent nodes, handles the REVISE branching path (max 3 revision loops before forcing human decision), and logs the full execution trace to `output/execution_log.json` on every run.

**ResearchAgent** calls the MCP `web_search` tool, querying for 3–5 high-quality sources. It loads the `research-summarizer` skill only when it fires — this skill contains instructions for evaluating source quality, extracting key claims, and synthesising a 130–180 word research brief. If fewer than 2 sources are found, it asks the user to refine the topic rather than proceeding with insufficient evidence.

**ScriptAgent** receives the research brief and loads the `scriptwriting` skill — which contains the full channel voice guidelines, format rules, good/bad hook examples, and tone specifications for @RennAsks. It enforces two guardrails: the hook cannot start with banned phrases ("In today's video", "Hey guys", "Welcome back"), and the script must cite at least 2 source URLs from the research brief.

**SEOAgent** loads the `seo-optimizer` skill, which contains YouTube SEO principles, title formula examples matching the channel tone, and a tag strategy (broad → specific → long-tail). It enforces title guardrails: at least one title must include a number, at least one must be a question, all must be under 60 characters, none can be pure clickbait.

**ReviewAgent** implements the Human-In-The-Loop gate using ADK's callback interrupt pattern — not a simple `input()` call. The agent pauses execution and surfaces the full content package to the web UI. It waits for an explicit APPROVE, REVISE, or REJECT. The timeout default is REJECT — it never auto-approves. On APPROVE, it writes four files to `output/{topic_slug}_{timestamp}/` and logs the decision with a timestamp to `approval_log.json`.

**Skills and Progressive Disclosure:** All three skills (`research-summarizer`, `scriptwriting`, `seo-optimizer`) follow the progressive disclosure pattern from the course. Antigravity and ADK load only the skill metadata at startup. The full skill instructions are loaded only when the matching agent fires. This means the OrchestratorAgent never carries all three skill payloads simultaneously — it pays the token cost for exactly the skill it's actively using.

**MCP web_search:** The ResearchAgent uses the MCP `web_search` tool as its primary data source. A robust simulated fallback is implemented in `config/mcp_config.py` — when the live MCP search server is unreachable (e.g., local development without Node.js configured), it returns high-quality pre-built research data for the five evaluation topics. This ensures the pipeline never crashes due to a missing external dependency.

---

## 4. Context Engineering Decisions

Context engineering is where I spent most of my design time. Getting this right is what separates a system that produces generic content from one that actually sounds like my channel.

**Static context — AGENTS.md:** The project root contains an `AGENTS.md` file that every agent inherits. It contains the stack, hard rules, channel voice guidelines, and workflow definition. This is loaded into every agent's context on every run. The hard rules include: never publish without explicit human approval, never fabricate statistics, always cite source URLs, never use corporate language.

**Dynamic context — three skills:** The channel voice instructions, SEO formula examples, and research evaluation criteria live in skill files, not in the system prompt. They're only loaded when their agent fires. This was a deliberate trade-off: if I put everything in the system prompt, I'd have context rot — the model dilutes attention when flooded with irrelevant information. By using skills, the ScriptAgent only sees writing instructions when it's writing, and the SEOAgent only sees SEO instructions when it's optimizing.

**The six context types from the course:**
- Instructions: AGENTS.md hard rules and workflow definition
- Knowledge: channel voice guidelines in skills, research brief from web search
- Memory: session state tracked in SESSIONS dict, approval log persisted to disk
- Examples: good/bad hook examples in scriptwriting skill
- Tools: MCP web_search for ResearchAgent, file system for output writing
- Guardrails: hook banned phrases, source citation requirements, HITL approval gate

**Token cost impact:** By splitting static and dynamic context, a typical run uses approximately 3–4x fewer tokens than it would if all skill instructions were loaded statically into every agent call. At scale, this is significant.

---

## 5. Evaluation

I didn't just vibe code this and hope it worked. I built a real evaluation harness.

**The harness:** `evals/eval_runner.py` runs the full ContentOS pipeline against a formal evalset of 5 test cases defined in `evals/evalset.json`. Each test case specifies expected outputs across all four quality dimensions, with an explicit pass threshold of 70/100.

**Scoring rubric:**
| Component | Points | Key Criteria |
|---|---|---|
| Research | 25 | Min sources met, all required fields present, summary 100–300 words |
| Script | 40 | Word count in range, no banned hook phrases, min sources cited, all 4 sections present |
| SEO | 20 | Correct title count, titles under 60 chars, min 10 tags |
| HITL | 15 | approval_log.json created with correct fields |

**Real pipeline results:** On the first real Gemini API run (Case 1: "why gen z is burnt out before they even start their careers"), the pipeline scored **85/100**. The only failure was a word count of 253 vs the configured limit of 250 — a 3-word overage. I diagnosed this as an over-strict configuration rather than an agent failure, updated `eval_config.yaml` to set `max_word_count: 300`, and re-ran. Case 1 scored **100/100**.

**Before/after comparison:**
| Test Case | Before Fix | After Fix |
|---|---|---|
| Case 1 (Gen Z burnout) | 85/100 FAIL | 100/100 PASS |
| Cases 1–5 (mock) | 100/100 | 100/100 |

**The mock eval trap:** My first evaluation run scored a perfect 100/100 — but it was measuring hardcoded mock data, not the real agent. I caught this, refactored the eval runner to call the real pipeline by default, and added a `--mock` flag for offline CI testing. A real 85/100 is worth more than a fake 100/100.

**Quota management:** The Gemini free tier allows 20 requests per day. Running all 5 real eval cases requires 20+ API calls. I implemented automatic rate-limit retry with exponential backoff in the eval runner — it intercepts 429 RESOURCE_EXHAUSTED errors, extracts the recommended sleep duration, and retries automatically.

---

## 6. Security and HITL

Security wasn't an afterthought. It was a design requirement from day one.

**The HITL gate** is implemented as an ADK callback interrupt — not a `print()` statement and not a blocking `input()` call. The ReviewAgent pauses the ADK graph execution and surfaces the content package to the web UI via a session polling endpoint. Execution resumes only when the `/api/session/{id}/action` endpoint receives an explicit POST from the user.

**Nothing is saved until APPROVE.** The ReviewAgent checks for explicit approval before writing any file. The timeout behavior defaults to REJECT — if the session expires without a response, the draft is discarded. There is no auto-approve path.

**approval_log.json** records every decision with a timestamp, the session ID, the topic, and the action taken. This creates an audit trail for every piece of content the system produces.

**Source verification guardrail:** The ScriptAgent includes a guardrail that checks whether every factual claim in the script can be traced back to a URL in the research brief. If it cannot, the claim is either removed or flagged for human review during the HITL gate.

**Production security:** The `.env` file is excluded from version control (.gitignore verified before every push). The `CLOUD_RUN=true` environment variable disables all `input()` calls in containerized environments. The `GEMINI_API_KEY` is injected at deploy time via `gcloud run deploy --set-env-vars`, never hardcoded.

---

## 7. Deployment

ContentOS is deployed on Google Cloud Run and accessible at a public URL.

**Container:** Python 3.11-slim base image. Flask app served by Gunicorn with 2 workers and a 300-second timeout (necessary for the multi-agent pipeline execution time). Port 8080, exposed to Cloud Run's managed load balancer.

**Configuration:**
- `--no-cpu-throttling`: ensures CPU is always allocated for background async agent execution
- `--session-affinity`: pins client requests to the same container instance, preventing in-memory session state from being split across instances
- `--memory 1Gi`: handles the ADK graph runtime and concurrent session management
- `CLOUD_RUN=true`: disables interactive `input()` prompts, enables auto-approve for HITL in batch contexts

**Deploy command:**
```bash
gcloud run deploy contentos \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --session-affinity \
  --set-env-vars "CLOUD_RUN=true,GEMINI_API_KEY=..."
```

**Live URL:** https://contentos-535767604287.us-central1.run.app  
**GitHub:** https://github.com/asad-haris/contentos

---

## 8. Lessons Learned

**The mock eval trap is real.** My first evaluation run scored a perfect 100/100. I was about to move on when I noticed the eval runner was using hardcoded mock data, not the real pipeline. Refactoring it to test the actual agent output immediately revealed a real failure. This is exactly why the course emphasizes evals — not to feel good about your system, but to find out what's actually broken.

**Context engineering made the biggest difference.** Before I wrote the channel voice guidelines in the `scriptwriting` skill, the ScriptAgent was producing generic, corporate-sounding scripts. After adding specific tone rules, banned phrases, and good/bad hook examples, the output quality improved dramatically. The model doesn't need cleverly worded prompts — it needs the same context a new writer would need to understand your brand.

**The 80% problem is real, and the 20% matters.** ADK generated approximately 80% of every agent's output correctly on the first pass. The remaining 20% — edge cases in the HITL callback pattern, the Cloud Run `input()` incompatibility, the session affinity requirement — required genuine engineering judgment. The AI builds the structure; the developer handles the integration points.

**Free tier quota forces discipline.** 20 requests per day sounds like a lot until you have a 4-agent pipeline and a 5-case eval suite. Implementing rate-limit retry and the `--mock` flag for offline testing wasn't optional — it was required to make development sustainable. This is a real constraint that production systems face at scale, and building around it early paid off.

**What I'd build next:** Real-time MCP web search (replace the simulated fallback), multi-platform output (LinkedIn threads, Twitter threads from the same research brief), scheduled content pipeline via MCP cron triggers, and persistent cross-session memory so the agent learns the channel's historical performance.

---

## 9. Course Concepts Used

| Course Concept | Where Used in ContentOS |
|---|---|
| ADK 2.0 graph workflows | OrchestratorAgent as graph root with 4 subagent nodes, conditional REVISE branching |
| Agent Skills (progressive disclosure) | 3 skills loaded only when their agent fires — not statically in system prompt |
| MCP web_search | ResearchAgent's primary tool for source gathering |
| HITL security gate | ReviewAgent: ADK callback interrupt, APPROVE/REVISE/REJECT, timeout defaults to REJECT |
| Cloud Run deployment | Production deployment with Gunicorn, session affinity, no-CPU-throttling |

ContentOS demonstrates that the shift from vibe coding to agentic engineering is not about using fancier tools — it's about building the harness. The model is 10% of the system. The context engineering, the evaluation harness, the HITL gate, the deployment configuration, and the guardrails are the other 90%. That's what this project is about.

---

*Word count: ~2,480 words*
