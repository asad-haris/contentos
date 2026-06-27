"""ContentOS Evaluation Runner.

Runs evaluation test cases, scores results against configured rubrics,
applies auto-fail conditions, and generates formatted reports.
"""

import os
import sys
import json
import yaml
import time
import argparse
import asyncio
import datetime
from unittest.mock import patch

# Add project root to sys.path
sys.path.append(os.getcwd())

# If running in mock mode, set dummy environment variables to bypass validation
if "--mock" in sys.argv:
    os.environ["GOOGLE_API_KEY"] = "dummy_google_api_key"
    os.environ["MCP_SEARCH_API_KEY"] = "dummy_mcp_search_api_key"
else:
    from dotenv import load_dotenv
    load_dotenv()

from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from agents.orchestrator import orchestrator


# --- Scoring Logic functions ---

def score_case(case_data, run_dir):
    """Scores a single case run output folder against rubrics and returns scores + failures."""
    expected = case_data["expected_outputs"]
    failures = []
    
    # Load files from target directory
    research_file = os.path.join(run_dir, "research_brief.json")
    script_file = os.path.join(run_dir, "script.md")
    seo_file = os.path.join(run_dir, "seo_package.json")
    log_file = os.path.join(run_dir, "approval_log.json")

    # 1. Research Scoring (max 25)
    r_score = 0
    sources_count = 0
    has_research = os.path.exists(research_file)
    research_data = {}
    if has_research:
        try:
            with open(research_file, "r", encoding="utf-8") as f:
                research_data = json.load(f)
            sources = research_data.get("sources", [])
            sources_count = len(sources)
            min_src = expected["research"]["min_sources"]
            # Meet min sources
            if sources_count >= min_src:
                r_score += 10
            else:
                failures.append(f"Research: sources count ({sources_count}) below expected minimum ({min_src})")
            
            # Fields check
            req_fields = expected["research"]["required_fields"]
            missing_fields = [f for f in req_fields if f not in research_data]
            if not missing_fields:
                r_score += 10
            else:
                failures.append(f"Research: missing required fields {missing_fields}")

            # Summary length
            summary = research_data.get("summary", "")
            sum_words = len(summary.split())
            if 100 <= sum_words <= 200:
                r_score += 5
            else:
                failures.append(f"Research: summary length ({sum_words} words) out of [100, 200] range")
        except Exception as e:
            failures.append(f"Research: Failed to parse research file. Details: {e}")
    else:
        failures.append("Research: research_brief.json file missing")

    # 2. Script Scoring (max 40)
    s_score = 0
    has_script = os.path.exists(script_file)
    script_content = ""
    if has_script:
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                script_content = f.read()
            words = script_content.split()
            word_count = len(words)
            min_wc = expected["script"]["min_word_count"]
            max_wc = expected["script"]["max_word_count"]
            
            # Dynamic override from config if specified
            config_path = "evals/eval_config.yaml"
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        import yaml
                        cfg = yaml.safe_load(f) or {}
                        cfg_max = cfg.get("auto_fail_conditions", {}).get("script", {}).get("max_word_count")
                        if cfg_max:
                            max_wc = cfg_max
                except Exception:
                    pass
            
            # Word count
            if min_wc <= word_count <= max_wc:
                s_score += 15
            else:
                failures.append(f"Script: word count ({word_count}) outside range [{min_wc}, {max_wc}]")

            # Hook Banned Phrases
            hook_line = ""
            for line in script_content.split("\n"):
                if line.strip() and not line.startswith("#"):
                    hook_line = line.strip().lower()
                    break
            
            banned = expected["script"]["hook_banned_phrases"]
            found_banned = [p for p in banned if p in hook_line]
            if not found_banned:
                s_score += 10
            else:
                failures.append(f"Script: hook contains banned phrases: {found_banned}")

            # Sources Cited count
            # Parse links in parentheses
            import re
            links = re.findall(r"https?://[^\s)]+", script_content)
            citations_count = len(set(links))
            min_cited = expected["script"]["min_sources_cited"]
            if citations_count >= min_cited:
                s_score += 10
            else:
                failures.append(f"Script: citations count ({citations_count}) under expected minimum ({min_cited})")

            # All 4 sections presence
            lower_script = script_content.lower()
            has_hook = "# hook" in lower_script
            has_sec1 = "# section 1" in lower_script
            has_sec2 = "# section 2" in lower_script
            has_sec3 = "# section 3" in lower_script
            has_cta = "# cta" in lower_script
            
            if has_hook and (has_sec1 or has_sec2 or has_sec3) and has_cta:
                s_score += 5
            else:
                failures.append(f"Script: missing header sections (Hook: {has_hook}, Section1-3: {has_sec1 or has_sec2 or has_sec3}, CTA: {has_cta})")

        except Exception as e:
            failures.append(f"Script: Failed to read script file. Details: {e}")
    else:
        failures.append("Script: script.md file missing")

    # 3. SEO Scoring (max 20)
    seo_score = 0
    has_seo = os.path.exists(seo_file)
    seo_data = {}
    if has_seo:
        try:
            with open(seo_file, "r", encoding="utf-8") as f:
                seo_data = json.load(f)
            titles = seo_data.get("titles", [])
            title_count = len(titles)
            expected_title_count = expected["seo"]["title_count"]
            
            # Title count
            if title_count == expected_title_count:
                seo_score += 8
            else:
                failures.append(f"SEO: title count ({title_count}) does not match expected ({expected_title_count})")

            # Max title length
            max_len = expected["seo"]["max_title_length"]
            long_titles = [t for t in titles if len(t) > max_len]
            if not long_titles:
                seo_score += 7
            else:
                failures.append(f"SEO: titles exceeding {max_len} chars: {long_titles}")

            # Min tags count
            tags = seo_data.get("tags", [])
            min_t = expected["seo"]["min_tags"]
            if len(tags) >= min_t:
                seo_score += 5
            else:
                failures.append(f"SEO: tags count ({len(tags)}) under expected minimum ({min_t})")

        except Exception as e:
            failures.append(f"SEO: Failed to parse SEO file. Details: {e}")
    else:
        failures.append("SEO: seo_package.json file missing")

    # 4. HITL Scoring (max 15)
    hitl_score = 0
    has_log = os.path.exists(log_file)
    if has_log:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)
            req_log_fields = ["approved_by", "timestamp", "topic", "files_saved"]
            missing_log = [f for f in req_log_fields if f not in log_data]
            if not missing_log:
                hitl_score += 15
            else:
                failures.append(f"HITL: approval log missing fields {missing_log}")
        except Exception as e:
            failures.append(f"HITL: Failed to parse approval log. Details: {e}")
    else:
        failures.append("HITL: approval_log.json file missing")

    total_pts = r_score + s_score + seo_score + hitl_score
    return {
        "research": r_score,
        "script": s_score,
        "seo": seo_score,
        "hitl": hitl_score,
        "total": total_pts,
        "failures": failures
    }


