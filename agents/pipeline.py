"""Multi-agent report pipeline — runs entirely on local Ollama models.

Agents:
  1. Intake    (llama3.2:3b)   — parse raw query → structured spec
  2. Planner   (deepseek-r1:7b)— spec + schema   → SQL query plan
     ── Checkpoint 1: admin reviews and approves query plan ──
  3. Researcher               — execute SQL queries → data findings (no LLM)
     ── Checkpoint 2: admin reviews gathered data ──
  4. Builder   (deepseek-r1:7b)— all context → HTML report

Background thread polls DB every 3 s at each checkpoint.
"""
from __future__ import annotations
import json, logging, os, re, threading, time
from sqlalchemy import text
from data.loader import engine
from db.report_requests import (
    STATUS_RUNNING, STATUS_CP1, STATUS_CP1_OK,
    STATUS_RESEARCHING, STATUS_CP2, STATUS_CP2_OK,
    STATUS_BUILDING, STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED,
    get_request, set_field, append_log,
)

log = logging.getLogger(__name__)

INTAKE_MODEL = "llama3.2:3b"
WORK_MODEL   = "deepseek-r1:7b"

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports", "generated")
os.makedirs(REPORTS_DIR, exist_ok=True)

_active: dict[int, bool] = {}
_lock = threading.Lock()

DB_SCHEMA = """
AVAILABLE TABLES:

work_items_main  — every ADO work item
  work_item_id(int), title, work_item_type(Enhancement/Bug/Bug_UI/Bug_Text/Task),
  state, priority(1=critical 2=high 3=med 4=low), assigned_to, main_dev,
  iteration_path(text e.g. '...\\Iteration 2026 05-May'), story_points(float),
  created_date(date), closed_date(date), type(Customer/Internal/Automation)
  Sprint filter: iteration_path LIKE '%Iteration 2026 05-%'

agg_dev_monthly_capacity  — pre-aggregated dev capacity
  name, ym('YYYY-MM'), total_hours, feature_hours, overhead_hours, allocated_pct

p_bugs  — bug tracker
  bug_ref, ado_id(int), title, state, priority(int), main_dev, sprint('YYYY-MM')

agg_gantt_items  — active planning items
  work_item_id, title, main_dev, iteration_path, pct_complete(0-100), customer_type

standalone_task_classifications  — classified overhead tasks
  task_id, title, category(Meetings & Calls/Dev Overhead/Research & Spikes/
  Design & Docs/Testing & QA/Operations/Other), confidence

p_dev_leaves       — dev_name, leave_date, leave_type(planned/sick), hours, ym
p_company_holidays — holiday_date, holiday_name, hours
"""


# ── Ollama helpers ─────────────────────────────────────────────────────────────