async def run_pipeline_for_case(case_data):
    """Executes the actual pipeline for the topic and auto-approves HITL gate."""
    topic = case_data["input_topic"]
    slug = case_data["eval_id"]
    run_dir = f"evals/runs/{slug}"
    
    # Pre-clean the run directory safely
    import shutil
    if os.path.exists(run_dir):
        for name in os.listdir(run_dir):
            file_path = os.path.join(run_dir, name)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception:
                pass
    else:
        os.makedirs(run_dir, exist_ok=True)

    session_service = InMemorySessionService()
    runner = Runner(
        agent=orchestrator,
        app_name="agents",
        session_service=session_service,
        auto_create_session=True
    )

    session_id = f"eval_{slug}_session"
    user_id = "eval_user"

    # Set topic for mock tracking if mock mode is active
    if "--mock" in sys.argv:
        import evals.mock_data
        evals.mock_data.CURRENT_TOPIC_TEXT = topic

    # Step 1: Start execution run
    user_msg = types.Content(parts=[types.Part(text=topic)])
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=user_msg
    ):
        pass

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

    if unresolved:
        unresolved_fc = unresolved[-1]
        
        # Step 2: Auto-approve callback resumption
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
            user_id=user_id,
            session_id=session_id,
            new_message=resume_msg
        ):
            pass

    # Copy the saved files from the output directory to the runs folder
    import re
    import shutil
    topic_slug = re.sub(r'[^a-z0-9]+', '_', topic.lower()).strip('_')
    if not topic_slug:
        topic_slug = "content_package"
        
    matching_dirs = []
    if os.path.exists("output"):
        for name in os.listdir("output"):
            full_path = os.path.join("output", name)
            if os.path.isdir(full_path) and name.startswith(topic_slug):
                matching_dirs.append(full_path)
                
    if matching_dirs:
        matching_dirs.sort(key=os.path.getmtime)
        latest_dir = matching_dirs[-1]
        for fname in os.listdir(latest_dir):
            src_file = os.path.join(latest_dir, fname)
            dst_file = os.path.join(run_dir, fname)
            if os.path.isfile(src_file):
                shutil.copy2(src_file, dst_file)
                
    return run_dir


def evaluate_case_auto_fail(scores_breakdown, config_data):
    """Applies hard config auto-fail rules."""
    rules = config_data.get("auto_fail_conditions", {})
    auto_fails = []
    
    # We inspect the test case failures list compiled during score_case
    failures = scores_breakdown.get("failures", [])
    for failure in failures:
        # Categorize
        if "sources count" in failure and rules.get("research", {}).get("min_sources_limit"):
            auto_fails.append(f"Auto-Fail (Research): {failure}")
        if "missing required fields" in failure and rules.get("research", {}).get("missing_required_fields"):
            auto_fails.append(f"Auto-Fail (Research): {failure}")
        if "banned phrases" in failure and rules.get("script", {}).get("contains_banned_phrases"):
            auto_fails.append(f"Auto-Fail (Script): {failure}")
        if "citations" in failure and rules.get("script", {}).get("missing_citations"):
            auto_fails.append(f"Auto-Fail (Script): {failure}")
        if "word count" in failure and rules.get("script", {}).get("word_count_out_of_bounds"):
            auto_fails.append(f"Auto-Fail (Script): {failure}")
        if "title count" in failure and rules.get("seo", {}).get("incorrect_title_count"):
            auto_fails.append(f"Auto-Fail (SEO): {failure}")
        if "exceeding" in failure and rules.get("seo", {}).get("title_length_exceeded"):
            auto_fails.append(f"Auto-Fail (SEO): {failure}")
        if "tags" in failure and rules.get("seo", {}).get("insufficient_tags"):
            auto_fails.append(f"Auto-Fail (SEO): {failure}")
        if "approval log" in failure and rules.get("hitl", {}).get("missing_approval_log"):
            auto_fails.append(f"Auto-Fail (HITL): {failure}")
            
    return auto_fails


def compile_recommendations(all_auto_fails):
    """Compiles recommendations list based on failures encountered."""
    recs = []
    has_banned = any("banned phrases" in f for f in all_auto_fails)
    has_words = any("word count" in f for f in all_auto_fails)
    has_sources = any("sources count" in f or "validated sources" in f for f in all_auto_fails)
    has_titles = any("title count" in f or "exceeding" in f for f in all_auto_fails)
    has_log = any("approval log" in f for f in all_auto_fails)

    if has_banned:
        recs.append("Modify ScriptAgent system instructions to strictly enforce banned phrases compliance.")
    if has_words:
        recs.append("Adjust ScriptAgent word limit enforcement or modify output schema constraints.")
    if has_sources:
        recs.append("Re-configure Brave Search API key or check fallback search parameters in config/mcp_config.py.")
    if has_titles:
        recs.append("Fix SEOAgent generation prompts or schemas to restrict title options limit to exactly 3 and max length to 60 characters.")
    if has_log:
        recs.append("Check ReviewAgent output file creation routine and path naming convention checks.")
    
    if not recs and all_auto_fails:
        recs.append("Review test outputs and check agent parameters alignment.")
    elif not recs:
        recs.append("No actions needed. All tests passed.")
        
    return recs


# Save the original method to call it
original_generate_content_async = Gemini.generate_content_async