def _ollama(model: str, prompt: str) -> str:
    import ollama as _ol
    resp = _ol.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
    )
    raw = resp["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def _extract_json(text: str) -> dict | list | None:
    m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _safe_select(sql: str, max_rows: int = 200) -> list[dict] | str:
    clean = sql.strip()
    if not clean.upper().startswith("SELECT"):
        return f"Skipped (not SELECT): {clean[:80]}"
    try:
        with engine.connect() as c:
            rows = c.execute(text(clean)).fetchmany(max_rows)
            return [dict(r._mapping) for r in rows]
    except Exception as e:
        return f"Error: {e}"


def _wait_approval(request_id: int, target_status: str, timeout: int = 7200) -> bool:
    """Poll DB every 3 s until status reaches target or request is cancelled."""
    for _ in range(timeout // 3):
        time.sleep(3)
        r = get_request(request_id)
        if not r:
            return False
        if r["status"] == target_status:
            return True
        if r["status"] in (STATUS_CANCELLED, STATUS_FAILED):
            return False
    append_log(request_id, "Checkpoint timed out (2 h). Cancelling.")
    return False


# ── Agent 1: Intake ────────────────────────────────────────────────────────────

def _agent_intake(request_id: int, query: str) -> dict | None:
    append_log(request_id, "Agent 1 (Intake): parsing query...")
    prompt = (
        "You are an analytics intake agent. Parse this report request.\n\n"
        f'Request: "{query}"\n\n'
        "Return ONLY valid JSON — no explanation:\n"
        '{\n'
        '  "analysis_type": "sprint_performance|bug_analysis|capacity_planning|'
        'velocity_trends|developer_performance|custom",\n'
        '  "time_range": "current_sprint|last_month|last_3_months|last_6_months|ytd|custom",\n'
        '  "focus_areas": ["delivery","bugs","capacity","developer_performance","scope_creep"],\n'
        '  "summary": "one sentence: what this report covers"\n'
        "}"
    )
    try:
        raw  = _ollama(INTAKE_MODEL, prompt)
        spec = _extract_json(raw)
        if not spec:
            spec = {"analysis_type": "custom", "time_range": "last_3_months",
                    "focus_areas": ["delivery"], "summary": query[:200]}
            append_log(request_id, "  ⚠ Intake: used fallback spec (JSON parse failed)")
        else:
            append_log(request_id, f"  ✓ Intake done: {spec.get('summary','')[:120]}")
        return spec
    except Exception as e:
        append_log(request_id, f"  ✗ Intake error: {e}")
        return None


# ── Agent 2: Planner ───────────────────────────────────────────────────────────

def _agent_planner(request_id: int, query: str, spec: dict) -> dict | None:
    append_log(request_id, "Agent 2 (Planner): building query plan...")
    prompt = (
        f'Original request: "{query}"\n\n'
        f"Report spec:\n{json.dumps(spec, indent=2)}\n\n"
        f"{DB_SCHEMA}\n\n"
        "Write SQL SELECT queries to gather all data needed for this report.\n"
        "Rules:\n"
        "- Only SELECT statements (no INSERT/UPDATE/DELETE)\n"
        "- Current year is 2026; use YYYY-MM format for months\n"
        "- Max 6 queries, each self-contained and runnable\n"
        "- For sprint filters use iteration_path LIKE '%Iteration 2026 MM-%'\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "queries": [\n'
        '    {"label": "Name", "sql": "SELECT ...", "purpose": "why needed"}\n'
        "  ],\n"
        '  "report_outline": ["Section 1", "Section 2"]\n'
        "}"
    )
    try:
        raw  = _ollama(WORK_MODEL, prompt)
        plan = _extract_json(raw)
        if not plan or "queries" not in plan:
            append_log(request_id, "  ✗ Planner: could not parse query plan")
            return None
        n = len(plan.get("queries", []))
        append_log(request_id, f"  ✓ Planner done: {n} queries planned")
        return plan
    except Exception as e:
        append_log(request_id, f"  ✗ Planner error: {e}")
        return None


# ── Agent 3: Researcher ────────────────────────────────────────────────────────

def _agent_researcher(request_id: int, query_plan: dict) -> str | None:
    append_log(request_id, "Agent 3 (Researcher): executing queries...")
    findings: list[str] = []
    for q in query_plan.get("queries", []):
        label   = q.get("label", "Query")
        sql     = q.get("sql", "")
        purpose = q.get("purpose", "")
        append_log(request_id, f"  → {label}...")
        result  = _safe_select(sql)
        if isinstance(result, str):
            findings.append(f"## {label}\n{result}\n")
        elif not result:
            findings.append(f"## {label}\nPurpose: {purpose}\nNo rows returned.\n")
        else:
            headers  = list(result[0].keys())
            rows_txt = "\n".join(
                "  " + " | ".join(str(row.get(h, "")) for h in headers)
                for row in result[:50]
            )
            findings.append(
                f"## {label}\nPurpose: {purpose}\n"
                f"Columns: {', '.join(headers)}\nRows: {len(result)}\n{rows_txt}\n"
            )
    data = "\n".join(findings)
    append_log(request_id, f"  ✓ Research done: {len(query_plan.get('queries',[]))} queries executed")
    return data


# ── Agent 4: Builder ───────────────────────────────────────────────────────────

def _agent_builder(request_id: int, query: str, spec: dict, plan: dict, data: str) -> str | None:
    append_log(request_id, "Agent 4 (Builder): generating HTML report...")
    outline = plan.get("report_outline", [])
    prompt = (
        "Generate a complete professional HTML analytics report.\n\n"
        f'Request: "{query}"\n'
        f'Summary: {spec.get("summary","")}\n'
        f'Sections: {", ".join(outline) if outline else "derive from data"}\n\n'
        f"DATA FINDINGS:\n{data[:8000]}\n\n"
        "Requirements:\n"
        "- Light theme: white background (#fff), dark text (#1e293b), navy/blue accents\n"
        "- Full page width, professional management-grade layout\n"
        "- Clear section headers, HTML tables for tabular data\n"
        "- Summary box at top with 3-4 key metrics/findings\n"
        "- Self-contained: all CSS in a <style> block, no external dependencies\n"
        "- Readable on screen and printable\n\n"
        "Return ONLY the complete HTML starting with <!DOCTYPE html>"
    )
    try:
        raw = _ollama(WORK_MODEL, prompt)
        if "<!DOCTYPE html>" in raw:
            html_out = raw[raw.find("<!DOCTYPE html>"):]
        elif "<html" in raw:
            html_out = raw[raw.find("<html"):]
        else:
            html_out = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<style>body{font-family:Arial,sans-serif;padding:40px;"
                "color:#1e293b;background:#fff;max-width:1200px;margin:0 auto}"
                "h1{color:#1e3a8a}h2{color:#1e40af;border-bottom:2px solid #e2e8f0;padding-bottom:8px}"
                "table{width:100%;border-collapse:collapse;margin:16px 0}"
                "th{background:#1e3a8a;color:#fff;padding:8px 12px;text-align:left}"
                "td{padding:7px 12px;border-bottom:1px solid #e2e8f0}"
                "tr:nth-child(even){background:#f8fafc}</style></head>"
                f"<body><h1>Analytics Report</h1><p><em>{query}</em></p>"
                f"<pre style='white-space:pre-wrap'>{raw}</pre></body></html>"
            )
        append_log(request_id, f"  ✓ Builder done: {len(html_out):,} chars")
        return html_out
    except Exception as e:
        append_log(request_id, f"  ✗ Builder error: {e}")
        return None


# ── Orchestrator ───────────────────────────────────────────────────────────────

def _run_pipeline(request_id: int) -> None:
    try:
        r = get_request(request_id)
        if not r:
            return
        query = r["query_text"]
        log.info("Pipeline start: request %d", request_id)

        # Stage 1 + 2: Intake → Planner
        set_field(request_id, status=STATUS_RUNNING)
        spec = _agent_intake(request_id, query)
        if not spec:
            set_field(request_id, status=STATUS_FAILED)
            return

        plan = _agent_planner(request_id, query, spec)
        if not plan:
            set_field(request_id, status=STATUS_FAILED)
            return

        # Checkpoint 1
        set_field(request_id, status=STATUS_CP1,
                  intake_spec=json.dumps(spec), query_plan=json.dumps(plan))
        append_log(request_id, "── Checkpoint 1: awaiting admin approval of query plan ──")

        if not _wait_approval(request_id, STATUS_CP1_OK):
            append_log(request_id, "Halted at Checkpoint 1.")
            return

        # Stage 3: Researcher
        set_field(request_id, status=STATUS_RESEARCHING)
        data = _agent_researcher(request_id, plan)
        if not data:
            set_field(request_id, status=STATUS_FAILED)
            return

        # Checkpoint 2
        set_field(request_id, status=STATUS_CP2, data_findings=data)
        append_log(request_id, "── Checkpoint 2: awaiting admin approval to build report ──")

        if not _wait_approval(request_id, STATUS_CP2_OK):
            append_log(request_id, "Halted at Checkpoint 2.")
            return

        # Stage 4: Builder
        set_field(request_id, status=STATUS_BUILDING)
        html_out = _agent_builder(request_id, query, spec, plan, data)
        if not html_out:
            set_field(request_id, status=STATUS_FAILED)
            return

        filename = f"report_{request_id}_{int(time.time())}.html"
        filepath = os.path.join(REPORTS_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_out)

        set_field(request_id, status=STATUS_DONE,
                  report_path=f"reports/generated/{filename}")
        append_log(request_id, f"✓ Pipeline complete — {filename}")
        log.info("Pipeline done: request %d → %s", request_id, filename)

    except Exception as e:
        log.exception("Pipeline crash (request %d): %s", request_id, e)
        try:
            set_field(request_id, status=STATUS_FAILED)
            append_log(request_id, f"Pipeline crashed: {e}")
        except Exception:
            pass
    finally:
        with _lock:
            _active.pop(request_id, None)


def start_pipeline(request_id: int) -> bool:
    """Start pipeline in background thread. Returns False if already running."""
    with _lock:
        if request_id in _active:
            return False
        _active[request_id] = True
    threading.Thread(
        target=_run_pipeline, args=(request_id,),
        daemon=True, name=f"pipeline-{request_id}",
    ).start()
    return True


def is_running(request_id: int) -> bool:
    return request_id in _active