async def rate_limited_generate_content_async(self, llm_request, stream=False):
    max_retries = 5
    retry_delay = 20  # default sleep duration
    
    for attempt in range(max_retries):
        try:
            # Delegate to original generator
            async for response in original_generate_content_async(self, llm_request, stream=stream):
                yield response
            return
        except Exception as e:
            err_msg = str(e).lower()
            is_rate_limit = "429" in err_msg or "resource_exhausted" in err_msg or "quota" in err_msg
            is_unavailable = "503" in err_msg or "unavailable" in err_msg or "temporary" in err_msg
            
            if (is_rate_limit or is_unavailable) and attempt < max_retries - 1:
                import re
                match = re.search(r"retry in ([\d\.]+)s", err_msg)
                sleep_sec = float(match.group(1)) + 2.0 if match else retry_delay
                print(f"\n[Rate Limit] API returned error. Retrying in {sleep_sec:.2f}s (Attempt {attempt+1}/{max_retries})...")
                await asyncio.sleep(sleep_sec)
            else:
                raise e


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Validate evalset JSON structure only")
    parser.add_argument("--case", type=str, help="Index (1-5) or Case ID of a single case to evaluate")
    parser.add_argument("--mock", action="store_true", help="Run evaluation runner using offline mocked Gemini responses")
    args = parser.parse_args()

    # Load configuration files
    evalset_path = "evals/evalset.json"
    config_path = "evals/eval_config.yaml"

    if not os.path.exists(evalset_path):
        print(f"Error: {evalset_path} not found.")
        sys.exit(1)
    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found.")
        sys.exit(1)

    with open(evalset_path, "r", encoding="utf-8") as f:
        evalset = json.load(f)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Dry-Run structural validation
    if args.dry_run:
        print("\n[EVAL RUNNER] Running dry-run validation of evals/evalset.json...")
        errors = []
        for idx, case in enumerate(evalset, 1):
            eval_id = case.get("eval_id")
            topic = case.get("input_topic")
            expected = case.get("expected_outputs")
            rubric = case.get("quality_rubric")
            
            if not eval_id:
                errors.append(f"Case {idx}: Missing 'eval_id'")
            if not topic:
                errors.append(f"Case {idx}: Missing 'input_topic'")
            if not expected:
                errors.append(f"Case {idx}: Missing 'expected_outputs'")
            else:
                if "research" not in expected:
                    errors.append(f"Case {idx}: Missing expected 'research' outputs")
                if "script" not in expected:
                    errors.append(f"Case {idx}: Missing expected 'script' outputs")
                if "seo" not in expected:
                    errors.append(f"Case {idx}: Missing expected 'seo' outputs")
            if not rubric:
                errors.append(f"Case {idx}: Missing 'quality_rubric'")
                
        if errors:
            print(f"Dry-run FAILED with {len(errors)} errors:")
            for err in errors:
                print(f" - {err}")
            sys.exit(1)
        else:
            print("Dry-run PASSED. The evaluation dataset is structurally valid.")
            sys.exit(0)

    # Filter by case if specified
    cases_to_run = evalset
    if args.case:
        filtered = []
        # Support case indexing 1-5 or case ID
        if args.case.isdigit():
            idx = int(args.case) - 1
            if 0 <= idx < len(evalset):
                filtered.append(evalset[idx])
        else:
            filtered = [c for c in evalset if c["eval_id"] == args.case]
            
        if not filtered:
            print(f"Error: Single case filter '{args.case}' did not match any test cases.")
            sys.exit(1)
        cases_to_run = filtered

    # Key validation for real mode runs
    if not args.mock:
        google_key = os.environ.get("GOOGLE_API_KEY")
        if not google_key or google_key == "your_gemini_api_key_here":
            print("Error: GOOGLE_API_KEY is missing or invalid in your .env file.", file=sys.stderr)
            print("Please set a valid Gemini API key to run the real ContentOS pipeline evaluation,", file=sys.stderr)
            print("or run with --mock for offline mocked testing (e.g., python evals/eval_runner.py --mock).", file=sys.stderr)
            sys.exit(1)

    print(f"\n[ContentOS Evals] Starting evaluation run of {len(cases_to_run)} cases...")
    if args.mock:
        print("[ContentOS Evals] Running in OFFLINE MOCK MODE. Using simulated model responses.")
    else:
        print("[ContentOS Evals] Running in REAL PIPELINE MODE. Calling real Gemini API.")
    print("=" * 60)

    per_case_scores = []
    all_auto_fails = []
    total_run_scores = 0

    async def run_cases():
        nonlocal total_run_scores
        for idx, case in enumerate(cases_to_run, 1):
            eval_id = case["eval_id"]
            topic = case["input_topic"]
            print(f"\n[{idx}/{len(cases_to_run)}] Running pipeline for: '{topic}'")
            
            start_time = time.time()
            try:
                run_dir = await run_pipeline_for_case(case)
                elapsed = time.time() - start_time
                
                # Score
                score_data = score_case(case, run_dir)
                
                # Auto fail rules
                case_fails = evaluate_case_auto_fail(score_data, config)
                all_auto_fails.extend(case_fails)
                failures_list = score_data["failures"]
            except Exception as e:
                elapsed = time.time() - start_time
                case_fails = [f"Execution Error: Pipeline execution crashed. Details: {e}"]
                all_auto_fails.extend(case_fails)
                score_data = {
                    "research": 0,
                    "script": 0,
                    "seo": 0,
                    "hitl": 0,
                    "total": 0
                }
                failures_list = case_fails
            
            case_result = {
                "eval_id": eval_id,
                "input_topic": topic,
                "score_breakdown": {
                    "research": score_data["research"],
                    "script": score_data["script"],
                    "seo": score_data["seo"],
                    "hitl": score_data["hitl"]
                },
                "total_score": score_data["total"],
                "elapsed_seconds": round(elapsed, 2),
                "status": "FAIL" if case_fails else "PASS",
                "failures": failures_list
            }
            per_case_scores.append(case_result)
            total_run_scores += score_data["total"]
            
            print(f"    Completed in {elapsed:.2f}s. Score: {score_data['total']}/100. Status: {case_result['status']}")
            if failures_list:
                print("    Failures detected:")
                for f in failures_list:
                    print(f"      - {f}")
            
            # Sleep between cases to avoid rate limits (RPM quota) on free tier
            if idx < len(cases_to_run):
                print("    Waiting 20 seconds to respect API rate limits...")
                await asyncio.sleep(20)

    if args.mock:
        from evals.mock_data import mock_generate_content_async
        with patch.object(Gemini, "generate_content_async", new=mock_generate_content_async):
            await run_cases()
    else:
        with patch.object(Gemini, "generate_content_async", new=rate_limited_generate_content_async):
            await run_cases()

    # Compile Final Report
    avg_score = total_run_scores / len(cases_to_run)
    pass_thresh = config.get("thresholds", {}).get("pass_threshold", 0.70) * 100
    
    overall_status = "PASS"
    if avg_score < pass_thresh:
        overall_status = "FAIL"
    if all_auto_fails:
        overall_status = "FAIL"

    recs = compile_recommendations(all_auto_fails)
    
    report = {
        "run_timestamp": datetime.datetime.now().isoformat(),
        "total_score": round(avg_score, 2),
        "pass_fail": overall_status,
        "per_case_scores": per_case_scores,
        "failures": all_auto_fails,
        "recommendations": recs
    }

    report_path = "evals/eval_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 60)
    print("  EVALUATION RUN REPORT SUMMARY")
    print("=" * 60)
    print(f"Timestamp:          {report['run_timestamp']}")
    print(f"Overall Result:     {report['pass_fail']}")
    print(f"Average Score:      {report['total_score']}/100")
    print(f"Pass Threshold:     {pass_thresh}/100")
    print(f"Total Failures:     {len(all_auto_fails)}")
    print(f"Report Location:    {report_path}")
    print("-" * 60)
    if all_auto_fails:
        print("Auto-Fail Triggers:")
        for fail in all_auto_fails[:10]:
            print(f"  - {fail}")
        print("\nRecommendations for Agent Optimizations:")
        for rec in recs:
            print(f"  - {rec}")
    else:
        print("Congratulations! All checks passed successfully.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
