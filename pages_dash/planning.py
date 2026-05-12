"""EOD Planning Tool — Story Readiness, BA Sign-Off & Capacity Dashboard"""

import re
import dash
import pandas as pd
from datetime import date, datetime

from dash import dcc, html, Input, Output, State, ALL, callback, ctx, no_update
import dash_bootstrap_components as dbc

from data.loader import load_data
from config.team_mapping import TEAM_MAPPING
from config.settings  import ADO_BASE_URL
from config.lifecycle import LIFECYCLE, STEP_INDEX, STEP_LABELS, TOTAL_STEPS

dash.register_page(__name__, path="/planning", name="Planning Tool")
print(">>> [planning.py] LOADED — panel=680px card=#252548")

# ─── Colour tokens ─────────────────────────────────────────────────────────────
G  = "#34d399"   # green  – Ready / good
R  = "#f87171"   # red    – Not Started / urgent
A  = "#fb923c"   # amber  – Draft / warning
B  = "#60a5fa"   # blue   – In Dev / M0
P  = "#818cf8"   # purple – accent
TX = "#e2e8f0"   # primary text
MT = "#8892a4"   # muted text
BD = "rgba(255,255,255,0.07)"
CD = "#13131f"
C2 = "#1a1a2e"
C3 = "#0f0f1a"

STATUS_COLOR = {
    "NOT STARTED":   R,
    "DRAFT":         A,
    "STORY FROZEN":  "#c084fc",
    "IN DEV":        B,
    "IN QA":         "#fb923c",
    "READY TO SHIP": G,
    "SHIPPED":       "#10b981",
}

# Ordered gate fields matching DB schema
_GATE_FIELDS = ("dor", "story_written", "estimation", "in_dev", "in_qa", "ready_to_ship", "delivery")
_GATE_FILTER_MAP = {
    "dor":           {"gates": ["g1", "g2"], "phases": None},
    "story_written": {"gates": ["g3"],       "phases": ["p4"]},
    "estimation":    {"gates": ["g3"],       "phases": ["p5"]},
    "delivery":      {"gates": ["g4", "g5", "g6"], "phases": None},
}
_WIN_BORDER  = "#fbbf24"  # golden separator between planning window and rest of 2026

# Tab button styles (active / idle) — used by _switch_tab callback
_TAB_BTN_ACT = {
    "background": f"{P}22", "border": f"1px solid {P}", "borderRadius": "8px",
    "color": TX, "fontSize": "13px", "fontWeight": "600",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}
_TAB_BTN_IDL = {
    "background": "transparent", "border": f"1px solid {BD}", "borderRadius": "8px",
    "color": MT, "fontSize": "13px", "fontWeight": "400",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}

# ─── Story Owner mapping ────────────────────────────────────────────────────────
# ADO field: Custom.Userstoryowner — short name values ("Geetika", "Chhavi")
# Maps short name → (display_name, code, role)
STORY_OWNER_MAP: dict[str, tuple] = {
    "Geetika": ("Geetika Khanna", "SO-01", "Story Owner"),
    "Chhavi":  ("Chhavi Bhardwaj", "SO-02", "Story Owner"),
}
BA_DEFAULT = ("Unassigned", "SO-00", "Story Owner")

# ─── Terminal ADO states — used for closed-item filtering only ─────────────────
_CLOSED_STATES = {
    "Closed", "Not an issue", "Not Required", "Userstory Update",
    "No Customer Response", "Resolved",
}

# ─── Matrix column order ────────────────────────────────────────────────────────
MATRIX_MONTHS = ["M0", "M1", "M2", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

CELL_COLORS = {
    "not_started":   {"bg": "#2e0e0e", "text": R,         "border": R},
    "draft":         {"bg": "#2a1f00", "text": A,         "border": A},
    "story_frozen":  {"bg": "#1e1040", "text": "#c084fc", "border": "#c084fc"},
    "in_dev":        {"bg": "#0e2340", "text": B,         "border": B},
    "in_qa":         {"bg": "#2a1500", "text": "#fb923c", "border": "#fb923c"},
    "ready_to_ship": {"bg": "#0c2e1e", "text": G,         "border": G},
    "shipped":       {"bg": "#052e1c", "text": "#10b981", "border": "#10b981"},
}

_DEV_ROLE = {
    "Development":  "Web Dev",
    "Mobile":       "Mobile Dev",
    "QA":           "QA/Test",
    "Design/Video": "Designer",
    "Management":   "Manager",
    "User Story":   "BA/PO",
}

_CAL = {1:"Jan", 2:"Feb", 3:"Mar", 4:"Apr", 5:"May", 6:"Jun",
        7:"Jul", 8:"Aug", 9:"Sep", 10:"Oct", 11:"Nov", 12:"Dec"}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

# Cache for processed planning data — avoids rebuilding 700+ stories on every page visit.
# Gate state is NOT cached here (always fresh from DB on page load).
_planning_cache: dict = {"data": None, "ts": 0.0}
_unest_cache:    dict = {"data": None, "ts": 0.0}
_bug_cache:      dict = {"data": None, "ts": 0.0}
_PLANNING_TTL = 300  # 5 minutes, matches load_data() TTL
_PAGE_SIZE    = 4    # rows per page in BA Sign-Off table


def _load_unestimated_data() -> list[dict]:
    """
    Query open 2026 Enhancements + Issues with task-rollup estimate logic.

    Estimate status per item:
      estimated           — original_estimate > 0 on the item itself
      estimated_via_tasks — no direct estimate, all child tasks estimated
      partial             — child tasks exist, SOME missing estimates (flag these)
      unestimated         — no estimate anywhere

    Returns only items where est_status in ('unestimated', 'partial').
    Cached for 5 min.
    """
    import time as _time
    from sqlalchemy import text as _text

    _now = _time.monotonic()
    if _unest_cache["data"] is not None and (_now - _unest_cache["ts"]) < _PLANNING_TTL:
        return _unest_cache["data"]

    sql = _text("""
        WITH related_tasks AS (
            -- Tasks linked via "Related" to an Enhancement/Bug instead of
            -- as a proper Child. Pick lowest Enh ID when linked to multiples.
            SELECT DISTINCT ON (t.work_item_id)
                   CASE WHEN rel.source_id = t.work_item_id
                        THEN rel.target_id ELSE rel.source_id END AS parent_id,
                   t.main_developer,
                   t.work_item_id,
                   t.original_estimate,
                   t.state
            FROM work_items_main t
            JOIN work_items_relations rel
                ON rel.relation_type = 'System.LinkTypes.Related'
                AND (rel.source_id = t.work_item_id
                     OR rel.target_id = t.work_item_id)
            JOIN work_items_main e
                ON e.work_item_id = CASE
                    WHEN rel.source_id = t.work_item_id
                    THEN rel.target_id ELSE rel.source_id END
            WHERE t.work_item_type = 'Task'
              AND (t.parent_id IS NULL OR t.parent_id != e.work_item_id)
              AND e.work_item_type IN (
                    'Enhancement','Bug','Bug_UI','Bug_Text')
            ORDER BY t.work_item_id, parent_id
        ),
        child_tasks AS (
            SELECT parent_id, main_developer, original_estimate, state
            FROM work_items_main
            WHERE work_item_type = 'Task' AND parent_id IS NOT NULL
        ),
        dev_task_summary AS (
            -- All child tasks for a parent, regardless of which developer is
            -- assigned. main_developer on the Enhancement is one person but
            -- multiple devs can create tasks — all of them count together.
            -- Closed/terminal tasks are excluded from the missing-estimate check.
            SELECT
                parent_id,
                COUNT(*)  AS task_count,
                COUNT(*) FILTER (WHERE state NOT IN (
                    'Closed','Dev Complete','Resolved','Not Required','Not an issue'
                ))  AS open_task_count,
                COUNT(*) FILTER (WHERE
                    (original_estimate IS NULL OR original_estimate = 0)
                    AND state NOT IN (
                        'Closed','Dev Complete','Resolved','Not Required','Not an issue'
                    )
                )  AS missing_count,
                SUM(COALESCE(original_estimate, 0))  AS est_sum
            FROM child_tasks
            GROUP BY parent_id
        ),
        rel_task_summary AS (
            -- Orphan tasks (parent_id IS NULL) linked via Related — also
            -- not developer-scoped since the Enhancement owns them collectively.
            -- Closed/terminal tasks are excluded from the missing-estimate check.
            SELECT
                parent_id,
                COUNT(*)  AS task_count,
                COUNT(*) FILTER (WHERE state NOT IN (
                    'Closed','Dev Complete','Resolved','Not Required','Not an issue'
                ))  AS open_task_count,
                COUNT(*) FILTER (WHERE
                    (original_estimate IS NULL OR original_estimate = 0)
                    AND state NOT IN (
                        'Closed','Dev Complete','Resolved','Not Required','Not an issue'
                    )
                )  AS missing_count,
                SUM(COALESCE(original_estimate, 0))  AS est_sum
            FROM related_tasks
            GROUP BY parent_id
        ),
        classified AS (
            SELECT
                e.work_item_id,
                e.title,
                e.priority,
                e.work_item_type,
                e.state,
                e.iteration_path,
                e.main_developer,
                e.story_owner,
                COALESCE(e.original_estimate, 0)        AS original_estimate,
                COALESCE(ts.task_count,    0)           AS task_count,
                COALESCE(ts.missing_count, 0)           AS task_missing_count,
                COALESCE(ts.est_sum,       0)           AS task_est_sum,
                CASE
                    WHEN COALESCE(e.original_estimate, 0) > 0
                        THEN 'estimated'
                    -- Child tasks: all closed → OK; open tasks all estimated → OK; any open missing → partial
                    WHEN ts.task_count > 0 AND COALESCE(ts.open_task_count, 0) = 0
                        THEN 'estimated_via_tasks'
                    WHEN ts.task_count > 0 AND ts.missing_count = 0 AND ts.est_sum > 0
                        THEN 'estimated_via_tasks'
                    WHEN ts.task_count > 0 AND ts.missing_count > 0
                        THEN 'partial'
                    -- Fall through to orphan related tasks (same logic)
                    WHEN rts.task_count > 0 AND COALESCE(rts.open_task_count, 0) = 0
                        THEN 'estimated_via_tasks'
                    WHEN rts.task_count > 0 AND rts.missing_count = 0 AND rts.est_sum > 0
                        THEN 'estimated_via_tasks'
                    WHEN rts.task_count > 0 AND rts.missing_count > 0
                        THEN 'partial'
                    ELSE 'unestimated'
                END AS est_status
            FROM work_items_main e
            LEFT JOIN dev_task_summary ts
                   ON ts.parent_id = e.work_item_id
            LEFT JOIN rel_task_summary rts
                   ON rts.parent_id = e.work_item_id
            WHERE e.iteration_path LIKE '%2026%'
              AND e.work_item_type IN ('Enhancement', 'Bug', 'Bug_UI', 'Bug_Text')
              AND e.state NOT IN (
                  'Closed','Not an issue','Not Required',
                  'Userstory Update','No Customer Response','Resolved',
                  'Clarification','Watch List','On Hold','Rare Scenario',
                  'Waiting on Customer'
              )
        )
        SELECT * FROM classified
        ORDER BY priority, work_item_id
    """)

    try:
        from data.loader import engine as _engine
        with _engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
    except Exception:
        return []

    today = date.today()
    cur_m = today.month
    result = []
    for r in rows:
        m = re.search(r"Iteration 2026 (\d{2})-", str(r.iteration_path))
        if not m:
            continue
        mnum  = int(m.group(1))
        delta = mnum - cur_m
        if   delta == 0: mkey = "M0"
        elif delta == 1: mkey = "M1"
        elif delta == 2: mkey = "M2"
        else:            mkey = _CAL.get(mnum)
        if not mkey:
            continue

        dev = str(r.main_developer or "Unassigned").split(" <")[0].strip()
        try:
            pri = f"P{int(float(r.priority))}"
        except Exception:
            pri = "P4"

        wtype = (
            "Enhancement" if r.work_item_type == "Enhancement" else "Issue"
        )

        result.append({
            "id":           int(r.work_item_id),
            "title":        str(r.title or "")[:100],
            "pri":          pri,
            "type":         wtype,
            "dev":          dev,
            "month":        mkey,
            "est_status":   r.est_status,     # 'unestimated' | 'partial'
            "task_count":   int(r.task_count),
            "task_missing": int(r.task_missing_count),
            "task_sum":     float(r.task_est_sum),
            "story_owner":  str(r.story_owner or ""),
        })

    _unest_cache["data"] = result
    _unest_cache["ts"]   = _now
    return result


def _load_bug_data() -> list[dict]:
    """Load open Bug/Bug_UI/Bug_Text items from 2026 iterations."""
    import time as _time
    _now = _time.monotonic()
    if _bug_cache["data"] is not None and (_now - _bug_cache["ts"]) < _PLANNING_TTL:
        return _bug_cache["data"]

    try:
        df = load_data()
    except Exception:
        return []

    today = date.today()
    cur_m = today.month
    _BUG_TYPES = {"Bug", "Bug_UI", "Bug_Text"}

    mask = (
        df["iteration_path"].str.contains("2026", na=False)
        & df["work_item_type"].isin(_BUG_TYPES)
        & ~df["state"].isin(_CLOSED_STATES)
    )
    bugs = df[mask].copy()

    def _mkey(ipath: str):
        m = re.search(r"Iteration 2026 (\d{2})-", str(ipath))
        if not m:
            return None
        mnum  = int(m.group(1))
        delta = mnum - cur_m
        if delta == 0: return "M0"
        if delta == 1: return "M1"
        if delta == 2: return "M2"
        return _CAL.get(mnum)

    bugs["_mkey"] = bugs["iteration_path"].apply(_mkey)
    bugs = bugs[bugs["_mkey"].notna()]

    result = []
    for _, row in bugs.iterrows():
        dev      = str(row.get("main_developer", "Unassigned")).split(" <")[0].strip()
        dev_team = TEAM_MAPPING.get(dev, "")
        dev_role = _DEV_ROLE.get(dev_team, "Developer")
        est      = row.get("original_estimate")
        est_ok   = bool(pd.notna(est) and float(est) > 0) if pd.notna(est) else False
        owner    = str(row.get("story_owner", "")).strip()
        ba       = STORY_OWNER_MAP.get(owner, BA_DEFAULT)
        try:
            pri = f"P{int(float(row.get('priority', 4)))}"
        except Exception:
            pri = "P4"

        result.append({
            "id":        int(row["work_item_id"]),
            "title":     str(row["title"])[:100] if pd.notna(row.get("title")) else "(No title)",
            "pri":       pri,
            "type":      str(row.get("work_item_type", "Bug")),
            "dev":       dev,
            "dev_role":  dev_role,
            "ba":        ba[0],
            "ba_code":   ba[1],
            "ba_role":   ba[2],
            "month":     row["_mkey"],
            "state":     str(row.get("state", "")),
            "estimated": est_ok,
            "hrs":       float(est) if est_ok else None,
        })

    _bug_cache["data"] = result
    _bug_cache["ts"]   = _now
    return result


def _story_status_key(s: dict) -> str:
    """Map story dict → CELL_COLORS key based on lifecycle gate progress."""
    if s.get("delivery"):
        return "shipped"
    if s.get("ready_to_ship"):
        return "ready_to_ship"
    if s.get("in_qa"):
        return "in_qa"
    if s.get("in_dev"):
        return "in_dev"
    if s.get("dor") and s.get("story_written") and s.get("estimation"):
        return "story_frozen"
    if s.get("dor") or s.get("story_written") or s.get("estimation"):
        return "draft"
    return "not_started"


def _load_planning_data():
    """
    Pull open Enhancements from 2026 ADO iterations and build all planning-page
    data structures.

    ADO story data is cached for 5 min (matches load_data() TTL).
    Gate state is always fetched fresh from DB on every call.

    Returns:
        stories      – list[dict]  one entry per ADO work item
        months       – list[dict]  {key, label, badge, bc} ordered M0→Dec
        init_gates   – dict        str(work_item_id) → {written, ac, est}
        ba_names     – list[str]   unique BA display names (non-default)
        dev_names    – list[str]   unique developer names (non-unassigned)
        dev_matrix   – dict        dev_name → {role, ns, M0:(...), ...}
        story_matrix – list[dict]  M0/M1/M2 stories × months (for By Story view)
    """
    import time as _time

    # ── Check cache (stories + matrices only, not gates) ─────────────────────
    _now = _time.monotonic()
    if _planning_cache["data"] is not None and (_now - _planning_cache["ts"]) < _PLANNING_TTL:
        cached_stories, months, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat = \
            _planning_cache["data"]
        # Always re-fetch gates from DB (they change independently)
        try:
            from db.planning import load_all_gates as _load_all_gates
            _db_gates = _load_all_gates()
        except Exception:
            _db_gates = {}
        stories = []
        for s in cached_stories:
            s = dict(s)
            if s["id"] in _db_gates:
                _dg = _db_gates[s["id"]]
                for _f in _GATE_FIELDS:
                    if _f != "estimation":
                        s[_f] = _dg.get(_f, False)
            else:
                for _f in _GATE_FIELDS:
                    if _f != "estimation":
                        s[_f] = False
            stories.append(s)
        init_gates = {
            str(s["id"]): {f: s[f] for f in _GATE_FIELDS}
            for s in stories
        }
        return stories, months, init_gates, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat

    try:
        df = load_data()
    except Exception:
        return [], [], {}, [], [], {}, []

    today   = date.today()
    cur_m   = today.month   # e.g. 4 for April

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _parse_mkey(ipath: str):
        m = re.search(r"Iteration 2026 (\d{2})-", str(ipath))
        if not m:
            return None
        mnum  = int(m.group(1))
        delta = mnum - cur_m
        if delta == 0: return "M0"
        if delta == 1: return "M1"
        if delta == 2: return "M2"
        return _CAL.get(mnum)

    def _clean(n: str) -> str:
        n = str(n)
        return n.split(" <")[0].strip()

    def _fmt_pri(p) -> str:
        try:
            return f"P{int(float(p))}"
        except Exception:
            return "P4"

    def _fmt_size(h) -> str | None:
        if pd.isna(h) or h == 0:
            return None
        h = float(h)
        if h >= 80: return "Big"
        if h >= 30: return "Medium"
        if h >= 8:  return "Small"
        return "Very Small"

    def _get_ba(row) -> tuple:
        """Read Custom.Userstoryowner (short name) → (display_name, code, role)."""
        owner = str(row.get("story_owner", "")).strip()
        return STORY_OWNER_MAP.get(owner, BA_DEFAULT)

    # ── Filter: open Enhancements in 2026 iterations only ────────────────────
    # Bugs excluded — sign-off gate workflow applies to Enhancements only for now
    mask = (
        df["iteration_path"].str.contains("2026", na=False)
        & (df["work_item_type"] == "Enhancement")
        & ~df["state"].isin(_CLOSED_STATES)
    )
    enh = df[mask].copy()
    enh["_mkey"] = enh["iteration_path"].apply(_parse_mkey)
    enh = enh[enh["_mkey"].notna()]

    # ── Build stories list ────────────────────────────────────────────────────
    stories: list[dict] = []
    for _, row in enh.iterrows():
        ba       = _get_ba(row)
        dev      = _clean(str(row.get("main_developer", "Unassigned")))
        dev_team = TEAM_MAPPING.get(dev, "")
        dev_role = _DEV_ROLE.get(dev_team, "Developer")
        st       = str(row.get("state", ""))
        est      = row.get("original_estimate")
        est_ok   = bool(pd.notna(est) and float(est) > 0) if pd.notna(est) else False
        wtype    = str(row.get("work_item_type", ""))

        stories.append({
            "id":            int(row["work_item_id"]),
            "title":         str(row["title"])[:100] if pd.notna(row.get("title")) else "(No title)",
            "pri":           _fmt_pri(row.get("priority")),
            "type":          "ENH" if wtype == "Enhancement" else "ISSUE",
            "size":          _fmt_size(est),
            "hrs":           float(est) if est_ok else None,
            "dev":           dev,
            "dev_role":      dev_role,
            "ba":            ba[0],
            "ba_code":       ba[1],
            "ba_role":       ba[2],
            "month":         row["_mkey"],
            "dor":           False,
            "story_written": False,
            "estimation":    est_ok,
            "in_dev":        False,
            "in_qa":         False,
            "ready_to_ship": False,
            "delivery":      False,
            "state":         st,
            "function":      str(row.get("function", "")),
        })

    # ── Apply DB gate overrides BEFORE building summaries ────────────────────
    # Source of truth is the lifecycle tracker → DB. ADO state is not used for gates.
    try:
        from db.planning import load_all_gates as _load_all_gates
        _db_gates = _load_all_gates()
    except Exception:
        _db_gates = {}

    for s in stories:
        if s["id"] in _db_gates:
            _dg = _db_gates[s["id"]]
            for _f in _GATE_FIELDS:
                if _f != "estimation":
                    s[_f] = _dg.get(_f, False)

    init_gates = {
        str(s["id"]): {f: s[f] for f in _GATE_FIELDS}
        for s in stories
    }

    # ── Build MONTHS list ─────────────────────────────────────────────────────
    _morder = ["M0","M1","M2","Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]
    _mlabels = {
        "M0": f"M0 · {_CAL[cur_m]}",
        "M1": f"M1 · {_CAL[min(cur_m+1, 12)]}",
        "M2": f"M2 · {_CAL[min(cur_m+2, 12)]}",
    }
    for _, ml in _CAL.items():
        _mlabels[ml] = ml

    months_present = {s["month"] for s in stories}
    months: list[dict] = []
    for mkey in _morder:
        if mkey not in months_present:
            continue
        ms      = [s for s in stories if s["month"] == mkey]
        ready   = sum(1 for s in ms if s["dor"] and s["story_written"])
        total   = len(ms)
        pct     = round(ready / total * 100) if total else 0
        ns      = sum(1 for s in ms if not s["dor"])
        bc      = G if pct >= 80 else A if pct >= 50 else R
        badge   = f"{pct}%" if mkey in ("M0","M1","M2") else f"{ns}ns"
        months.append({"key": mkey, "label": _mlabels.get(mkey, mkey),
                       "badge": badge, "bc": bc, "pct": pct})

    # ── Unique BAs and devs ───────────────────────────────────────────────────
    ba_names  = sorted({s["ba"] for s in stories if s["ba"] != BA_DEFAULT[0]})
    dev_names = sorted({
        s["dev"] for s in stories
        if s["dev"] not in ("Unassigned", "Not Specified", "")
    })

    # ── By-developer matrix ───────────────────────────────────────────────────
    _SP = {
        "in_dev": 0, "in_qa": 1, "ready_to_ship": 2,
        "story_frozen": 3, "draft": 4, "not_started": 5, "shipped": 6,
    }
    dev_matrix: dict = {}
    for s in stories:
        dname = s["dev"]
        if dname in ("Unassigned", "Not Specified", ""):
            continue
        if dname not in dev_matrix:
            dev_matrix[dname] = {"role": s["dev_role"], "ns": 0,
                                  **{mk: None for mk in MATRIX_MONTHS}}
        mkey = s["month"]
        if mkey not in MATRIX_MONTHS:
            continue
        sk = _story_status_key(s)
        if dev_matrix[dname][mkey] is None:
            dev_matrix[dname][mkey] = (1, sk)
        else:
            cnt, csk = dev_matrix[dname][mkey]
            worst = csk if _SP.get(csk, 9) >= _SP.get(sk, 9) else sk
            dev_matrix[dname][mkey] = (cnt + 1, worst)
        if not s.get("dor"):
            dev_matrix[dname]["ns"] += 1

    # ── By-story matrix (M0/M1/M2 only, unique titles) ───────────────────────
    story_matrix: list[dict] = []
    seen: set = set()
    m012 = sorted(
        [s for s in stories if s["month"] in ("M0","M1","M2")],
        key=lambda x: (x["pri"], x["title"]),
    )
    for s in m012:
        if s["title"] in seen:
            continue
        seen.add(s["title"])
        sm = {
            "id":      s["id"],
            "title":   s["title"],
            "size":    s["size"],
            "pri":     s["pri"],
            "type":    s["type"],
            "ba":      s["ba"],
            "ba_code": s["ba_code"],
            **{mk: None for mk in MATRIX_MONTHS},
        }
        for ss in stories:
            if ss["title"] == s["title"] and ss["month"] in MATRIX_MONTHS:
                sm[ss["month"]] = (ss["dev"], _story_status_key(ss))
        story_matrix.append(sm)

    # ── Flat list for reactive dev matrix (id + dev + role + month only) ─────
    dev_stories_flat = [
        {"id": s["id"], "dev": s["dev"], "role": s["dev_role"], "month": s["month"]}
        for s in stories
        if s["dev"] not in ("Unassigned", "Not Specified", "")
        and s["month"] in MATRIX_MONTHS
    ]

    # ── Store ADO-derived data in cache (gates excluded — always live) ────────
    _stories_for_cache = [
        {k: v for k, v in s.items() if k not in _GATE_FIELDS}
        for s in stories
    ]
    _planning_cache["data"] = (_stories_for_cache, months, ba_names, dev_names,
                               dev_matrix, story_matrix, dev_stories_flat)
    _planning_cache["ts"] = _time.monotonic()

    return stories, months, init_gates, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _status(g: dict) -> str:
    if g.get("dor") and g.get("story_written"):
        return "STORY FROZEN"
    if g.get("dor") or g.get("story_written"):
        return "DRAFT"
    return "NOT STARTED"


def _pri_clr(p):   return {"P1": R, "P2": A, "P3": G, "P4": MT}.get(str(p), MT)
def _type_clr(t):  return {"ENH": P, "ISSUE": "#f59e0b"}.get(t, MT)
def _size_clr(s):  return {"Big": "#e879f9", "Medium": B, "Small": G, "Very Small": MT}.get(s or "", MT)


# ═══════════════════════════════════════════════════════════════════════════════
# REUSABLE COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

def _tag(text, color):
    return html.Span(text, style={
        "fontSize": "10px", "fontWeight": "700", "padding": "2px 7px",
        "borderRadius": "4px", "background": f"{color}22", "color": color,
        "marginRight": "4px", "letterSpacing": "0.3px",
    })


def _gate_btn(sid, gate, checked):
    labels = {
        "dor":           "DoR Gate",
        "story_written": "Story Written",
    }
    clr  = G if checked else "rgba(255,255,255,0.18)"
    icon = "✓" if checked else "○"
    return html.Div(
        [
            html.Span(icon, style={"color": clr, "marginRight": "6px",
                                   "fontSize": "12px", "fontWeight": "700",
                                   "flexShrink": "0"}),
            html.Span(labels[gate], style={"fontSize": "11px", "fontWeight": "600",
                                            "color": G if checked else MT}),
        ],
        id={"type": "gate-open-btn", "sid": sid, "gate": gate},
        n_clicks=0,
        className=f"gate-pill {'gate-done' if checked else 'gate-pending'}",
        style={
            "padding":      "5px 10px", "cursor": "pointer",
            "display":      "flex", "alignItems": "center",
            "borderRadius": "6px", "marginBottom": "4px",
            "width": "100%", "transition": "all .2s",
        },
    )


def _delivery_gate_btn(sid, g):
    if g.get("delivery"):
        label, clr, icon = "Shipped",        "#10b981", "✓"
    elif g.get("ready_to_ship"):
        label, clr, icon = "Ready to Ship",  G,         "→"
    elif g.get("in_qa"):
        label, clr, icon = "In QA",          "#fb923c", "◉"
    elif g.get("in_dev"):
        label, clr, icon = "In Dev",         B,         "◉"
    else:
        label, clr, icon = "Delivery",       MT,        "○"
    return html.Div(
        [
            html.Span(icon, style={"color": clr, "marginRight": "6px",
                                   "fontSize": "12px", "fontWeight": "700",
                                   "flexShrink": "0"}),
            html.Span(label, style={"fontSize": "11px", "fontWeight": "600",
                                    "color": clr}),
        ],
        id={"type": "gate-open-btn", "sid": sid, "gate": "delivery"},
        n_clicks=0,
        className="gate-pill gate-done" if g.get("delivery") else "gate-pill gate-pending",
        style={
            "padding":      "5px 10px", "cursor": "pointer",
            "display":      "flex", "alignItems": "center",
            "borderRadius": "6px", "marginBottom": "4px",
            "width": "100%", "transition": "all .2s",
        },
    )


def _status_badge(status):
    c     = STATUS_COLOR.get(status, MT)
    icons = {
        "NOT STARTED":   "🔴",
        "DRAFT":         "🟠",
        "STORY FROZEN":  "🟣",
        "IN DEV":        "🔵",
        "IN QA":         "🟡",
        "READY TO SHIP": "🟢",
        "SHIPPED":       "✅",
    }
    return html.Div([
        html.Span(icons.get(status, ""), style={"marginRight": "6px", "fontSize": "14px"}),
        html.Span(status, style={"fontSize": "11px", "fontWeight": "700",
                                  "letterSpacing": "0.5px", "color": c}),
    ], style={
        "background": f"{c}15", "border": f"1px solid {c}44",
        "borderRadius": "8px", "padding": "6px 12px",
        "display": "flex", "alignItems": "center",
        "minWidth": "130px", "justifyContent": "center",
    })


def _kpi_card(label, value_pct, sub, color=None):
    c = color or (G if value_pct >= 80 else A if value_pct >= 50 else R)
    return html.Div([
        html.Div(label, style={"fontSize": "10px", "fontWeight": "700", "color": MT,
                                "textTransform": "uppercase", "letterSpacing": "0.8px",
                                "marginBottom": "10px"}),
        html.Div(f"{value_pct}%", style={"fontSize": "36px", "fontWeight": "800",
                                          "color": c, "lineHeight": "1"}),
        html.Div(sub, style={"fontSize": "10px", "color": MT,
                              "marginTop": "8px", "lineHeight": "1.4"}),
        html.Div([
            html.Div(style={"width": f"{value_pct}%", "height": "3px",
                             "background": c, "borderRadius": "2px",
                             "transition": "width .5s"}),
        ], style={"width": "100%", "height": "3px",
                   "background": "rgba(255,255,255,0.08)",
                   "borderRadius": "2px", "marginTop": "12px"}),
    ], style={
        "background": CD, "border": f"1px solid {c}33",
        "borderRadius": "12px", "padding": "18px 20px",
        "flex": "1", "minWidth": "200px",
    })


def _ba_card(name, code, role, pct, done, total, color=None):
    c = color or (G if pct >= 80 else A if pct >= 50 else R)
    return html.Div([
        html.Div([
            html.Span(name, style={"fontWeight": "700", "color": TX, "fontSize": "13px"}),
            html.Span(f" {pct}%", style={"fontWeight": "800", "color": c,
                                          "fontSize": "15px", "marginLeft": "8px"}),
        ], style={"marginBottom": "4px"}),
        html.Div(html.Span(f"{code} · {role}", style={"fontSize": "10px", "color": MT})),
        html.Div([
            html.Div(style={"width": f"{pct}%", "height": "3px",
                             "background": c, "borderRadius": "2px"}),
        ], style={"width": "100%", "height": "3px",
                   "background": "rgba(255,255,255,0.08)",
                   "borderRadius": "2px", "margin": "8px 0"}),
        html.Div(f"{done} of {total} stories", style={"fontSize": "10px", "color": MT}),
    ], style={
        "background": C2, "border": f"1px solid {c}33",
        "borderRadius": "10px", "padding": "12px 16px",
        "minWidth": "160px", "flex": "1",
    })


def _matrix_cell(dev_key, month_key, val):
    _win_sep = {}
    if month_key == "M0":
        _win_sep["borderLeft"] = f"2px solid {_WIN_BORDER}"
    elif month_key == "M2":
        _win_sep["borderRight"] = f"2px solid {_WIN_BORDER}"
    if val is None:
        return html.Td("—", style={
            "textAlign": "center", "color": "rgba(255,255,255,0.15)",
            "fontSize": "12px", "padding": "10px 8px",
            "borderBottom": f"1px solid {BD}", **_win_sep,
        })
    count, sk = val
    cc = CELL_COLORS.get(sk, {"bg": C2, "text": MT, "border": BD})
    label_map = {
        "in_dev": "DEV", "in_qa": "QA", "ready_to_ship": "SHIP",
        "story_frozen": "FROZEN", "draft": "DRAFT", "not_started": "NS", "shipped": "✓",
    }
    return html.Td(
        html.Div([
            html.Div(str(count), style={"fontSize": "20px", "fontWeight": "700",
                                         "color": cc["text"], "lineHeight": "1"}),
            html.Div(label_map.get(sk, ""), style={"fontSize": "9px", "color": cc["text"],
                                                    "opacity": "0.7", "marginTop": "2px"}),
        ], style={
            "background":   cc["bg"],
            "border":       f"1px solid {cc['border']}44",
            "borderRadius": "8px", "padding": "10px 8px",
            "textAlign":    "center", "cursor": "pointer",
            "transition":   "opacity .15s",
        }, id={"type": "matrix-cell", "dev": dev_key, "month": month_key}),
        style={"padding": "6px", "borderBottom": f"1px solid {BD}", **_win_sep},
    )


def _alert(text, color=R):
    return html.Div(text, style={
        "background":   f"{color}18",
        "border":       f"1px solid {color}44",
        "borderRadius": "8px", "padding": "10px 16px",
        "fontSize":     "12px", "color": color,
        "flex": "1", "lineHeight": "1.5",
    })


def _story_matrix_cell(val, month_key=""):
    _win_sep = {}
    if month_key == "M0":
        _win_sep["borderLeft"] = f"2px solid {_WIN_BORDER}"
    elif month_key == "M2":
        _win_sep["borderRight"] = f"2px solid {_WIN_BORDER}"
    if val is None:
        return html.Td("—", style={
            "textAlign": "center", "color": "rgba(255,255,255,0.12)",
            "fontSize": "11px", "padding": "8px 4px",
            "borderBottom": f"1px solid {BD}", **_win_sep,
        })
    dev_name, sk = val
    cc      = CELL_COLORS.get(sk, {"bg": C2, "text": MT, "border": BD})
    display = (dev_name.split()[0]
               if dev_name and dev_name not in ("Unassigned","Not Specified")
               else dev_name)
    return html.Td(
        html.Div(display, style={
            "background":   cc["bg"], "color": cc["text"],
            "border":       f"1px solid {cc['border']}44",
            "borderRadius": "6px", "padding": "5px 8px",
            "fontSize":     "11px", "fontWeight": "600",
            "textAlign":    "center", "cursor": "pointer",
        }),
        style={"padding": "5px 4px", "borderBottom": f"1px solid {BD}", **_win_sep},
    )


# ─── Story table ───────────────────────────────────────────────────────────────
_TH_S = {
    "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
    "letterSpacing": "0.5px", "color": MT, "padding": "10px 16px",
    "borderBottom": f"1px solid {BD}", "textAlign": "left",
}

story_table_header = html.Tr([
    html.Th("Story",          style={**_TH_S, "width": "32%"}),
    html.Th("Developer",      style={**_TH_S, "width": "12%"}),
    html.Th("BA Responsible", style={**_TH_S, "width": "13%"}),
    html.Th("Sign-Off Gates", style={**_TH_S, "width": "21%"}),
    html.Th("Status",         style={**_TH_S, "width": "15%"}),
    html.Th("Lifecycle",      style={**_TH_S, "width": "7%", "textAlign": "center"}),
])


def _story_row(s: dict, gates: dict) -> html.Tr:
    _default_g = {f: s.get(f, False) for f in _GATE_FIELDS}
    g      = gates.get(str(s["id"]), _default_g)
    status = _status(g)
    sc     = STATUS_COLOR.get(status, MT)

    tags = [_tag(s["pri"], _pri_clr(s["pri"])), _tag(s["type"], _type_clr(s["type"]))]
    if s.get("size"):
        tags.append(_tag(s["size"], _size_clr(s["size"])))
    if s.get("hrs"):
        tags.append(html.Span(f"{s['hrs']:.0f}h",
                               style={"fontSize": "10px", "color": MT, "marginLeft": "2px"}))

    gates_col = html.Div([
        _gate_btn(s["id"], "dor",          g.get("dor",           False)),
        _gate_btn(s["id"], "story_written", g.get("story_written", False)),
    ], style={"display": "flex", "flexDirection": "column", "gap": "2px"})

    return html.Tr([
        html.Td([
            html.Div([
                html.A(f"#{s['id']}",
                       href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                       style={"color": P, "fontSize": "10px", "fontWeight": "700",
                              "textDecoration": "none", "letterSpacing": "0.3px",
                              "marginRight": "6px", "flexShrink": "0"}),
                html.Span(s.get("month", ""),
                          style={"color": MT, "fontSize": "9px", "fontWeight": "600",
                                 "background": BD, "padding": "1px 5px",
                                 "borderRadius": "3px"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
            html.A(s["title"],
                   href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                   style={"fontWeight": "600", "color": TX, "fontSize": "13px",
                          "marginBottom": "5px", "textDecoration": "none",
                          "display": "block", "lineHeight": "1.4"}),
            html.Div(tags, style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"}),
            html.Button("🕐 History", id={"type": "ticket-log-btn", "sid": s["id"]}, n_clicks=0,
                        style={"background": "none", "border": f"1px solid {BD}",
                               "borderRadius": "6px", "color": MT, "fontSize": "10px",
                               "cursor": "pointer", "padding": "2px 8px", "marginTop": "6px",
                               "transition": "color .15s"}),
        ], style={"padding": "14px 16px",
                   "borderLeft": f"3px solid {sc}",
                   "borderBottom": f"1px solid {BD}"}),
        html.Td([
            html.Div(s["dev"],      style={"color": TX, "fontSize": "13px", "fontWeight": "600"}),
            html.Div(s["dev_role"], style={"color": MT, "fontSize": "10px"}),
        ], style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td([
            html.Div(html.Span(s["ba"], style={"color": P, "fontSize": "12px", "fontWeight": "600"})),
            html.Div(f"{s['ba_code']} · {s['ba_role']}",
                     style={"color": MT, "fontSize": "10px", "marginTop": "2px"}),
        ], style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(gates_col, style={"padding": "10px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(_status_badge(status), style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(
            html.Button("📋", id={"type": "tracker-btn", "sid": s["id"]}, n_clicks=0,
                        title="Open lifecycle tracker",
                        style={"background": "none", "border": f"1px solid {BD}",
                               "borderRadius": "8px", "color": P, "fontSize": "16px",
                               "cursor": "pointer", "padding": "6px 10px",
                               "transition": "all .15s"}),
            style={"padding": "10px 8px", "borderBottom": f"1px solid {BD}",
                   "textAlign": "center"},
        ),
    ], style={"background": CD, "transition": "background .15s"})


# ─── Bug table ─────────────────────────────────────────────────────────────────
bug_table_header = html.Tr([
    html.Th("Issue",      style={**_TH_S, "width": "50%"}),
    html.Th("Developer",  style={**_TH_S, "width": "16%"}),
    html.Th("Estimated",  style={**_TH_S, "width": "14%"}),
    html.Th("Status",     style={**_TH_S, "width": "20%"}),
])

_BUG_TYPE_CLR = {"Bug": R, "Bug_UI": A, "Bug_Text": "#67e8f9"}
_BUG_STATE_CLR = {
    "Active": B, "Dev InProgress": B, "Dev Review": B, "Dev Complete": G,
    "Testing": A, "Tester Assigned": A, "Request Estimate": A,
    "Reopened": R, "Watch List": MT, "On Hold": MT,
}


def _bug_row(b: dict) -> html.Tr:
    tc   = _BUG_TYPE_CLR.get(b["type"], MT)
    tags = [_tag(b["pri"], _pri_clr(b["pri"])),
            _tag(b["type"].replace("_", " "), tc)]

    if b["estimated"]:
        est_cell = html.Div([
            html.Span("✓ Estimated",
                      style={"color": G, "fontSize": "11px", "fontWeight": "600"}),
            *([ html.Span(f"  {b['hrs']:.0f}h",
                          style={"color": MT, "fontSize": "10px", "marginLeft": "4px"})
               ] if b.get("hrs") else []),
        ])
    else:
        est_cell = html.Span("✗ Not Estimated",
                             style={"color": R, "fontSize": "11px", "fontWeight": "600"})

    sc = _BUG_STATE_CLR.get(b["state"], MT)
    state_badge = html.Span(b["state"], style={
        "fontSize": "11px", "fontWeight": "600", "color": sc,
        "background": f"{sc}18", "border": f"1px solid {sc}44",
        "borderRadius": "6px", "padding": "3px 8px",
    })

    return html.Tr([
        html.Td([
            html.Div([
                html.A(f"#{b['id']}",
                       href=f"{ADO_BASE_URL}{b['id']}", target="_blank",
                       style={"color": P, "fontSize": "10px", "fontWeight": "700",
                              "textDecoration": "none", "letterSpacing": "0.3px",
                              "marginRight": "6px", "flexShrink": "0"}),
                html.Span(b.get("month", ""),
                          style={"color": MT, "fontSize": "9px", "fontWeight": "600",
                                 "background": BD, "padding": "1px 5px", "borderRadius": "3px"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
            html.A(b["title"],
                   href=f"{ADO_BASE_URL}{b['id']}", target="_blank",
                   style={"fontWeight": "600", "color": TX, "fontSize": "13px",
                          "marginBottom": "5px", "textDecoration": "none",
                          "display": "block", "lineHeight": "1.4"}),
            html.Div(tags, style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"}),
        ], style={"padding": "14px 16px", "borderLeft": f"3px solid {tc}",
                  "borderBottom": f"1px solid {BD}"}),
        html.Td([
            html.Div(b["dev"],      style={"color": TX, "fontSize": "13px", "fontWeight": "600"}),
            html.Div(b["dev_role"], style={"color": MT, "fontSize": "10px"}),
        ], style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(est_cell,    style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(state_badge, style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
    ], style={"background": CD, "transition": "background .15s"})


def _pagination_bar(page: int, total_pages: int,
                    prev_id: str, next_id: str) -> html.Div:
    if total_pages <= 1:
        return html.Div()
    _btn = lambda label, disabled, cid: html.Button(
        label, id=cid, n_clicks=0, disabled=disabled,
        style={
            "background": "transparent",
            "border": f"1px solid {BD}",
            "borderRadius": "6px",
            "color": MT if disabled else TX,
            "fontSize": "12px",
            "cursor": "default" if disabled else "pointer",
            "padding": "4px 14px",
            "transition": "all .15s",
        },
    )
    return html.Div([
        _btn("‹ Prev", page <= 1,           prev_id),
        html.Span(f"Page {page} of {total_pages}",
                  style={"color": MT, "fontSize": "12px", "padding": "0 14px"}),
        _btn("Next ›", page >= total_pages, next_id),
    ], style={
        "display": "flex", "alignItems": "center", "justifyContent": "center",
        "gap": "8px", "padding": "12px 0",
    })


# ─── Matrix builders ────────────────────────────────────────────────────────────
def _build_dev_matrix(dev_matrix: dict, today_month: int) -> html.Table:
    ml = {
        "M0": f"M0 · {_CAL[today_month]}",
        "M1": f"M1 · {_CAL[min(today_month+1, 12)]}",
        "M2": f"M2 · {_CAL[min(today_month+2, 12)]}",
    }
    for _, lbl in _CAL.items():
        ml[lbl] = lbl

    col_headers = [html.Th("Developer", style={**_TH_S, "minWidth": "160px"})]
    for mk in MATRIX_MONTHS:
        is_plan = mk in ("M0","M1","M2")
        _hborder = {}
        if mk == "M0":
            _hborder = {"borderLeft":  f"2px solid {_WIN_BORDER}",
                        "borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M1":
            _hborder = {"borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M2":
            _hborder = {"borderTop":   f"2px solid {_WIN_BORDER}",
                        "borderRight": f"2px solid {_WIN_BORDER}"}
        col_headers.append(html.Th(ml.get(mk, mk), style={
            **_TH_S, "textAlign": "center", "minWidth": "80px",
            "color": B if mk == "M0" else P if is_plan else MT,
            **_hborder,
        }))
    col_headers.append(html.Th("Total", style={**_TH_S, "textAlign": "center"}))

    rows = []
    # Sort by total assigned items descending
    for dev_name, dv in sorted(
        dev_matrix.items(),
        key=lambda x: -sum(v[0] for v in x[1].values() if isinstance(v, tuple)),
    ):
        cells = [html.Td([
            html.Div(dev_name,  style={"color": TX, "fontWeight": "600", "fontSize": "13px"}),
            html.Div(dv["role"], style={"color": MT, "fontSize": "10px"}),
            html.Div(f"{dv['ns']} not started",
                     style={"color": R, "fontSize": "10px", "marginTop": "2px"}),
        ], style={"padding": "12px 16px", "borderBottom": f"1px solid {BD}", "minWidth": "160px"})]

        total = 0
        for mk in MATRIX_MONTHS:
            val = dv.get(mk)
            cells.append(_matrix_cell(dev_name, mk, val))
            if val:
                total += val[0]

        cells.append(html.Td(
            str(total) if total else "—",
            style={"textAlign": "center", "color": MT, "fontSize": "12px",
                   "fontWeight": "600", "padding": "10px 8px",
                   "borderBottom": f"1px solid {BD}"},
        ))
        rows.append(html.Tr(cells, style={"background": CD}))

    separator = html.Tr([
        html.Td(),
        html.Td("← 1+2 PLANNING WINDOW →", colSpan=3, style={
            "textAlign": "center", "fontSize": "10px", "color": P,
            "fontWeight": "700", "letterSpacing": "0.5px",
            "padding": "6px", "background": f"{P}0a", "borderBottom": f"1px solid {BD}",
            "borderLeft":  f"2px solid {_WIN_BORDER}",
            "borderTop":   f"2px solid {_WIN_BORDER}",
            "borderRight": f"2px solid {_WIN_BORDER}",
        }),
        html.Td("← REST OF 2026 →", colSpan=6, style={
            "textAlign": "center", "fontSize": "10px", "color": MT,
            "fontWeight": "700", "letterSpacing": "0.5px",
            "padding": "6px", "background": "rgba(255,255,255,0.02)",
            "borderBottom": f"1px solid {BD}",
        }),
        html.Td(),
    ])
    return html.Table(
        [html.Thead([separator, html.Tr(col_headers)]), html.Tbody(rows)],
        className="dev-matrix",
        style={"width": "100%", "borderCollapse": "collapse", "background": CD},
    )


def _build_story_matrix(story_matrix: list) -> html.Table:
    col_headers = [
        html.Th("Story / Title + BA", style={**_TH_S, "minWidth": "220px"}),
        html.Th("Size",               style={**_TH_S, "width": "60px"}),
    ]
    for mk in MATRIX_MONTHS:
        is_plan = mk in ("M0","M1","M2")
        _shborder = {}
        if mk == "M0":
            _shborder = {"borderLeft":  f"2px solid {_WIN_BORDER}",
                         "borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M1":
            _shborder = {"borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M2":
            _shborder = {"borderTop":   f"2px solid {_WIN_BORDER}",
                         "borderRight": f"2px solid {_WIN_BORDER}"}
        col_headers.append(html.Th(mk, style={
            **_TH_S, "textAlign": "center", "minWidth": "70px",
            "color": B if mk == "M0" else P if is_plan else MT,
            **_shborder,
        }))

    rows = []
    for sm in story_matrix:
        size_tag = _tag(sm["size"], _size_clr(sm["size"])) if sm["size"] else html.Span()
        ba_chip  = html.Span(
            f"● {sm['ba']}  ·  {sm['ba_code']}",
            style={"fontSize": "10px", "color": P, "display": "block", "marginTop": "3px"},
        )
        cells = [
            html.Td([
                html.Div(
                    [_tag(sm["pri"], _pri_clr(sm["pri"])),
                     _tag(sm["type"], _type_clr(sm["type"])),
                     html.Span(sm["title"], style={"color": TX, "fontSize": "12px",
                                                    "fontWeight": "600"})],
                    style={"display": "flex", "alignItems": "center",
                           "flexWrap": "wrap", "gap": "4px"},
                ),
                ba_chip,
            ], style={"padding": "10px 16px", "borderBottom": f"1px solid {BD}"}),
            html.Td(size_tag, style={"padding": "10px 8px", "borderBottom": f"1px solid {BD}"}),
        ]
        for mk in MATRIX_MONTHS:
            cells.append(_story_matrix_cell(sm.get(mk), mk))
        rows.append(html.Tr(cells, style={"background": CD}))

    separator = html.Tr([
        html.Td(), html.Td(),
        html.Td("← 1+2 PLANNING WINDOW →", colSpan=3, style={
            "textAlign": "center", "fontSize": "10px", "color": P,
            "fontWeight": "700", "padding": "6px",
            "background": f"{P}0a", "borderBottom": f"1px solid {BD}",
            "borderLeft":  f"2px solid {_WIN_BORDER}",
            "borderTop":   f"2px solid {_WIN_BORDER}",
            "borderRight": f"2px solid {_WIN_BORDER}",
        }),
        html.Td("← REST OF 2026 →", colSpan=6, style={
            "textAlign": "center", "fontSize": "10px", "color": MT,
            "fontWeight": "700", "padding": "6px",
            "background": "rgba(255,255,255,0.02)", "borderBottom": f"1px solid {BD}",
        }),
    ])
    return html.Table(
        [html.Thead([separator, html.Tr(col_headers)]), html.Tbody(rows)],
        className="story-matrix",
        style={"width": "100%", "borderCollapse": "collapse", "background": CD},
    )


# ─── BA Team Brief ──────────────────────────────────────────────────────────────

_BA_ROLES = [
    {
        "code": "R-01",
        "title": "Backlog Steward",
        "subtitle": "Data integrity & prioritisation",
        "responsibilities": [
            ("Issue Triage",        "Maintain all VSTS issues from Jan 2024 onwards. Classify every item by type (customer / internal) and priority (P1 → P4). No item remains unclassified for more than 2 working days."),
            ("Enhancement Triage",  "Maintain all VSTS enhancements from inception. Tag each as customer-identified or internally-identified, and size as Big / Medium / Small / Very Small. Customer Big and Medium enhancements are always surfaced first."),
            ("Priority Sequencing", "Enforce agreed priority logic in VSTS: Customer P1 Issues → Customer Big/Medium Enhancements → Internally Identified Enhancements → Lower-priority Issues. Sequencing must be visible and defensible on demand."),
            ("Backlog Hygiene",     "Every active item must carry a type, priority, size, and status. Audit weekly. Any item open ≥ 2 weeks without all four fields is a hygiene failure and escalated immediately."),
        ],
    },
    {
        "code": "R-02",
        "title": "Story Writer (M1/M2)",
        "subtitle": "Story production for the live sprint window",
        "responsibilities": [
            ("M1 Story Delivery",  "Write, review with the Product Owner, and deliver all M1 stories fully before the first day of that month. Zero exceptions."),
            ("M2 Draft Coverage",  "Produce draft stories for all M2 items by mid-M1, with acceptance criteria locked. Estimation can begin as soon as drafts are in place."),
            ("M0 Support",         "During the current month, answer developer clarification questions only. No new writing for M0 — if a story is unclear at M0, that is a M1 process failure."),
            ("Quality Assurance",  "Own story rejection rate. Every story returned by a developer due to ambiguity or missing criteria is reviewed to identify and close the root cause."),
        ],
    },
    {
        "code": "R-03",
        "title": "Pipeline & Horizon Owner",
        "subtitle": "Long-range readiness through Dec 2026",
        "responsibilities": [
            ("Long-Horizon Library",      "Ensure all customer P1 Issues and Big/Medium Enhancements through Dec 2026 have user stories written and kept estimation-ready."),
            ("Estimation Coordination",   "Facilitate estimation sessions with developers for M1/M2 and long-horizon items. Track estimated vs unestimated items weekly."),
            ("Roadmap Alignment",         "Flag conflicts between the prioritised backlog and the delivery roadmap. Escalate to the Product Owner when capacity in any month is forecast to be exceeded."),
            ("Sprint Discipline",         "Ensure the team is always writing one month ahead of where developers are building. Identify drift early and recover before it affects developer throughput."),
        ],
    },
]


def _ba_role_card(role: dict, open_: bool = False) -> html.Div:
    rows = [
        html.Div([
            html.Span(lbl, style={
                "fontFamily": "monospace", "fontSize": "11px", "fontWeight": "700",
                "color": A, "minWidth": "180px", "paddingRight": "20px",
                "flexShrink": "0",
            }),
            html.Span(desc, style={"fontSize": "13px", "color": TX, "lineHeight": "1.6"}),
        ], style={"display": "flex", "padding": "12px 0",
                  "borderBottom": f"1px solid {BD}"})
        for lbl, desc in role["responsibilities"]
    ]
    body = html.Div(rows, id={"type": "ba-role-body", "role": role["code"]},
                    style={"display": "block" if open_ else "none",
                           "padding": "4px 24px 20px"})

    header = html.Div([
        html.Div([
            html.Span(role["code"], style={
                "fontSize": "10px", "fontWeight": "700", "color": A,
                "fontFamily": "monospace", "marginRight": "14px",
                "background": f"{A}18", "border": f"1px solid {A}44",
                "borderRadius": "4px", "padding": "2px 8px",
            }),
            html.Div([
                html.Div(role["title"],    style={"fontWeight": "700", "fontSize": "15px", "color": TX}),
                html.Div(role["subtitle"], style={"fontSize": "11px", "color": MT, "marginTop": "2px"}),
            ]),
        ], style={"display": "flex", "alignItems": "center", "flex": "1"}),
        html.Button(
            "×" if open_ else "+",
            id={"type": "ba-role-toggle", "role": role["code"]},
            n_clicks=0,
            style={
                "background": "none", "border": "none",
                "color": MT, "fontSize": "22px", "cursor": "pointer",
                "lineHeight": "1", "padding": "2px 6px",
            },
        ),
    ], style={"display": "flex", "alignItems": "center", "padding": "18px 20px",
              "cursor": "pointer"})

    return html.Div([header, body], style={
        "background": C2, "borderRadius": "12px",
        "border": f"1px solid {BD}", "marginBottom": "12px",
        "overflow": "hidden",
    })


def _build_ba_brief() -> html.Div:
    # ── Sub-tab strip ─────────────────────────────────────────────────────────
    sub_tabs = html.Div([
        html.Button(lbl, id={"type": "ba-brief-tab", "tab": tid}, n_clicks=0,
                    style={
                        "background":   f"{A}22" if i == 0 else "transparent",
                        "border":       "none",
                        "borderBottom": f"2px solid {A}" if i == 0 else "2px solid transparent",
                        "color":        TX if i == 0 else MT,
                        "fontSize":     "13px", "fontWeight": "600" if i == 0 else "400",
                        "padding":      "8px 16px", "cursor": "pointer", "marginRight": "4px",
                    })
        for i, (lbl, tid) in enumerate([
            ("Role Brief",          "role"),
            ("KPI Scorecard",       "kpi"),
            ("Operating Principles","ops"),
        ])
    ], style={"display": "flex", "borderBottom": f"1px solid {BD}",
              "marginBottom": "28px"})

    # ── Role Brief content ────────────────────────────────────────────────────
    intro = html.P([
        "The BA team has two distinct functions: ",
        html.Strong("backlog stewardship", style={"color": TX}),
        " and ",
        html.Strong("story production", style={"color": TX}),
        ". The three roles below ensure neither crowds out the other.",
    ], style={"color": MT, "fontSize": "14px", "lineHeight": "1.7",
              "marginBottom": "24px"})

    role_cards = html.Div(
        [_ba_role_card(r, open_=(r["code"] == "R-01")) for r in _BA_ROLES],
        id="ba-role-cards",
    )

    note = html.Div([
        html.Div("NOTE · TEAM COMPOSITION", style={
            "fontSize": "9px", "fontWeight": "700", "color": G,
            "letterSpacing": "1.4px", "textTransform": "uppercase", "marginBottom": "8px",
        }),
        html.P(
            "Roles can be held by three individuals or distributed differently. "
            "KPIs are role-indexed, not person-indexed, so accountability remains "
            "clear regardless of assignment.",
            style={"color": MT, "fontSize": "13px", "lineHeight": "1.6", "margin": "0"},
        ),
    ], style={
        "background": f"{G}0d", "border": f"1px solid {G}44",
        "borderRadius": "10px", "padding": "16px 20px", "marginTop": "8px",
    })

    role_brief = html.Div([intro, role_cards, note], id="ba-tab-role",
                          style={"display": "block"})

    placeholder = html.Div(
        "Coming soon.",
        style={"color": MT, "fontSize": "14px", "padding": "40px 0"},
    )
    kpi_tab = html.Div(placeholder, id="ba-tab-kpi",  style={"display": "none"})
    ops_tab = html.Div(placeholder, id="ba-tab-ops",  style={"display": "none"})

    return html.Div([
        # ── Page header ───────────────────────────────────────────────────────
        html.Div([
            html.Div("BA TEAM · ROLE BRIEF & KPI SCORECARD", style={
                "fontSize": "9px", "fontWeight": "700", "color": A,
                "letterSpacing": "1.6px", "textTransform": "uppercase", "marginBottom": "8px",
            }),
            html.Div("BA Team Brief · Roles, KPIs & Principles", style={
                "fontSize": "26px", "fontWeight": "800", "color": TX, "marginBottom": "6px",
            }),
            html.Div("3-person team · 1+2 sprint planning model · VSTS-sourced backlog", style={
                "fontSize": "13px", "color": MT,
            }),
        ], style={"marginBottom": "28px"}),
        sub_tabs,
        role_brief, kpi_tab, ops_tab,
    ], style={"maxWidth": "860px", "padding": "8px 0"})


# ─── Static components ──────────────────────────────────────────────────────────
_legend = html.Div([
    *[html.Span([
        html.Span("■ ", style={"color": c}),
        html.Span(lbl, style={"color": MT, "fontSize": "11px", "marginRight": "14px"}),
    ]) for lbl, c in [("In Dev", B), ("Ready", G), ("Draft", A), ("Not Started", R)]],
    html.Span("— Click any cell for stories",
              style={"color": MT, "fontSize": "11px", "fontStyle": "italic"}),
], style={"display": "flex", "alignItems": "center", "marginBottom": "12px"})

signoff_modal = dbc.Modal([
    dbc.ModalHeader(
        html.Span("📋 Sign-Off Log", style={"fontWeight": "700", "color": TX}),
        style={"background": CD, "borderBottom": f"1px solid {BD}"},
    ),
    dbc.ModalBody(
        html.Div(id="log-body"),
        style={"background": CD, "maxHeight": "60vh", "overflowY": "auto"},
    ),
    dbc.ModalFooter(
        html.Div(id="log-footer"),
        style={"background": CD, "borderTop": f"1px solid {BD}"},
    ),
], id="signoff-modal", is_open=False, size="lg",
   style={"--bs-modal-bg": CD, "--bs-modal-border-color": BD})

ticket_log_modal = dbc.Modal([
    dbc.ModalHeader(
        html.Div(id="tlog-header"),
        style={"background": CD, "borderBottom": f"1px solid {BD}"},
    ),
    dbc.ModalBody(
        html.Div(id="tlog-body"),
        style={"background": CD, "maxHeight": "65vh", "overflowY": "auto"},
    ),
    dbc.ModalFooter(
        html.Div(id="tlog-footer"),
        style={"background": CD, "borderTop": f"1px solid {BD}"},
    ),
], id="tlog-modal", is_open=False, size="lg",
   style={"--bs-modal-bg": CD, "--bs-modal-border-color": BD})

tracker_modal = dbc.Modal([
    dbc.ModalHeader(
        html.Div(id="tracker-header"),
        style={"background": CD, "borderBottom": f"1px solid {BD}", "flexDirection": "column",
               "alignItems": "flex-start"},
        close_button=True,
    ),
    dbc.ModalBody(
        html.Div(id="tracker-body"),
        style={"background": C3, "padding": "20px 24px",
               "maxHeight": "75vh", "overflowY": "auto"},
    ),
], id="tracker-modal", is_open=False, size="xl",
   style={"--bs-modal-bg": C3, "--bs-modal-border-color": BD},
   scrollable=True)

# ── Capacity matrix panel styles (needed before matrix_panel definition) ──────
_CAP_PANEL_BASE   = {
    "position": "fixed", "top": "0", "right": "0",
    "height": "100vh", "width": "560px",
    "background": C2,
    "borderLeft": "1px solid rgba(255,255,255,0.10)",
    "zIndex": "1050",
    "display": "flex", "flexDirection": "column",
    "boxShadow": "-16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_CAP_PANEL_OPEN   = {**_CAP_PANEL_BASE, "transform": "translateX(0%)"}
_CAP_PANEL_CLOSED = {**_CAP_PANEL_BASE, "transform": "translateX(110%)"}

matrix_panel = html.Div([
    # Fixed header — dev name + month + close
    html.Div([
        html.Div([
            html.Div(id="matrix-panel-hdr", style={
                "fontWeight": "700", "fontSize": "15px", "color": TX,
            }),
        ], style={"flex": "1"}),
        html.Button("✕", id="matrix-panel-close", n_clicks=0, style={
            "background": "none", "border": "none", "color": MT,
            "fontSize": "20px", "cursor": "pointer",
            "padding": "2px 8px", "lineHeight": "1",
        }),
    ], style={
        "display": "flex", "alignItems": "flex-start",
        "padding": "18px 20px 14px",
        "borderBottom": f"1px solid {BD}",
        "flexShrink": "0",
    }),
    # Scrollable body
    html.Div(id="matrix-panel-body",
             style={"overflowY": "auto", "flex": "1", "padding": "0"}),
], id="matrix-panel", style=_CAP_PANEL_CLOSED)


def _type_filter_strip(sizes=False):
    _btn = lambda lbl, active=False: html.Button(
        lbl,
        id={"type": "type-f", "v": lbl},
        style={
            "background":   (A + "33") if active else "transparent",
            "border":       f"1px solid {A}" if active else f"1px solid {BD}",
            "borderRadius": "12px",
            "color":        A if active else MT,
            "fontSize":     "11px",
            "fontWeight":   "700" if active else "400",
            "padding":      "3px 10px", "cursor": "pointer", "marginRight": "4px",
        },
    )
    items = [
        html.Span("TYPE", style={"fontSize": "10px", "fontWeight": "700", "color": MT,
                                  "textTransform": "uppercase", "letterSpacing": "0.5px",
                                  "marginRight": "6px"}),
        _btn("All", active=True), _btn("Enhancements"), _btn("Issues"),
    ]
    if sizes:
        items += [
            html.Div(style={"width": "1px", "height": "16px",
                             "background": BD, "margin": "0 10px"}),
            html.Span("SIZE", style={"fontSize": "10px", "fontWeight": "700", "color": MT,
                                      "textTransform": "uppercase", "letterSpacing": "0.5px",
                                      "marginRight": "6px"}),
            *[html.Button(lbl, id={"type": "size-f", "v": lbl}, style={
                "background": "transparent", "border": f"1px solid {BD}",
                "borderRadius": "12px", "color": MT, "fontSize": "11px",
                "padding": "3px 10px", "cursor": "pointer", "marginRight": "4px",
            }) for lbl in ["All", "Big", "Medium", "Small", "Very Small"]],
        ]
    return html.Div(items, style={"display": "flex", "alignItems": "center",
                                   "marginBottom": "12px", "flexWrap": "wrap"})


_footer = html.Div([
    html.Span("ExpenseOnDemand · Planning Tool · expenseondemand / Solo Expenses",
              style={"color": MT, "fontSize": "10px"}),
    html.Span("Data: open Enhancements & Bugs in 2026 ADO iterations · Refreshes every 5 min",
              style={"color": MT, "fontSize": "10px"}),
], style={"display": "flex", "justifyContent": "space-between",
           "borderTop": f"1px solid {BD}", "paddingTop": "14px", "marginTop": "24px"})


# ═══════════════════════════════════════════════════════════════════════════════
# UNESTIMATED TAB BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

# filter key → color (used both in builder and in callback to restore card style)
_UNEST_CARD_COLORS = {
    "all":    R,
    "p1":     R,
    "issues": A,
    "enhanc": G,
    "devsp1": "#e879f9",
}


def _kcard_style(color: str, active: bool) -> dict:
    return {
        "background":   f"{color}22" if active else CD,
        "border":       f"1px solid {color}" if active else f"1px solid {color}33",
        "borderRadius": "12px", "padding": "18px 22px", "flex": "1", "minWidth": "160px",
        "cursor": "pointer", "transition": "all .15s",
        "boxShadow": f"0 0 18px {color}33" if active else "none",
    }


# ── Side panel style constants ────────────────────────────────────────────────
_PANEL_BASE = {
    "position": "fixed", "top": "0", "right": "0",
    "height": "100vh", "width": "500px",
    "background": C2,
    "borderLeft": f"1px solid rgba(255,255,255,0.10)",
    "zIndex": "1050",
    "display": "flex", "flexDirection": "column",
    "boxShadow": "-16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_PANEL_OPEN   = {**_PANEL_BASE, "transform": "translateX(0%)"}
_PANEL_CLOSED = {**_PANEL_BASE, "transform": "translateX(110%)"}

_BACKDROP_BASE = {
    "position": "fixed", "top": "0", "left": "0",
    "width": "100vw", "height": "100vh",
    "background": "rgba(0,0,0,0.50)",
    "zIndex": "1049",
    "transition": "opacity 0.28s ease",
}
_BACKDROP_OPEN   = {**_BACKDROP_BASE, "opacity": "1",  "pointerEvents": "all"}
_BACKDROP_CLOSED = {**_BACKDROP_BASE, "opacity": "0",  "pointerEvents": "none"}

_FLT_PANEL_BASE = {
    "position": "fixed", "top": "0", "left": "0",
    "height": "100vh", "width": "310px",
    "background": C2,
    "borderRight": f"1px solid rgba(255,255,255,0.10)",
    "zIndex": "1050",
    "display": "flex", "flexDirection": "column",
    "boxShadow": "16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_FLT_PANEL_OPEN   = {**_FLT_PANEL_BASE, "transform": "translateX(0%)"}
_FLT_PANEL_CLOSED = {**_FLT_PANEL_BASE, "transform": "translateX(-110%)"}


def _build_unest_tab(items: list[dict]) -> html.Div:
    """Build full content for the Unestimated Items tab from pre-loaded items."""
    unest_only = [s for s in items if s["est_status"] in ("unestimated", "partial")]
    if not items:
        return html.Div("No items found.",
                        style={"color": G, "fontSize": "14px", "padding": "32px"})

    total        = len(unest_only)
    p1_count     = sum(1 for s in unest_only if s["pri"] == "P1")
    issues       = sum(1 for s in unest_only if s["type"] == "Issue")
    enhancements = sum(1 for s in unest_only if s["type"] == "Enhancement")
    partial      = sum(1 for s in unest_only if s["est_status"] == "partial")
    devs_p1      = len({s["dev"] for s in unest_only
                        if s["pri"] == "P1" and s["dev"] not in ("Unassigned","Not Specified","")})
    total_devs   = len({s["dev"] for s in unest_only
                        if s["dev"] not in ("Unassigned","Not Specified","")})

    iss_pct = round(issues / total * 100) if total else 0
    enh_pct = round(enhancements / total * 100) if total else 0

    def _kcard(val, label, sub, fkey):
        color = _UNEST_CARD_COLORS[fkey]
        return html.Div([
            html.Div(str(val), style={"fontSize": "38px", "fontWeight": "800",
                                      "color": color, "lineHeight": "1"}),
            html.Div(label, style={"fontSize": "10px", "fontWeight": "700",
                                   "color": MT, "textTransform": "uppercase",
                                   "letterSpacing": "0.8px", "marginTop": "8px"}),
            html.Div(sub,   style={"fontSize": "11px", "color": MT, "marginTop": "4px"}),
        ], id={"type": "unest-kcard", "filter": fkey},
           n_clicks=0,
           style=_kcard_style(color, False))

    kpi_strip = html.Div([
        _kcard(total,        "Total Unestimated", f"{partial} partial (some tasks missing)", "all"),
        _kcard(p1_count,     "P1 Items",          "Highest urgency",                          "p1"),
        _kcard(issues,       "Issues",            f"{iss_pct}% of total",                     "issues"),
        _kcard(enhancements, "Enhancements",      f"{enh_pct}% of total",                     "enhanc"),
        _kcard(devs_p1,      "Devs with P1 Gap",  f"of {total_devs} developers",              "devsp1"),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "16px", "flexWrap": "wrap"})

    # ── Developer × Month matrix ───────────────────────────────────────────────
    month_order = ["M0","M1","M2","Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]
    months_present = sorted({s["month"] for s in items},
                            key=lambda x: month_order.index(x) if x in month_order else 99)

    # Build dev → month → {est, unest, p1_unest, p2_unest} counts
    dev_month: dict = {}
    for s in items:
        dev = s["dev"]
        if dev in ("Unassigned","Not Specified",""):
            continue
        mon = s["month"]
        if dev not in dev_month:
            dev_month[dev] = {m: {"est": 0, "unest": 0, "p1_unest": 0, "p2_unest": 0} for m in month_order}
        if s["est_status"] in ("estimated", "estimated_via_tasks"):
            dev_month[dev][mon]["est"] += 1
        else:
            dev_month[dev][mon]["unest"] += 1
            if s["pri"] == "P1": dev_month[dev][mon]["p1_unest"] += 1
            if s["pri"] == "P2": dev_month[dev][mon]["p2_unest"] += 1

    # Sort devs by total unestimated desc
    sorted_devs = sorted(dev_month.keys(),
                         key=lambda d: -sum(v["unest"] for v in dev_month[d].values()))

    today_m = date.today().month
    _mlbl = {"M0": f"M0·{_CAL[today_m]}",
             "M1": f"M1·{_CAL[min(today_m+1,12)]}",
             "M2": f"M2·{_CAL[min(today_m+2,12)]}"}
    for _, lbl in _CAL.items(): _mlbl[lbl] = lbl

    th_s = {"fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
            "letterSpacing": "0.5px", "color": MT, "padding": "10px 12px",
            "borderBottom": f"1px solid {BD}", "textAlign": "center"}

    hdr = [html.Th("Developer", style={**th_s, "textAlign": "left", "minWidth": "150px"})]
    for mk in months_present:
        hdr.append(html.Th(_mlbl.get(mk, mk), style={
            **th_s, "color": B if mk == "M0" else P if mk in ("M1","M2") else MT,
        }))
    hdr.append(html.Th("Total", style={**th_s}))

    mat_rows = []
    for dev in sorted_devs:
        dm        = dev_month[dev]
        role      = _DEV_ROLE.get(TEAM_MAPPING.get(dev, ""), "Developer")
        tot       = sum(dm[mk]["est"] + dm[mk]["unest"] for mk in months_present)
        unest_tot = sum(dm[mk]["unest"] for mk in months_present)
        cells = [html.Td([
            html.Div(dev,  style={"color": TX, "fontWeight": "600", "fontSize": "13px"}),
            html.Div(role, style={"color": MT, "fontSize": "10px"}),
        ], style={"padding": "10px 14px", "borderBottom": f"1px solid {BD}"})]

        for mk in months_present:
            est_n   = dm[mk]["est"]
            unest_n = dm[mk]["unest"]
            p1      = dm[mk]["p1_unest"]
            p2      = dm[mk]["p2_unest"]
            if est_n == 0 and unest_n == 0:
                cells.append(html.Td("—", style={
                    "textAlign": "center", "color": "rgba(255,255,255,0.15)",
                    "fontSize": "12px", "padding": "10px 8px",
                    "borderBottom": f"1px solid {BD}",
                }))
            else:
                clr_u = R if p1 > 0 else A if p2 > 0 else MT
                sub_btns = []
                if est_n > 0:
                    sub_btns.append(html.Div([
                        html.Div(str(est_n), style={"fontSize": "15px", "fontWeight": "700",
                                                    "color": G, "lineHeight": "1"}),
                        html.Div("est", style={"fontSize": "8px", "color": G,
                                               "marginTop": "1px", "opacity": "0.7"}),
                    ],
                    id={"type": "unest-matrix-cell", "dev": dev, "month": mk, "est_type": "e"},
                    n_clicks=0,
                    style={"background": f"{G}18", "border": f"1px solid {G}44",
                           "borderRadius": "6px", "padding": "5px 8px", "textAlign": "center",
                           "cursor": "pointer", "transition": "opacity .15s", "marginBottom": "3px"},
                    ))
                if unest_n > 0:
                    sub_btns.append(html.Div([
                        html.Div(str(unest_n), style={"fontSize": "15px", "fontWeight": "700",
                                                      "color": clr_u, "lineHeight": "1"}),
                        html.Div(f"P1:{p1}" if p1 else "unest",
                                 style={"fontSize": "8px", "color": R if p1 else MT,
                                        "marginTop": "1px"}),
                    ],
                    id={"type": "unest-matrix-cell", "dev": dev, "month": mk, "est_type": "u"},
                    n_clicks=0,
                    style={"background": f"{clr_u}18", "border": f"1px solid {clr_u}44",
                           "borderRadius": "6px", "padding": "5px 8px", "textAlign": "center",
                           "cursor": "pointer", "transition": "opacity .15s"},
                    ))
                cells.append(html.Td(
                    html.Div(sub_btns, style={"display": "flex", "flexDirection": "column"}),
                    style={"padding": "4px 6px", "borderBottom": f"1px solid {BD}"},
                ))

        cells.append(html.Td([
            html.Div(str(unest_tot), style={"fontWeight": "700", "fontSize": "14px",
                                            "color": R if unest_tot > 5 else A}),
            html.Div(f"+{tot - unest_tot} est" if (tot - unest_tot) > 0 else "",
                     style={"fontSize": "9px", "color": G}),
        ], style={"textAlign": "center", "padding": "10px 8px",
                   "borderBottom": f"1px solid {BD}"}))
        mat_rows.append(html.Tr(cells, style={"background": CD}))

    matrix = html.Div([
        html.Div("Estimated vs Unestimated · Developer × Month",
                 style={"fontWeight": "700", "color": TX, "fontSize": "14px",
                        "marginBottom": "12px"}),
        html.Div(
            html.Table(
                [html.Thead(html.Tr(hdr)), html.Tbody(mat_rows)],
                style={"width": "100%", "borderCollapse": "collapse", "background": CD},
            ),
            style={"background": CD, "borderRadius": "12px",
                   "border": f"1px solid {BD}", "overflow": "auto", "marginBottom": "20px"},
        ),
    ])

    # ── Priority Breakdown table ───────────────────────────────────────────────
    # Build dev → {P1, P2, P3, P4} counts (unestimated only)
    dev_pri: dict = {}
    for s in unest_only:
        dev = s["dev"]
        if dev in ("Unassigned","Not Specified",""):
            continue
        if dev not in dev_pri:
            dev_pri[dev] = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
        dev_pri[dev][s["pri"]] = dev_pri[dev].get(s["pri"], 0) + 1

    sorted_devs_p = sorted(dev_pri.keys(),
                           key=lambda d: -(dev_pri[d]["P1"]*1000 + dev_pri[d]["P2"]*100
                                          + dev_pri[d]["P3"]*10 + dev_pri[d]["P4"]))

    _td = lambda v, c=MT: html.Td(
        str(v) if v else "—",
        style={"textAlign": "center", "color": c if v else "rgba(255,255,255,0.15)",
               "fontWeight": "700" if v else "400", "fontSize": "13px",
               "padding": "12px 8px", "borderBottom": f"1px solid {BD}"},
    )
    _th2 = lambda t, w="80px": html.Th(t, style={
        "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
        "color": MT, "padding": "10px 8px", "borderBottom": f"1px solid {BD}",
        "textAlign": "center", "width": w,
    })

    pb_rows = []
    for dev in sorted_devs_p:
        dp   = dev_pri[dev]
        tot  = sum(dp.values())
        role = _DEV_ROLE.get(TEAM_MAPPING.get(dev, ""), "Developer")
        risk_lbl, risk_c = (
            ("HIGH",   R) if dp["P1"] > 0 else
            ("MEDIUM", A) if dp["P2"] > 0 else
            ("LOW",    G)
        )
        pb_rows.append(html.Tr([
            html.Td([
                html.Div(dev,  style={"color": TX, "fontWeight": "600", "fontSize": "13px"}),
                html.Div(role, style={"color": MT, "fontSize": "10px"}),
            ], style={"padding": "12px 16px", "borderBottom": f"1px solid {BD}"}),
            _td(dp["P1"], R),
            _td(dp["P2"], A),
            _td(dp["P3"], G),
            _td(dp["P4"], MT),
            html.Td(str(tot), style={
                "textAlign": "center", "color": TX, "fontWeight": "800",
                "fontSize": "14px", "padding": "12px 8px",
                "borderBottom": f"1px solid {BD}",
            }),
            html.Td(html.Span(risk_lbl, style={
                "background": f"{risk_c}22", "color": risk_c,
                "border": f"1px solid {risk_c}55", "borderRadius": "6px",
                "padding": "3px 10px", "fontSize": "11px", "fontWeight": "700",
            }), style={"textAlign": "center", "padding": "12px 8px",
                       "borderBottom": f"1px solid {BD}"}),
        ], style={"background": CD}))

    pri_table = html.Div([
        html.Div("Priority Breakdown by Developer",
                 style={"fontWeight": "700", "color": TX, "fontSize": "14px",
                        "marginBottom": "4px"}),
        html.Div("Total unestimated items per developer, split by priority",
                 style={"color": MT, "fontSize": "11px", "marginBottom": "12px"}),
        html.Div(
            html.Table([
                html.Thead(html.Tr([
                    html.Th("Developer", style={
                        "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
                        "color": MT, "padding": "10px 16px", "borderBottom": f"1px solid {BD}",
                        "textAlign": "left",
                    }),
                    _th2("P1"), _th2("P2"), _th2("P3"), _th2("P4"),
                    _th2("Total"), _th2("Risk"),
                ])),
                html.Tbody(pb_rows),
            ], style={"width": "100%", "borderCollapse": "collapse", "background": CD}),
            style={"background": CD, "borderRadius": "12px",
                   "border": f"1px solid {BD}", "overflow": "hidden"},
        ),
    ])

    # ── Partial estimates callout ──────────────────────────────────────────────
    partial_note = html.Div([], style={"display": "none"})
    if partial > 0:
        partial_note = html.Div([
            html.Span("⚠ ", style={"marginRight": "6px"}),
            html.Span(f"{partial} items have partial task estimates — "
                      "click a card to find them.",
                      style={"fontSize": "12px"}),
        ], style={
            "background": f"{A}18", "border": f"1px solid {A}44",
            "borderRadius": "8px", "padding": "10px 16px",
            "color": A, "marginBottom": "12px",
        })

    panel_hint = html.Div(
        "↑ Click a card to see the items",
        style={"color": MT, "fontSize": "11px", "textAlign": "center",
               "padding": "10px 0", "marginBottom": "16px",
               "border": f"1px dashed {BD}", "borderRadius": "8px"},
    )

    return html.Div([
        kpi_strip,
        html.Div(id="unest-item-panel", children=panel_hint),
        partial_note,
        html.Div(
            "↑ Click a cell to see items for that developer × month",
            style={"color": MT, "fontSize": "11px", "marginBottom": "8px",
                   "textAlign": "right"},
        ),
        matrix,
        pri_table,
        _footer,
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT  (function — executed fresh on every page visit)
# ═══════════════════════════════════════════════════════════════════════════════

def layout(**_):
    """Returns a shell immediately — content loaded via _init_plan callback."""
    return html.Div([
        dcc.Store(id="_plan-init", data=1),
        dcc.Loading(
            id="_plan-loading",
            type="circle",
            color="#818cf8",
            style={"minHeight": "80vh", "display": "flex",
                   "alignItems": "center", "justifyContent": "center"},
            children=html.Div(id="_plan-body"),
        ),
    ], style={"background": C3, "minHeight": "100vh",
              "fontFamily": "Inter, system-ui, sans-serif"})


def _build_full_layout():
    stories, months, init_gates, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat = \
        _load_planning_data()

    _today      = date.today()
    today_month = _today.month

    # ── KPIs ──────────────────────────────────────────────────────────────────
    m1_s = [s for s in stories if s["month"] == "M1"]
    m2_s = [s for s in stories if s["month"] == "M2"]
    lh_s = [
        s for s in stories
        if s["month"] not in ("M0","M1","M2")
        and (s["pri"] in ("P1","P2") or s["size"] in ("Big","Medium"))
    ]

    m1_ready = sum(1 for s in m1_s if s.get("dor") and s.get("story_written"))
    m1_total = len(m1_s) or 1
    m1_pct   = round(m1_ready / m1_total * 100)

    m2_draft = sum(1 for s in m2_s if s.get("dor"))
    m2_total = len(m2_s) or 1
    m2_pct   = round(m2_draft / m2_total * 100)

    lh_writ  = sum(1 for s in lh_s if s.get("dor"))
    lh_total = len(lh_s) or 1
    lh_pct   = round(lh_writ / lh_total * 100)

    m1_label = _CAL.get(today_month + 1, "M1")
    m2_label = _CAL.get(today_month + 2, "M2")

    kpi_strip = html.Div([
        _kpi_card(
            f"KPI-01 · {m1_label} Story Readiness Rate", m1_pct,
            f"{m1_ready} of {len(m1_s)} stories Ready · target 100%\n"
            f"All must be signed off before {m1_label} starts",
        ),
        _kpi_card(
            f"KPI-02 · {m2_label} Draft Coverage", m2_pct,
            f"{m2_draft} of {len(m2_s)} {m2_label} items have story started\n"
            "KPI-02 must always exceed KPI-03 in intermediate states.",
            color=R if m2_pct < 33 else None,
        ),
        _kpi_card(
            "KPI-03 · Long-Horizon Pipeline Health", lh_pct,
            f"{lh_writ} of {len(lh_s)} P1/P2/Big/Medium items (Jul–Dec) written\n"
            "Pipeline lead owns sign-off of long-horizon stories.",
            color=R if lh_pct < 33 else None,
        ),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "16px", "flexWrap": "wrap"})

    # ── Alert strip ────────────────────────────────────────────────────────────
    m1_not_ready    = len(m1_s) - m1_ready
    m2_not_started  = sum(1 for s in m2_s if not s.get("dor"))
    lh_not_started  = len(lh_s) - lh_writ
    alerts = []
    if m1_not_ready:
        alerts.append(_alert(
            f"{m1_not_ready} {m1_label} {'story' if m1_not_ready == 1 else 'stories'} not yet Ready "
            f"— must be fixed before {m1_label} starts", R,
        ))
    if m2_not_started:
        alerts.append(_alert(
            f"{m2_not_started} {m2_label} items have no story started "
            f"— target 100% Draft by mid-{m1_label}", A,
        ))
    if lh_not_started:
        alerts.append(_alert(
            f"{lh_not_started} P1/P2/Big/Medium items (Jul–Dec) still need stories written",
            "#7f5e00",
        ))
    alert_strip = html.Div(
        alerts or [_alert("All planning KPIs on track ✓", G)],
        style={"display": "flex", "gap": "10px", "marginBottom": "16px", "flexWrap": "wrap"},
    )

    # ── Month tabs ─────────────────────────────────────────────────────────────
    active_month = next(
        (m["key"] for m in months if m["key"] == "M1"),
        months[0]["key"] if months else "M1",
    )

    def _month_tabs(active: str):
        tabs = []
        for m in months:
            is_a  = m["key"] == active
            fp    = m.get("pct", 0)
            fc    = m["bc"]
            if is_a:
                bg = f"linear-gradient(to right, {P}55 {fp}%, {P}18 {fp}%)"
            elif fp > 0:
                bg = f"linear-gradient(to right, {fc}2e {fp}%, rgba(255,255,255,0.02) {fp}%)"
            else:
                bg = "rgba(255,255,255,0.02)"
            tabs.append(html.Div([
                html.Div(m["label"], style={"fontSize": "12px", "fontWeight": "700",
                                             "color": TX if is_a else MT}),
                html.Div(m["badge"], style={"fontSize": "9px", "color": m["bc"],
                                             "fontWeight": "600", "marginTop": "2px"}),
            ], id={"type": "month-tab", "month": m["key"]}, style={
                "padding":    "6px 4px", "borderRadius": "8px", "cursor": "pointer",
                "background": bg,
                "border":     f"1px solid {P}" if is_a else f"1px solid {BD}",
                "textAlign":  "center", "flex": "1", "transition": "all .15s",
            }))
        return html.Div(tabs, style={"display": "flex", "gap": "6px", "width": "100%"})

    # ── Filter bar with real BA + dev names ────────────────────────────────────
    ba_first_names  = sorted({n.split()[0] for n in ba_names}) if ba_names else []
    dev_first_names = sorted({n.split()[0] for n in dev_names})[:20]  # cap at 20

    _cs_act = lambda c, p="5px 12px": {
        "padding": p, "borderRadius": "20px", "fontSize": "12px",
        "fontWeight": "600", "cursor": "pointer",
        "background": f"{c}22", "color": c,
        "border": f"1px solid {c}", "boxShadow": f"0 0 10px {c}44",
    }
    _cs_idl = lambda p="5px 12px": {
        "padding": p, "borderRadius": "20px", "fontSize": "12px",
        "fontWeight": "500", "cursor": "pointer",
        "background": "rgba(255,255,255,0.04)", "color": MT,
        "border": "1px solid rgba(255,255,255,0.08)", "boxShadow": "none",
    }

    ba_chips = [html.Div("All BAs", id="ba-all-chip", style=_cs_act(P, "5px 14px"))]
    for ba in ba_first_names:
        ba_chips.append(html.Div(ba, id={"type": "ba-chip", "ba": ba}, style=_cs_idl("5px 14px")))

    dev_chips = [html.Div("All", id="dev-all-chip", style=_cs_act(B))]
    for dv in dev_first_names:
        dev_chips.append(html.Div(dv, id={"type": "dev-chip", "dev": dv}, style=_cs_idl()))

    show_chips = []
    for label in ["Needs Action", "All", "Ready"]:
        is_act = label == "Needs Action"
        show_chips.append(html.Div(label, id={"type": "show-chip", "show": label},
                                   style=_cs_act(A) if is_act else _cs_idl()))

    tier_chips = []
    for lbl, tid in [("All", "all"), ("Pre-DoR", "pre-dor"), ("DoR ✓", "dor"),
                     ("Story Written ✓", "story_written")]:
        tier_chips.append(html.Div(lbl, id={"type": "tier-chip", "tier": tid},
                                   style=_cs_act(G) if tid == "all" else _cs_idl()))

    def _fsec(label, color, chips):
        return html.Div([
            html.Div([
                html.Span(label, style={
                    "fontSize": "9px", "fontWeight": "800", "letterSpacing": "2px",
                    "textTransform": "uppercase", "color": color,
                }),
                html.Div(style={
                    "flex": "1", "height": "1px", "marginLeft": "10px",
                    "background": f"linear-gradient(to right, {color}55, transparent)",
                }),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
            html.Div(chips, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),
        ], style={"marginBottom": "24px"})

    filter_bar = html.Div([
        _fsec("BA",   P, ba_chips),
        _fsec("DEV",  B, dev_chips),
        _fsec("SHOW", A, show_chips),
        _fsec("GATE", G, tier_chips),
        html.Button([html.Span(id="log-count-badge")], id="signoff-log-btn", style={"display": "none"}),
    ], style={"padding": "4px 0"})

    # ── Load unestimated data ─────────────────────────────────────────────────
    unest_items = _load_unestimated_data()

    # ── Load bug data ─────────────────────────────────────────────────────────
    bug_items = _load_bug_data()

    # ── Stores ─────────────────────────────────────────────────────────────────
    stores = html.Div([
        dcc.Store(id="plan-active-tab",    data="signoff"),
        dcc.Store(id="plan-active-month",  data=active_month),
        dcc.Store(id="plan-ba-filter",     data="All BAs"),
        dcc.Store(id="plan-dev-filter",    data="All"),
        dcc.Store(id="plan-show-filter",   data="Needs Action"),
        dcc.Store(id="plan-type-filter",   data="All"),
        dcc.Store(id="plan-size-filter",   data="All"),
        dcc.Store(id="plan-story-matrix",  data=story_matrix),
        dcc.Store(id="plan-dev-stories",   data=dev_stories_flat),
        dcc.Store(id="plan-tier-filter",   data="all"),
        dcc.Store(id="gate-store",         data=init_gates),
        dcc.Store(id="log-store",          data=[]),
        dcc.Store(id="plan-stories-store", data=stories),    # real ADO data
        dcc.Store(id="plan-months-store",  data=months),     # for month-tab rebuild
        dcc.Store(id="plan-unest-store",    data=unest_items), # unestimated items
        dcc.Store(id="unest-panel-filter",  data=None),        # active side panel filter
        dcc.Store(id="unest-active-kcard", data=None),         # which KPI card is expanded
        dcc.Store(id="ticket-log-sid",      data=None),        # selected ticket for history modal
        dcc.Store(id="tracker-sid",         data=None),        # selected ticket for lifecycle tracker
        dcc.Store(id="tracker-gate-focus",  data=None),        # gate key to scroll/highlight when opening
        dcc.Store(id="tracker-data",        data={}),          # {sid, state} for tracker modal
        dcc.Store(id="plan-main-tab",       data="readiness"),
        dcc.Store(id="plan-bugs-store",     data=bug_items),   # bug items for sign-off tab
        dcc.Store(id="story-page",          data=1),
        dcc.Store(id="bug-page",            data=1),
        dcc.Store(id="ba-type-f",           data="Enhancements"),
    ])

    # ── Sprint info strip (dynamic) ──────────────────────────────────────────
    from calendar import monthrange as _mr
    from config.dev_capacity import DEFAULT_CAPACITY_H as _dch
    import sys as _sys
    _ld = _mr(_today.year, _today.month)[1]
    _sprint_info = (
        f"{_today.strftime('%b %Y')} · Sprint 1 · "
        f"Day {_today.day} of {_ld} · Default: {_dch}h/person"
    )
    _fm  = _sys.modules.get("pages_dash.focus")
    _cm  = _sys.modules.get("pages_dash.capacity_planner")
    _focus_section  = _fm.focus_tab_content()  if _fm  else html.Div("VSTS Focus Area loading…",   style={"padding": "20px", "color": MT})
    _devcap_section = _cm.layout()  if _cm  else html.Div("Developer Capacity loading…", style={"padding": "20px", "color": MT})

    # ── Full layout ────────────────────────────────────────────────────────────
    return html.Div([
        stores,
        signoff_modal,
        ticket_log_modal,
        tracker_modal,
        matrix_panel,

        # Page header
        html.Div([
            html.Div([
                html.Div("EOD · PLANNING", style={
                    "fontSize": "11px", "fontWeight": "700", "color": P,
                    "letterSpacing": "1px", "textTransform": "uppercase", "marginBottom": "4px",
                }),
                html.Div("Planning Tool · Story Readiness, Estimation & Capacity", style={
                    "fontSize": "20px", "fontWeight": "800", "color": TX,
                }),
                html.Div(
                    "KPI-01 M1 Readiness · KPI-02 M2 Coverage · "
                    "KPI-03 Long-Horizon Pipeline Health · Click any cell for more detail",
                    style={"fontSize": "11px", "color": MT, "marginTop": "4px"},
                ),
            ]),
            html.Div(_sprint_info, style={
                "fontSize": "11px", "color": MT, "whiteSpace": "nowrap",
                "alignSelf": "flex-start", "marginTop": "2px",
                "background": "rgba(255,255,255,0.04)",
                "border": f"1px solid {BD}",
                "borderRadius": "8px", "padding": "6px 14px",
            }),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "flex-start", "marginBottom": "20px"}),

        # ── Main tab navigation ────────────────────────────────────────────────
        html.Div([
            *[html.Button(
                lbl, id={"type": "plan-main-tab-btn", "tab": tid}, n_clicks=0,
                style={
                    "background":   f"{P}22" if i == 0 else "transparent",
                    "border":       f"1px solid {P}" if i == 0 else f"1px solid {BD}",
                    "borderRadius": "8px",
                    "color":        TX if i == 0 else MT,
                    "fontSize":     "13px",
                    "fontWeight":   "600" if i == 0 else "400",
                    "padding":      "7px 18px", "cursor": "pointer", "marginRight": "6px",
                },
            ) for i, (lbl, tid) in enumerate([
                ("Story Readiness",    "readiness"),
                ("Unestimated Items",  "unest"),
                ("VSTS Focus Area",    "focus"),
                ("Developer Capacity", "devcap"),
                ("BA Team Brief",      "bateam"),
            ])],
        ], style={"display": "flex", "alignItems": "center", "gap": "4px",
                  "marginBottom": "20px", "borderBottom": f"1px solid {BD}",
                  "paddingBottom": "12px"}),

        # ── Story Readiness section ────────────────────────────────────────────
        html.Div([
            kpi_strip,

            # Sub-tab navigation (BA Sign-Off · By Developer · By Story)
            html.Div([
                html.Span("★ ", style={"color": P, "fontSize": "16px"}),
                *[html.Button(
                    lbl, id={"type": "plan-tab", "tab": tid}, n_clicks=0,
                    style={
                        "background":   f"{P}22" if i == 0 else "transparent",
                        "border":       f"1px solid {P}" if i == 0 else f"1px solid {BD}",
                        "borderRadius": "8px",
                        "color":        TX if i == 0 else MT,
                        "fontSize":     "13px",
                        "fontWeight":   "600" if i == 0 else "400",
                        "padding":      "7px 18px", "cursor": "pointer", "marginRight": "6px",
                    },
                ) for i, (lbl, tid) in enumerate([
                    ("BA Sign-Off",  "signoff"),
                    ("By Developer", "bydev"),
                    ("By Story",     "bystory"),
                ])],
                html.Button([
                    html.Span("⚙", style={"marginRight": "6px", "fontSize": "13px"}),
                    html.Span("Filters", style={"fontSize": "12px", "fontWeight": "600"}),
                ], id="ba-flt-open-btn", n_clicks=0, style={
                    "display": "flex", "alignItems": "center", "marginLeft": "auto",
                    "background": "transparent", "border": f"1px solid {BD}",
                    "borderRadius": "8px", "color": MT,
                    "padding": "6px 14px", "cursor": "pointer",
                    "transition": "border-color .15s, color .15s",
                }),
            ], style={
                "display": "flex", "alignItems": "center", "gap": "4px",
                "position": "sticky", "top": "58px", "zIndex": "22",
                "background": C3,
                "paddingTop": "8px", "paddingBottom": "8px",
                "marginBottom": "0",
                "borderBottom": f"1px solid {BD}",
            }),

            # ── BA Sign-Off tab ────────────────────────────────────────────────
            html.Div(id="tab-signoff", children=[
                # Frozen iteration filter — sticks below the sub-tab nav
                html.Div(id="month-tabs-container", children=_month_tabs(active_month),
                         style={
                             "position": "sticky", "top": "108px", "zIndex": "20",
                             "background": C3,
                             "paddingTop": "10px", "paddingBottom": "10px",
                             "marginBottom": "4px",
                             "boxShadow": "0 4px 20px rgba(0,0,0,0.45)",
                         }),
                dcc.Loading(
                    type="circle", color="#818cf8", style={"minHeight": "60px"},
                    children=html.Div(id="readiness-header"),
                ),
                # Enhancements section (shown by default)
                html.Div([
                    dcc.Loading(
                        type="circle", color="#818cf8", style={"minHeight": "120px"},
                        children=html.Div([
                            html.Table([
                                html.Thead(story_table_header),
                                html.Tbody(id="story-tbody"),
                            ], style={"width": "100%", "borderCollapse": "collapse"}),
                        ], style={
                            "background": CD, "borderRadius": "12px",
                            "border": f"1px solid {BD}", "overflow": "hidden", "marginBottom": "4px",
                        }),
                    ),
                    html.Div([
                        html.Button("‹ Prev", id="story-page-prev", n_clicks=0, disabled=True,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": MT, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                        html.Span(id="story-page-info",
                                  style={"color": MT, "fontSize": "12px", "padding": "0 14px"}),
                        html.Button("Next ›", id="story-page-next", n_clicks=0, disabled=False,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": TX, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                    ], id="story-pagination", style={
                        "display": "none", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0",
                    }),
                ], id="enh-section"),
                # Issues section (hidden by default, shown when TYPE=Issues)
                html.Div([
                    dcc.Loading(
                        type="circle", color="#818cf8", style={"minHeight": "120px"},
                        children=html.Div([
                            html.Table([
                                html.Thead(bug_table_header),
                                html.Tbody(id="bug-tbody"),
                            ], style={"width": "100%", "borderCollapse": "collapse"}),
                        ], style={
                            "background": CD, "borderRadius": "12px",
                            "border": f"1px solid {BD}", "overflow": "hidden", "marginBottom": "4px",
                        }),
                    ),
                    html.Div([
                        html.Button("‹ Prev", id="bug-page-prev", n_clicks=0, disabled=True,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": MT, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                        html.Span(id="bug-page-info",
                                  style={"color": MT, "fontSize": "12px", "padding": "0 14px"}),
                        html.Button("Next ›", id="bug-page-next", n_clicks=0, disabled=False,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": TX, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                    ], id="bug-pagination", style={
                        "display": "none", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0",
                    }),
                ], id="bug-section", style={"display": "none"}),
                _footer,
            ]),

            # ── By Developer tab ──────────────────────────────────────────────
            html.Div(id="tab-bydev", style={"display": "none"}, children=[
                alert_strip,
                html.Div([_type_filter_strip(), _legend]),
                html.Div(
                    id="dev-matrix-wrap",
                    children=[_build_dev_matrix(dev_matrix, today_month)],
                    style={
                        "background": CD, "borderRadius": "12px",
                        "border": f"1px solid {BD}", "overflow": "auto", "marginBottom": "12px",
                    },
                ),
                _footer,
            ]),

            # ── By Story tab ──────────────────────────────────────────────────
            html.Div(id="tab-bystory", style={"display": "none"}, children=[
                alert_strip,
                _type_filter_strip(sizes=True),
                _legend,
                html.Div(
                    id="story-matrix-wrap",
                    children=[_build_story_matrix(story_matrix)],
                    style={
                        "background": CD, "borderRadius": "12px",
                        "border": f"1px solid {BD}", "overflow": "auto", "marginBottom": "12px",
                    },
                ),
                _footer,
            ]),

        ], id="main-sec-readiness"),

        # ── Unestimated Items section ──────────────────────────────────────────
        html.Div(id="main-sec-unest", style={"display": "none"},
                 children=[_build_unest_tab(unest_items)]),

        # ── VSTS Focus Area section ────────────────────────────────────────────
        html.Div(id="main-sec-focus", style={"display": "none"},
                 children=[_focus_section]),

        # ── Developer Capacity section ─────────────────────────────────────────
        html.Div(id="main-sec-devcap", style={"display": "none"},
                 children=[_devcap_section]),

        # ── BA Team Brief section ─────────────────────────────────────────────
        html.Div(id="main-sec-bateam", style={"display": "none"},
                 children=[_build_ba_brief()]),

        # ── BA filters left panel ─────────────────────────────────────────────
        html.Div(id="ba-flt-backdrop", n_clicks=0, style=_BACKDROP_CLOSED),
        html.Div([
            html.Div([
                html.Span("Filters", style={
                    "fontWeight": "700", "fontSize": "15px", "color": TX, "flex": "1",
                }),
                html.Button("✕", id="ba-flt-panel-close", n_clicks=0, style={
                    "background": "none", "border": "none", "color": MT,
                    "fontSize": "20px", "cursor": "pointer", "padding": "2px 8px",
                    "lineHeight": "1",
                }),
            ], style={
                "display": "flex", "alignItems": "center",
                "padding": "18px 20px 14px",
                "borderBottom": f"1px solid {BD}",
                "flexShrink": "0",
            }),
            html.Div([
                # TYPE section — same vertical section style as filter_bar
                html.Div([
                    html.Div([
                        html.Span("TYPE", style={
                            "fontSize": "9px", "fontWeight": "800", "letterSpacing": "2px",
                            "textTransform": "uppercase", "color": P,
                        }),
                        html.Div(style={
                            "flex": "1", "height": "1px", "marginLeft": "10px",
                            "background": f"linear-gradient(to right, {P}55, transparent)",
                        }),
                    ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
                    html.Div([
                        *[html.Button(lbl, id={"type": "ba-type-btn", "v": lbl}, n_clicks=0, style={
                            "background": f"{P}22" if lbl == "Enhancements" else "rgba(255,255,255,0.04)",
                            "border": f"1px solid {P}" if lbl == "Enhancements" else "1px solid rgba(255,255,255,0.08)",
                            "borderRadius": "20px",
                            "color": P if lbl == "Enhancements" else MT,
                            "fontSize": "12px", "fontWeight": "600" if lbl == "Enhancements" else "500",
                            "padding": "5px 14px", "cursor": "pointer",
                            "boxShadow": f"0 0 10px {P}44" if lbl == "Enhancements" else "none",
                        }) for lbl in ("Enhancements", "Issues")],
                    ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),
                ], style={"marginBottom": "24px"}),
                # BA / DEV / SHOW / GATE sections
                filter_bar,
            ], style={"overflowY": "auto", "flex": "1", "padding": "16px 20px"}),
        ], id="ba-flt-panel", style=_FLT_PANEL_CLOSED),

        # ── Unestimated items side drawer (fixed, always in DOM) ──────────────
        html.Div(id="unest-backdrop", n_clicks=0, style=_BACKDROP_CLOSED),
        html.Div([
            # Header
            html.Div([
                html.Div(id="unest-panel-title",
                         style={"fontWeight": "700", "fontSize": "15px", "color": TX,
                                "flex": "1"}),
                html.Button("✕", id="unest-panel-close", n_clicks=0, style={
                    "background": "none", "border": "none", "color": MT,
                    "fontSize": "20px", "cursor": "pointer", "padding": "2px 8px",
                    "lineHeight": "1", "transition": "color .15s",
                }),
            ], style={
                "display": "flex", "alignItems": "center",
                "padding": "18px 20px 14px",
                "borderBottom": f"1px solid {BD}",
                "flexShrink": "0",
            }),
            # Scrollable body
            html.Div(id="unest-panel-body",
                     style={"overflowY": "auto", "flex": "1", "padding": "16px 20px"}),
        ], id="unest-side-panel", style=_PANEL_CLOSED),

    ], style={
        "padding":    "24px 32px",
        "background": C3,
        "minHeight":  "100vh",
        "fontFamily": "Inter, system-ui, sans-serif",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

@callback(
    Output("_plan-body", "children"),
    Input("_plan-init", "data"),
)
def _init_plan(_):
    return _build_full_layout()

# ── 1. Tab switching ──────────────────────────────────────────────────────────
@callback(
    Output("tab-signoff",                    "style"),
    Output("tab-bydev",                      "style"),
    Output("tab-bystory",                    "style"),
    Output("plan-active-tab",                "data"),
    Output({"type": "plan-tab", "tab": ALL}, "style"),
    Input({"type": "plan-tab", "tab": ALL},  "n_clicks"),
    State("plan-active-tab",                 "data"),
    State({"type": "plan-tab", "tab": ALL},  "id"),
    prevent_initial_call=True,
)
def _switch_tab(n_clicks, current, btn_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    tab  = triggered["tab"]
    show = {"display": "block"}
    hide = {"display": "none"}
    btn_styles = [
        _TAB_BTN_ACT if bid["tab"] == tab else _TAB_BTN_IDL
        for bid in (btn_ids or [])
    ]
    return (
        show if tab == "signoff" else hide,
        show if tab == "bydev"   else hide,
        show if tab == "bystory" else hide,
        tab,
        btn_styles,
    )



# ── 1b. Main section tab switching ────────────────────────────────────────────
_MAIN_ACT = {
    "background": f"{P}22", "border": f"1px solid {P}", "borderRadius": "8px",
    "color": TX, "fontSize": "13px", "fontWeight": "600",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}
_MAIN_IDL = {
    "background": "transparent", "border": f"1px solid {BD}", "borderRadius": "8px",
    "color": MT, "fontSize": "13px", "fontWeight": "400",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}

@callback(
    Output("main-sec-readiness",                         "style"),
    Output("main-sec-unest",                             "style"),
    Output("main-sec-focus",                             "style"),
    Output("main-sec-devcap",                            "style"),
    Output("main-sec-bateam",                            "style"),
    Output("plan-main-tab",                              "data"),
    Output({"type": "plan-main-tab-btn", "tab": ALL},   "style"),
    Input({"type": "plan-main-tab-btn", "tab": ALL},    "n_clicks"),
    State({"type": "plan-main-tab-btn", "tab": ALL},    "id"),
    prevent_initial_call=True,
)
def _switch_main_tab(n_clicks, btn_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    tab  = triggered["tab"]
    show = {"display": "block"}
    hide = {"display": "none"}
    btn_styles = [
        _MAIN_ACT if bid["tab"] == tab else _MAIN_IDL
        for bid in (btn_ids or [])
    ]
    return (
        show if tab == "readiness" else hide,
        show if tab == "unest"     else hide,
        show if tab == "focus"     else hide,
        show if tab == "devcap"    else hide,
        show if tab == "bateam"    else hide,
        tab,
        btn_styles,
    )


# ── 2. Month tab click ────────────────────────────────────────────────────────
@callback(
    Output("plan-active-month",    "data"),
    Output("month-tabs-container", "children"),
    Input({"type": "month-tab", "month": ALL}, "n_clicks"),
    State("plan-active-month",  "data"),
    State("plan-months-store",  "data"),
    prevent_initial_call=True,
)
def _select_month(n_clicks, current, months_data):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    new_month  = triggered["month"]
    months     = months_data or []
    tabs = []
    for m in months:
        is_a  = m["key"] == new_month
        fp    = m.get("pct", 0)
        fc    = m["bc"]
        if is_a:
            bg = f"linear-gradient(to right, {P}55 {fp}%, {P}18 {fp}%)"
        elif fp > 0:
            bg = f"linear-gradient(to right, {fc}2e {fp}%, rgba(255,255,255,0.02) {fp}%)"
        else:
            bg = "rgba(255,255,255,0.02)"
        tabs.append(html.Div([
            html.Div(m["label"], style={"fontSize": "12px", "fontWeight": "700",
                                         "color": TX if is_a else MT}),
            html.Div(m["badge"], style={"fontSize": "9px", "color": m["bc"],
                                         "fontWeight": "600", "marginTop": "2px"}),
        ], id={"type": "month-tab", "month": m["key"]}, style={
            "padding":    "6px 4px", "borderRadius": "8px", "cursor": "pointer",
            "background": bg,
            "border":     f"1px solid {P}" if is_a else f"1px solid {BD}",
            "textAlign":  "center", "flex": "1", "transition": "all .15s",
        }))
    return new_month, html.Div(tabs, style={"display": "flex", "gap": "6px", "width": "100%"})


# ── 3. (Gate direct-toggle removed — gates auto-derive from lifecycle tracker) ─


# ── 4. Re-render story table + readiness header ───────────────────────────────
@callback(
    Output("story-tbody",       "children"),
    Output("readiness-header",  "children"),
    Output("story-page-info",   "children"),
    Output("story-page-prev",   "disabled"),
    Output("story-page-next",   "disabled"),
    Output("story-pagination",  "style"),
    Input("gate-store",          "data"),
    Input("plan-active-month",   "data"),
    Input("plan-ba-filter",      "data"),
    Input("plan-dev-filter",     "data"),
    Input("plan-show-filter",    "data"),
    Input("plan-type-filter",    "data"),
    Input("plan-tier-filter",    "data"),
    Input("story-page",          "data"),
    State("plan-stories-store",  "data"),
)
def _render_stories(gates, month, ba_f, dev_f, show_f, type_f, tier_f, page, stories_data):
    all_month = [s for s in (stories_data or []) if s["month"] == month]
    stories   = list(all_month)

    if ba_f and ba_f != "All BAs":
        stories = [s for s in stories if s["ba"].startswith(ba_f)]
    if dev_f and dev_f != "All":
        stories = [s for s in stories if s["dev"].split()[0] == dev_f]
    _actionable = {"NOT STARTED", "DRAFT"}
    if show_f == "Needs Action":
        stories = [s for s in stories
                   if _status(gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS})) in _actionable]
    elif show_f == "Ready":
        stories = [s for s in stories
                   if _status(gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS})) not in _actionable]
    if type_f == "Enhancements":
        stories = [s for s in stories if s["type"] == "ENH"]
    elif type_f == "Issues":
        stories = [s for s in stories if s["type"] == "ISSUE"]

    if tier_f and tier_f != "all":
        def _gst(s):
            return gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS})
        if tier_f == "pre-dor":
            stories = [s for s in stories if not _gst(s)["dor"]]
        elif tier_f == "dor":
            stories = [s for s in stories if _gst(s)["dor"] and not _gst(s)["story_written"]]
        elif tier_f == "story_written":
            stories = [s for s in stories if _gst(s)["story_written"]]

    _pri_ord = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    def _sort_key(s):
        st = _status(gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS}))
        return (0 if st in {"NOT STARTED", "DRAFT"} else 1, _pri_ord.get(s["pri"], 9), s["id"])
    stories.sort(key=_sort_key)

    # Paginate
    total_filtered = len(stories)
    total_pages    = max(1, -(-total_filtered // _PAGE_SIZE))  # ceiling div
    page           = max(1, min(page or 1, total_pages))
    start          = (page - 1) * _PAGE_SIZE
    page_stories   = stories[start : start + _PAGE_SIZE]

    rows = [_story_row(s, gates) for s in page_stories]
    if not rows:
        rows = [html.Tr(html.Td(
            "No stories match the current filters.",
            colSpan=6,
            style={"textAlign": "center", "color": MT, "padding": "32px"},
        ))]

    _pag_style_show = {"display": "flex", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0"}
    _pag_style_hide = {"display": "none"}
    if total_pages <= 1:
        pag_style    = _pag_style_hide
        page_info    = ""
        prev_disabled = True
        next_disabled = True
    else:
        pag_style    = _pag_style_show
        page_info    = f"Page {page} of {total_pages}"
        prev_disabled = (page <= 1)
        next_disabled = (page >= total_pages)

    # Readiness header (always uses the full month, not filtered)
    _not_actionable = {"STORY FROZEN", "IN DEV", "IN QA", "READY TO SHIP", "SHIPPED"}
    ready = sum(
        1 for s in all_month
        if _status(gates.get(str(s["id"]),
                   {f: s.get(f, False) for f in _GATE_FIELDS})) in _not_actionable
    )
    total = len(all_month)
    pct   = round(ready / total * 100) if total else 0
    c     = G if pct >= 80 else A if pct >= 50 else R

    # Group by BA
    ba_groups: dict = {}
    for s in all_month:
        key = (s["ba"], s["ba_code"], s["ba_role"])
        ba_groups.setdefault(key, []).append(s)

    ba_cards = []
    for (ba_name, ba_code, ba_role), ss in sorted(ba_groups.items()):
        r = sum(
            1 for s in ss
            if _status(gates.get(str(s["id"]),
                       {f: s.get(f, False) for f in _GATE_FIELDS})) in _not_actionable
        )
        ba_cards.append(
            _ba_card(ba_name, ba_code, ba_role,
                     round(r / len(ss) * 100) if ss else 100, r, len(ss))
        )

    header = html.Div([
        html.Div([
            # Left — month + label
            html.Div([
                html.Span(month, style={"color": P, "fontSize": "13px", "fontWeight": "700",
                                        "marginRight": "4px"}),
                html.Span("· READINESS", style={"color": MT, "fontSize": "11px",
                                                  "fontWeight": "600", "textTransform": "uppercase",
                                                  "letterSpacing": "1px"}),
            ], style={"flexShrink": "0"}),
            # Center — progress bar
            html.Div([
                html.Div(style={
                    "width": f"{pct}%", "height": "100%",
                    "background": f"linear-gradient(to right, {c}88, {c})",
                    "borderRadius": "4px",
                    "transition": "width 0.5s ease",
                    "minWidth": "2px" if pct > 0 else "0",
                }),
            ], style={
                "flex": "1", "height": "6px",
                "background": "rgba(255,255,255,0.06)",
                "borderRadius": "4px", "margin": "0 20px",
            }),
            # Right — percentage + count
            html.Div([
                html.Span(f"{pct}%", style={"color": c, "fontSize": "22px",
                                             "fontWeight": "800", "marginRight": "10px"}),
                html.Span(f"{ready} / {total} Ready",
                          style={"color": MT, "fontSize": "12px", "whiteSpace": "nowrap"}),
            ], style={"display": "flex", "alignItems": "center", "flexShrink": "0"}),
        ], style={
            "display": "flex", "alignItems": "center",
            "background": CD, "border": f"1px solid {BD}",
            "borderRadius": "12px", "padding": "14px 20px",
            "marginBottom": "12px",
        }),
        html.Div(ba_cards,
                 style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
                         "marginBottom": "16px"}),
    ])
    return rows, header, page_info, prev_disabled, next_disabled, pag_style


@callback(
    Output("story-page", "data"),
    Input("plan-active-month", "data"),
    Input("plan-ba-filter",    "data"),
    Input("plan-dev-filter",   "data"),
    Input("plan-show-filter",  "data"),
    Input("plan-type-filter",  "data"),
    Input("plan-tier-filter",  "data"),
    prevent_initial_call=True,
)
def _reset_story_page(*_):
    return 1


@callback(
    Output("story-page", "data", allow_duplicate=True),
    Input("story-page-prev", "n_clicks"),
    State("story-page",      "data"),
    prevent_initial_call=True,
)
def _story_prev(_, page):
    return max(1, (page or 1) - 1)


@callback(
    Output("story-page", "data", allow_duplicate=True),
    Input("story-page-next", "n_clicks"),
    State("story-page",      "data"),
    prevent_initial_call=True,
)
def _story_next(_, page):
    return (page or 1) + 1


# ── 4b. Render bug table ──────────────────────────────────────────────────────
@callback(
    Output("bug-tbody",       "children"),
    Output("bug-page-info",   "children"),
    Output("bug-page-prev",   "disabled"),
    Output("bug-page-next",   "disabled"),
    Output("bug-pagination",  "style"),
    Input("plan-active-month", "data"),
    Input("bug-page",          "data"),
    State("plan-bugs-store",   "data"),
)
def _render_bugs(month, page, bugs_data):
    bugs = [b for b in (bugs_data or []) if b["month"] == month]
    bugs.sort(key=lambda b: (b["pri"], b["id"]))

    total_pages = max(1, -(-len(bugs) // _PAGE_SIZE))
    page        = max(1, min(page or 1, total_pages))
    start       = (page - 1) * _PAGE_SIZE
    page_bugs   = bugs[start : start + _PAGE_SIZE]

    rows = [_bug_row(b) for b in page_bugs]
    if not rows:
        rows = [html.Tr(html.Td(
            "No issues for this iteration.",
            colSpan=5,
            style={"textAlign": "center", "color": MT, "padding": "28px"},
        ))]

    _pag_style_show = {"display": "flex", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0"}
    if total_pages <= 1:
        return rows, "", True, True, {"display": "none"}
    return rows, f"Page {page} of {total_pages}", (page <= 1), (page >= total_pages), _pag_style_show


@callback(
    Output("bug-page", "data"),
    Input("plan-active-month", "data"),
    prevent_initial_call=True,
)
def _reset_bug_page(_):
    return 1


@callback(
    Output("bug-page", "data", allow_duplicate=True),
    Input("bug-page-prev", "n_clicks"),
    State("bug-page",      "data"),
    prevent_initial_call=True,
)
def _bug_prev(_, page):
    return max(1, (page or 1) - 1)


# ── TYPE filter (BA Sign-Off bottom strip) ─────────────────────────────────────
@callback(
    Output("ba-type-f", "data"),
    Output({"type": "ba-type-btn", "v": "Enhancements"}, "style"),
    Output({"type": "ba-type-btn", "v": "Issues"},       "style"),
    Input({"type": "ba-type-btn", "v": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _ba_type_filter(n_clicks):
    _act = {"background": f"{P}22", "border": f"1px solid {P}", "borderRadius": "20px",
            "color": P, "fontSize": "12px", "fontWeight": "600",
            "padding": "5px 14px", "cursor": "pointer", "boxShadow": f"0 0 10px {P}44"}
    _idl = {"background": "rgba(255,255,255,0.04)", "border": "1px solid rgba(255,255,255,0.08)",
            "borderRadius": "20px", "color": MT, "fontSize": "12px", "fontWeight": "500",
            "padding": "5px 14px", "cursor": "pointer", "boxShadow": "none"}
    triggered = ctx.triggered_id
    v = triggered.get("v", "Enhancements") if isinstance(triggered, dict) else "Enhancements"
    styles = {lbl: (_act if lbl == v else _idl) for lbl in ("Enhancements", "Issues")}
    return v, styles["Enhancements"], styles["Issues"]


@callback(
    Output("enh-section", "style"),
    Output("bug-section", "style"),
    Input("ba-type-f", "data"),
)
def _toggle_ba_section(ba_type):
    if ba_type == "Issues":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


# ── BA filter panel toggle ────────────────────────────────────────────────────
@callback(
    Output("ba-flt-panel",    "style"),
    Output("ba-flt-backdrop", "style"),
    Input("ba-flt-open-btn",    "n_clicks"),
    Input("ba-flt-panel-close", "n_clicks"),
    Input("ba-flt-backdrop",    "n_clicks"),
    prevent_initial_call=True,
)
def _toggle_ba_filter_panel(open_n, close_n, backdrop_n):
    if ctx.triggered_id == "ba-flt-open-btn":
        return _FLT_PANEL_OPEN, _BACKDROP_OPEN
    return _FLT_PANEL_CLOSED, _BACKDROP_CLOSED


@callback(
    Output("bug-page", "data", allow_duplicate=True),
    Input("bug-page-next", "n_clicks"),
    State("bug-page",      "data"),
    prevent_initial_call=True,
)
def _bug_next(_, page):
    return (page or 1) + 1


# ── 5. BA filter chip ─────────────────────────────────────────────────────────
@callback(
    Output("plan-ba-filter", "data"),
    Input("ba-all-chip",                    "n_clicks"),
    Input({"type": "ba-chip", "ba": ALL},   "n_clicks"),
    prevent_initial_call=True,
)
def _ba_filter(all_clicks, ba_clicks):
    triggered = ctx.triggered_id
    if triggered == "ba-all-chip":
        return "All BAs"
    if isinstance(triggered, dict):
        return triggered.get("ba", "All BAs")
    return "All BAs"


# ── 6. Dev filter chip ────────────────────────────────────────────────────────
@callback(
    Output("plan-dev-filter", "data"),
    Input("dev-all-chip",                    "n_clicks"),
    Input({"type": "dev-chip", "dev": ALL},  "n_clicks"),
    prevent_initial_call=True,
)
def _dev_filter(all_clicks, dev_clicks):
    triggered = ctx.triggered_id
    if triggered == "dev-all-chip":
        return "All"
    if isinstance(triggered, dict):
        return triggered.get("dev", "All")
    return "All"


# ── 7. Show filter chip ───────────────────────────────────────────────────────
@callback(
    Output("plan-show-filter", "data"),
    Input({"type": "show-chip", "show": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _show_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("show", "Needs Action")
    return "Needs Action"


# ── 8. Type filter buttons ────────────────────────────────────────────────────
@callback(
    Output("plan-type-filter", "data"),
    Input({"type": "type-f", "v": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _type_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("v", "All")
    return "All"


# ── Chip highlight helpers ─────────────────────────────────────────────────────
def _chip_style(active, size="md", color=None):
    c   = color or P
    pad = "5px 14px" if size == "lg" else "5px 12px"
    if active:
        return {
            "padding": pad, "borderRadius": "20px", "fontSize": "12px",
            "fontWeight": "600", "cursor": "pointer",
            "background": f"{c}22", "color": c,
            "border": f"1px solid {c}", "boxShadow": f"0 0 10px {c}44",
        }
    return {
        "padding": pad, "borderRadius": "20px", "fontSize": "12px",
        "fontWeight": "500", "cursor": "pointer",
        "background": "rgba(255,255,255,0.04)", "color": MT,
        "border": "1px solid rgba(255,255,255,0.08)", "boxShadow": "none",
    }


@callback(
    Output("dev-all-chip",                   "style"),
    Output({"type": "dev-chip", "dev": ALL}, "style"),
    Input("plan-dev-filter", "data"),
    State({"type": "dev-chip", "dev": ALL}, "id"),
)
def _update_dev_chips(active, chip_ids):
    all_style   = _chip_style(active == "All", color=B)
    chip_styles = [_chip_style(cid["dev"] == active, color=B) for cid in (chip_ids or [])]
    return all_style, chip_styles


@callback(
    Output("ba-all-chip",                   "style"),
    Output({"type": "ba-chip", "ba": ALL},  "style"),
    Input("plan-ba-filter", "data"),
    State({"type": "ba-chip", "ba": ALL},   "id"),
)
def _update_ba_chips(active, chip_ids):
    all_style   = _chip_style(active == "All BAs", size="lg", color=P)
    chip_styles = [_chip_style(cid["ba"] == active, size="lg", color=P) for cid in (chip_ids or [])]
    return all_style, chip_styles


@callback(
    Output({"type": "show-chip", "show": ALL}, "style"),
    Input("plan-show-filter", "data"),
    State({"type": "show-chip", "show": ALL}, "id"),
)
def _update_show_chips(active, chip_ids):
    styles = []
    for cid in (chip_ids or []):
        label = cid["show"]
        color = A if label == "Needs Action" else P
        styles.append(_chip_style(label == active, color=color))
    return styles


# ── Tier filter chip ─────────────────────────────────────────────────────────
@callback(
    Output("plan-tier-filter", "data"),
    Input({"type": "tier-chip", "tier": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _tier_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("tier", "all")
    return "all"


@callback(
    Output({"type": "tier-chip", "tier": ALL}, "style"),
    Input("plan-tier-filter", "data"),
    State({"type": "tier-chip", "tier": ALL}, "id"),
)
def _update_tier_chips(active, chip_ids):
    return [_chip_style(cid["tier"] == active, color=G) for cid in (chip_ids or [])]


@callback(
    Output({"type": "type-f", "v": ALL}, "style"),
    Input("plan-type-filter", "data"),
    State({"type": "type-f", "v": ALL}, "id"),
)
def _update_type_chips(active, chip_ids):
    styles = []
    for cid in (chip_ids or []):
        is_active = cid["v"] == active
        styles.append({
            "background":   (A + "33") if is_active else "transparent",
            "border":       f"1px solid {A}" if is_active else f"1px solid {BD}",
            "borderRadius": "12px",
            "color":        A if is_active else MT,
            "fontSize":     "11px",
            "fontWeight":   "700" if is_active else "400",
            "padding":      "3px 10px", "cursor": "pointer", "marginRight": "4px",
        })
    return styles


# ── BA Team Brief — role card accordion ──────────────────────────────────────
@callback(
    Output({"type": "ba-role-body",   "role": ALL}, "style"),
    Output({"type": "ba-role-toggle", "role": ALL}, "children"),
    Input({"type": "ba-role-toggle",  "role": ALL}, "n_clicks"),
    State({"type": "ba-role-body",    "role": ALL}, "style"),
    State({"type": "ba-role-toggle",  "role": ALL}, "id"),
    prevent_initial_call=True,
)
def _toggle_ba_role(n_clicks, body_styles, toggle_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    new_styles  = []
    new_icons   = []
    for tid, style in zip(toggle_ids, body_styles):
        currently_open = style.get("display") != "none"
        if tid["role"] == triggered["role"]:
            new_open = not currently_open
        else:
            new_open = currently_open
        new_styles.append({"display": "block", "padding": "4px 24px 20px"}
                          if new_open else {"display": "none"})
        new_icons.append("×" if new_open else "+")
    return new_styles, new_icons


# ── BA Team Brief — sub-tab switcher ─────────────────────────────────────────
@callback(
    Output("ba-tab-role",                              "style"),
    Output("ba-tab-kpi",                               "style"),
    Output("ba-tab-ops",                               "style"),
    Output({"type": "ba-brief-tab", "tab": ALL},       "style"),
    Input({"type": "ba-brief-tab",  "tab": ALL},       "n_clicks"),
    State({"type": "ba-brief-tab",  "tab": ALL},       "id"),
    prevent_initial_call=True,
)
def _switch_ba_brief_tab(n_clicks, tab_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    tab  = triggered["tab"]
    show = {"display": "block"}
    hide = {"display": "none"}
    btn_styles = []
    for tid in (tab_ids or []):
        active = tid["tab"] == tab
        btn_styles.append({
            "background":   f"{A}22" if active else "transparent",
            "border":       "none",
            "borderBottom": f"2px solid {A}" if active else "2px solid transparent",
            "color":        TX if active else MT,
            "fontSize":     "13px", "fontWeight": "600" if active else "400",
            "padding":      "8px 16px", "cursor": "pointer", "marginRight": "4px",
        })
    return (
        show if tab == "role" else hide,
        show if tab == "kpi"  else hide,
        show if tab == "ops"  else hide,
        btn_styles,
    )


# ── Size filter (By Story tab) ────────────────────────────────────────────────
@callback(
    Output("plan-size-filter", "data"),
    Input({"type": "size-f", "v": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _size_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("v", "All")
    return "All"


@callback(
    Output({"type": "size-f", "v": ALL}, "style"),
    Input("plan-size-filter", "data"),
    State({"type": "size-f", "v": ALL}, "id"),
)
def _update_size_chips(active, chip_ids):
    styles = []
    for cid in (chip_ids or []):
        is_active = cid["v"] == active
        styles.append({
            "background":   (B + "33") if is_active else "transparent",
            "border":       f"1px solid {B}" if is_active else f"1px solid {BD}",
            "borderRadius": "12px",
            "color":        B if is_active else MT,
            "fontSize":     "11px",
            "fontWeight":   "700" if is_active else "400",
            "padding":      "3px 10px", "cursor": "pointer", "marginRight": "4px",
        })
    return styles


# ── Story matrix re-render on TYPE / SIZE filter or gate change ───────────────
@callback(
    Output("story-matrix-wrap", "children"),
    Input("plan-type-filter",  "data"),
    Input("plan-size-filter",  "data"),
    Input("gate-store",        "data"),
    State("plan-story-matrix", "data"),
    prevent_initial_call=True,
)
def _filter_story_matrix(type_f, size_f, gates, story_matrix):
    if not story_matrix:
        return []
    filtered = story_matrix
    if type_f and type_f != "All":
        want = "ENH" if type_f == "Enhancements" else "ISSUE"
        filtered = [sm for sm in filtered if sm.get("type") == want]
    if size_f and size_f != "All":
        filtered = [sm for sm in filtered if sm.get("size") == size_f]
    if gates:
        updated = []
        for sm in filtered:
            sid = str(sm.get("id", ""))
            g   = gates.get(sid, {f: False for f in _GATE_FIELDS})
            sk  = _story_status_key(g)
            new_sm = dict(sm)
            for mk in MATRIX_MONTHS:
                if new_sm.get(mk) is not None:
                    dev, _ = new_sm[mk]
                    new_sm[mk] = (dev, sk)
            updated.append(new_sm)
        filtered = updated
    return [_build_story_matrix(filtered)]


# ── Dev matrix live-update on gate change ─────────────────────────────────────
_SP = {
    "in_dev": 0, "in_qa": 1, "ready_to_ship": 2,
    "story_frozen": 3, "draft": 4, "not_started": 5, "shipped": 6,
}

@callback(
    Output("dev-matrix-wrap", "children"),
    Input("gate-store",         "data"),
    State("plan-dev-stories",   "data"),
    prevent_initial_call=True,
)
def _live_dev_matrix(gates, dev_stories):
    if not dev_stories:
        return no_update
    dev_matrix: dict = {}
    for ds in dev_stories:
        dname = ds["dev"]
        month = ds["month"]
        sid   = str(ds["id"])
        g     = (gates or {}).get(sid, {f: False for f in _GATE_FIELDS})
        sk    = _story_status_key(g)
        if dname not in dev_matrix:
            dev_matrix[dname] = {"role": ds["role"], "ns": 0,
                                  **{mk: None for mk in MATRIX_MONTHS}}
        if dev_matrix[dname][month] is None:
            dev_matrix[dname][month] = (1, sk)
        else:
            cnt, csk = dev_matrix[dname][month]
            worst = csk if _SP.get(csk, 9) >= _SP.get(sk, 9) else sk
            dev_matrix[dname][month] = (cnt + 1, worst)
        if not g.get("dor", False):
            dev_matrix[dname]["ns"] += 1
    today_month = date.today().month
    return [_build_dev_matrix(dev_matrix, today_month)]


# ── 9. Sign-off log modal ─────────────────────────────────────────────────────
_GATE_LABEL = {
    "dor":           "DoR Gate",
    "story_written": "Story Written",
    "estimation":    "Estimation",
    "in_dev":        "In Dev",
    "in_qa":         "In QA",
    "ready_to_ship": "Ready to Ship",
    "delivery":      "Delivery",
}


@callback(
    Output("signoff-modal", "is_open"),
    Output("log-body",      "children"),
    Output("log-footer",    "children"),
    Input("signoff-log-btn", "n_clicks"),
    Input("signoff-modal",   "is_open"),
    State("log-store", "data"),
    prevent_initial_call=True,
)
def _toggle_log(n_clicks, is_open, session_log):
    if ctx.triggered_id != "signoff-log-btn":
        return False, no_update, no_update

    # ── Pull full history from DB ─────────────────────────────────────────────
    try:
        from db.planning import get_log as _get_log
        db_entries = _get_log(limit=300)
    except Exception:
        db_entries = []

    if not db_entries:
        body = html.Div(
            "No sign-off actions recorded yet.",
            style={"color": MT, "fontSize": "13px", "padding": "16px"},
        )
    else:
        cards = []
        for entry in db_entries:   # already newest-first from DB
            is_conf  = entry.get("action") == "Confirmed"
            gate_lbl = _GATE_LABEL.get(entry.get("gate", ""), entry.get("gate", ""))
            pri      = entry.get("priority") or "—"
            # Format timestamp
            pat = entry.get("performed_at")
            if hasattr(pat, "strftime"):
                time_str = pat.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = str(pat)[:16] if pat else "—"

            cards.append(html.Div([
                html.Div([
                    html.Span(time_str,
                              style={"color": MT, "fontSize": "10px", "marginRight": "10px"}),
                    html.Span(gate_lbl,
                              style={"color": P, "fontSize": "11px", "fontWeight": "700",
                                     "marginRight": "8px"}),
                    html.Span(
                        ("✓ " if is_conf else "✗ ") + entry.get("action", ""),
                        style={"color": G if is_conf else R,
                               "fontSize": "11px", "fontWeight": "700"},
                    ),
                    html.Span(
                        f" · {entry.get('performed_by', '')}",
                        style={"color": MT, "fontSize": "10px", "marginLeft": "6px"},
                    ),
                ], style={"marginBottom": "4px"}),
                html.A(
                    entry.get("title") or f"Item #{entry.get('work_item_id')}",
                    href=f"{ADO_BASE_URL}{entry.get('work_item_id', '')}",
                    target="_blank",
                    style={"color": TX, "fontSize": "12px", "fontWeight": "600",
                           "marginBottom": "2px", "textDecoration": "none", "display": "block"},
                ),
                html.Div([
                    html.Span(f"BA: {entry.get('ba') or '—'}",
                              style={"color": MT, "fontSize": "10px", "marginRight": "12px"}),
                    html.Span(f"Dev: {entry.get('dev_name') or '—'}",
                              style={"color": MT, "fontSize": "10px", "marginRight": "12px"}),
                    html.Span(f"Month: {entry.get('month_key') or '—'}",
                              style={"color": MT, "fontSize": "10px", "marginRight": "12px"}),
                    html.Span(f"Pri: {pri}",
                              style={"color": _pri_clr(pri), "fontSize": "10px"}),
                ], style={"marginBottom": "4px"}),
                html.Div([
                    html.Span("→ ", style={"color": MT, "fontSize": "10px"}),
                    html.Span(
                        entry.get("new_status", ""),
                        style={"color": G if is_conf else R,
                               "fontSize": "10px", "fontWeight": "700"},
                    ),
                ]),
            ], style={
                "background": C2, "border": f"1px solid {BD}",
                "borderRadius": "8px", "padding": "12px 14px", "marginBottom": "8px",
            }))
        body = html.Div(cards)

    # Footer: totals from DB
    confirmed = sum(1 for e in db_entries if e.get("action") == "Confirmed")
    cleared   = sum(1 for e in db_entries if e.get("action") == "Cleared")
    total     = len(db_entries)
    footer = html.Div([
        html.Span(f"✓ Confirmed: {confirmed}",
                  style={"color": G, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"✗ Cleared: {cleared}",
                  style={"color": R, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"Total log entries: {total}",
                  style={"color": MT, "fontSize": "12px"}),
    ])
    return True, body, footer


# ── 9. Matrix cell click → slide-out panel ────────────────────────────────────
@callback(
    Output("matrix-panel",      "style"),
    Output("matrix-panel-hdr",  "children"),
    Output("matrix-panel-body", "children"),
    Input({"type": "matrix-cell", "dev": ALL, "month": ALL}, "n_clicks"),
    Input("matrix-panel-close", "n_clicks"),
    State("plan-stories-store", "data"),
    prevent_initial_call=True,
)
def _matrix_panel(cell_clicks, close_click, stories_data):
    triggered = ctx.triggered_id
    if triggered == "matrix-panel-close" or not triggered:
        return _CAP_PANEL_CLOSED, no_update, no_update
    # New matrix-cell components rendered by live-update have n_clicks=0 — ignore
    if not any(n and n > 0 for n in (cell_clicks or [])):
        return no_update, no_update, no_update

    dev   = triggered.get("dev", "")
    month = triggered.get("month", "")

    # ── Month label ───────────────────────────────────────────────────────────
    today_m   = date.today().month
    m_offset  = {"M0": 0, "M1": 1, "M2": 2}.get(month, 0)
    cal_month = _CAL.get(min(today_m + m_offset, 12), month)
    month_lbl = f"{month} · {cal_month} 2026"

    # ── Filter stories for this dev × month ──────────────────────────────────
    _pri_ord = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    _sort    = lambda lst: sorted(lst, key=lambda s: (_pri_ord.get(s["pri"], 9), s["id"]))

    dev_stories = _sort([
        s for s in (stories_data or [])
        if s["dev"].split()[0] == dev.split()[0] and s["month"] == month
    ])

    # ── Group by readiness status ─────────────────────────────────────────────
    groups = {
        "not_started": [], "draft": [], "story_frozen": [],
        "in_dev": [], "in_qa": [], "ready_to_ship": [], "shipped": [],
    }
    for s in dev_stories:
        sk = _story_status_key(s)
        groups.setdefault(sk, []).append(s)

    _STATUS_META = {
        "not_started":  ("Not Started",   R,         "■"),
        "draft":        ("Draft",         A,         "■"),
        "story_frozen": ("Story Frozen",  "#c084fc", "■"),
        "in_dev":       ("In Dev",        B,         "■"),
        "in_qa":        ("In QA",         "#fb923c", "■"),
        "ready_to_ship":("Ready to Ship", G,         "■"),
        "shipped":      ("Shipped",       "#10b981", "■"),
    }

    # ── KPI count boxes ───────────────────────────────────────────────────────
    def _kpi_box(count, label, color):
        return html.Div([
            html.Div(str(count), style={
                "fontSize": "36px", "fontWeight": "800", "color": color,
                "lineHeight": "1", "textAlign": "center", "letterSpacing": "-1px",
            }),
            html.Div(label, style={
                "fontSize": "10px", "fontWeight": "700", "color": MT,
                "textTransform": "uppercase", "letterSpacing": "0.8px",
                "marginTop": "8px", "textAlign": "center",
            }),
        ], style={
            "flex": "1", "minWidth": "0",
            "display": "flex", "flexDirection": "column",
            "alignItems": "center", "justifyContent": "center",
            "padding": "20px 6px", "background": f"{color}12",
            "borderRadius": "12px", "border": f"1px solid {color}55",
            "borderBottom": f"3px solid {color}", "margin": "0 4px",
        })

    kpi_order = (
        ["in_dev", "in_qa", "ready_to_ship", "story_frozen", "draft", "not_started"]
        if month == "M0"
        else ["story_frozen", "not_started", "draft", "in_dev", "in_qa", "ready_to_ship"]
    )
    kpi_boxes = [
        _kpi_box(len(groups[k]), _STATUS_META[k][0], _STATUS_META[k][1])
        for k in kpi_order if groups[k]
    ]
    if not kpi_boxes:
        kpi_boxes = [_kpi_box(0, "No Items", MT)]

    # ── Section header ────────────────────────────────────────────────────────
    def _sec_hdr(label, count, color):
        return html.Div([
            html.Span(label, style={
                "fontSize": "10px", "fontWeight": "800", "color": color,
                "textTransform": "uppercase", "letterSpacing": "1.2px",
            }),
            html.Span(f"{count} item{'s' if count != 1 else ''}", style={
                "fontSize": "10px", "color": MT,
            }),
        ], style={
            "display": "flex", "justifyContent": "space-between", "alignItems": "center",
            "borderBottom": f"1px solid {BD}",
            "paddingBottom": "8px", "marginBottom": "12px", "marginTop": "20px",
        })

    # ── Story card with gate checkmarks ───────────────────────────────────────
    def _story_card(s):
        hrs_lbl = f"{s['hrs']:.0f}h" if s.get("hrs") else "—"
        hrs_clr = MT if not s.get("hrs") else TX

        def _gate(ok, label):
            clr = G if ok else R
            sym = "✓" if ok else "✗"
            return html.Span([
                html.Span(f"{sym} ", style={"color": clr, "fontWeight": "700"}),
                html.Span(label,     style={"color": MT}),
            ], style={"fontSize": "10px", "marginRight": "14px"})

        return html.Div([
            html.A(s["title"],
                   href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                   style={"color": TX, "fontSize": "13px", "fontWeight": "600",
                          "textDecoration": "none", "display": "block",
                          "lineHeight": "1.45", "marginBottom": "10px"}),
            html.Div([
                _tag(s["pri"], _pri_clr(s["pri"])),
                html.Span(s.get("size") or s["type"], style={
                    "fontSize": "10px", "fontWeight": "600", "color": A,
                    "background": f"{A}18", "border": f"1px solid {A}44",
                    "borderRadius": "4px", "padding": "1px 7px", "marginLeft": "6px",
                }),
                html.Span(hrs_lbl, style={
                    "fontSize": "11px", "fontWeight": "700", "color": hrs_clr,
                    "marginLeft": "8px",
                }),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
            html.Div([
                _gate(s.get("dor",           False), "DoR Gate"),
                _gate(s.get("story_written", False), "Story Written"),
                _gate(s.get("estimation",    False), "Estimation"),
                _gate(s.get("in_dev",        False), "In Dev"),
            ], style={"display": "flex", "flexWrap": "wrap"}),
        ], style={
            "background": C3, "borderRadius": "10px",
            "padding": "14px 16px", "marginBottom": "8px",
        })

    # ── Header ────────────────────────────────────────────────────────────────
    total = len(dev_stories)
    hdr_children = [
        html.Span("STORY READINESS DETAIL", style={
            "fontSize": "9px", "color": MT, "textTransform": "uppercase",
            "letterSpacing": "1.5px", "display": "block", "marginBottom": "4px",
        }),
        html.Span(dev, style={"color": TX}),
        html.Span(f"  ·  {month_lbl}  ·  {total} items",
                  style={"color": MT, "fontWeight": "400", "fontSize": "13px"}),
    ]

    # ── KPI row + count line ──────────────────────────────────────────────────
    kpi_section = html.Div([
        html.Div(kpi_boxes, style={"display": "flex", "margin": "20px -4px 16px"}),
        html.Div([
            html.Span(str(total), style={"fontSize": "20px", "fontWeight": "800", "color": TX,
                                         "marginRight": "5px"}),
            html.Span("ITEMS", style={"fontSize": "10px", "fontWeight": "700", "color": MT,
                                      "letterSpacing": "1px", "textTransform": "uppercase"}),
        ], style={"display": "flex", "alignItems": "baseline",
                  "borderTop": f"1px solid {BD}", "paddingTop": "14px"}),
    ], style={"padding": "0 20px 16px", "borderBottom": f"1px solid {BD}"})

    # ── Story sections ordered by urgency ─────────────────────────────────────
    section_order = (
        ["in_dev", "in_qa", "ready_to_ship", "story_frozen", "draft", "not_started", "shipped"]
        if month == "M0"
        else ["not_started", "draft", "story_frozen", "in_dev", "in_qa", "ready_to_ship", "shipped"]
    )
    if not dev_stories:
        cards_block = html.Div(
            "No stories planned for this developer in this month.",
            style={"color": MT, "fontSize": "13px", "padding": "20px"},
        )
    else:
        parts = []
        for key in section_order:
            grp = groups[key]
            if not grp:
                continue
            label, color, _ = _STATUS_META[key]
            parts.append(_sec_hdr(f"{label}  ·  {len(grp)} items", len(grp), color))
            parts.extend(_story_card(s) for s in grp)
        cards_block = html.Div(parts, style={"padding": "16px 20px 48px"})

    panel_body = html.Div([kpi_section, cards_block])
    return _CAP_PANEL_OPEN, hdr_children, panel_body


# ─── Unestimated KPI cards → inline table ─────────────────────────────────────
@callback(
    Output("unest-item-panel", "children"),
    Output({"type": "unest-kcard", "filter": ALL}, "style"),
    Output("unest-active-kcard", "data"),
    Input({"type": "unest-kcard", "filter": ALL}, "n_clicks"),
    State("plan-unest-store", "data"),
    State({"type": "unest-kcard", "filter": ALL}, "id"),
    State("unest-active-kcard", "data"),
    prevent_initial_call=True,
)
def _unest_card_click(clicks, items, card_ids, currently_active):
    if not ctx.triggered_id or not items:
        return no_update, no_update, no_update
    items = [s for s in items if s["est_status"] in ("unestimated", "partial")]

    active_f = ctx.triggered_id["filter"]

    # Toggle: clicking the already-active card collapses the table
    if active_f == currently_active:
        blank_styles = [_kcard_style(_UNEST_CARD_COLORS[cid["filter"]], False) for cid in card_ids]
        return html.Div(), blank_styles, None
    _UNA = ("Unassigned", "Not Specified", "")

    if active_f == "all":
        filtered, label = items, "All Unestimated Items"
    elif active_f == "p1":
        filtered, label = [s for s in items if s["pri"] == "P1"], "P1 Items"
    elif active_f == "issues":
        filtered, label = [s for s in items if s["type"] == "Issue"], "Issues"
    elif active_f == "enhanc":
        filtered, label = [s for s in items if s["type"] == "Enhancement"], "Enhancements"
    elif active_f == "devsp1":
        gap_devs = {s["dev"] for s in items if s["pri"] == "P1" and s["dev"] not in _UNA}
        filtered = [s for s in items if s["pri"] == "P1" and s["dev"] in gap_devs]
        label    = "Devs with P1 Gap"
    else:
        filtered, label = items, "Items"

    filtered = sorted(filtered, key=lambda s: (s["pri"], s["dev"], s["title"]))
    count    = len(filtered)
    color    = _UNEST_CARD_COLORS.get(active_f, R)

    td_s = {"fontSize": "12px", "color": TX, "padding": "10px 14px",
            "borderBottom": f"1px solid {BD}", "verticalAlign": "middle"}
    th_s = {"fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
            "letterSpacing": "0.5px", "color": MT, "padding": "10px 14px",
            "borderBottom": f"1px solid {BD}", "textAlign": "left"}

    rows = []
    for s in filtered:
        est_lbl, est_c = ("Partial", A) if s["est_status"] == "partial" else ("Missing", R)
        task_note = f"  {s['task_count']}t, {s['task_missing']} missing" \
                    if s.get("task_count", 0) > 0 else ""
        rows.append(html.Tr([
            html.Td(html.A(f"#{s['id']}", href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                           style={"color": P, "fontWeight": "700", "textDecoration": "none",
                                  "fontSize": "12px"}),
                    style={**td_s, "width": "72px"}),
            html.Td(html.A(s["title"], href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                           style={"color": TX, "textDecoration": "none", "fontSize": "12px",
                                  "fontWeight": "500", "lineHeight": "1.4"}),
                    style=td_s),
            html.Td(s["dev"] or "—", style={**td_s, "color": MT, "fontSize": "11px",
                                             "whiteSpace": "nowrap"}),
            html.Td(html.Span(s["pri"], style={
                        "background": f"{_pri_clr(s['pri'])}22", "color": _pri_clr(s["pri"]),
                        "border": f"1px solid {_pri_clr(s['pri'])}55",
                        "borderRadius": "4px", "padding": "2px 8px",
                        "fontSize": "11px", "fontWeight": "700",
                    }), style={**td_s, "textAlign": "center", "width": "54px"}),
            html.Td(s.get("month") or "—",
                    style={**td_s, "color": MT, "textAlign": "center",
                           "width": "54px", "fontSize": "11px"}),
            html.Td([
                html.Span(est_lbl, style={
                    "background": f"{est_c}22", "color": est_c,
                    "border": f"1px solid {est_c}55", "borderRadius": "4px",
                    "padding": "2px 8px", "fontSize": "11px", "fontWeight": "600",
                }),
                html.Span(task_note, style={"color": MT, "fontSize": "10px",
                                             "marginLeft": "6px"}),
            ], style={**td_s, "whiteSpace": "nowrap"}),
        ], style={"background": CD}))

    panel = html.Div([
        html.Div([
            html.Span(label, style={"fontWeight": "700", "color": color, "fontSize": "14px"}),
            html.Span(f"  ·  {count} items",
                      style={"color": MT, "fontSize": "12px"}),
            html.Span("  ↗ opens in ADO",
                      style={"color": MT, "fontSize": "10px", "marginLeft": "8px"}),
        ], style={"marginBottom": "10px"}),
        html.Div(
            html.Table([
                html.Thead(html.Tr([
                    html.Th("ID",          style={**th_s, "width": "72px"}),
                    html.Th("Title",       style=th_s),
                    html.Th("Developer",   style={**th_s, "width": "150px"}),
                    html.Th("Pri",         style={**th_s, "width": "54px", "textAlign": "center"}),
                    html.Th("Month",       style={**th_s, "width": "54px", "textAlign": "center"}),
                    html.Th("Est. Status", style=th_s),
                ])),
                html.Tbody(rows),
            ], style={"width": "100%", "borderCollapse": "collapse"}),
            style={"background": CD, "borderRadius": "12px",
                   "border": f"1px solid {color}44",
                   "overflow": "auto", "maxHeight": "400px"},
        ),
    ], style={"marginBottom": "20px"})

    card_styles = [
        _kcard_style(_UNEST_CARD_COLORS[cid["filter"]], cid["filter"] == active_f)
        for cid in card_ids
    ]
    return panel, card_styles, active_f


# ─── Unestimated matrix cell → side panel ──────────────────────────────────────

# Toggle: matrix cell click / close / backdrop → store {dev, month} or None
@callback(
    Output("unest-panel-filter", "data"),
    Input({"type": "unest-matrix-cell", "dev": ALL, "month": ALL, "est_type": ALL}, "n_clicks"),
    Input("unest-panel-close", "n_clicks"),
    Input("unest-backdrop",    "n_clicks"),
    prevent_initial_call=True,
)
def _unest_matrix_toggle(cell_clicks, close_click, backdrop_click):
    tid = ctx.triggered_id
    if tid in ("unest-panel-close", "unest-backdrop"):
        return None
    if isinstance(tid, dict) and tid.get("type") == "unest-matrix-cell":
        return {"dev": tid["dev"], "month": tid["month"], "est_type": tid.get("est_type", "u")}
    return no_update


# Render: store → slide panel open/closed with item cards
@callback(
    Output("unest-side-panel",  "style"),
    Output("unest-backdrop",    "style"),
    Output("unest-panel-title", "children"),
    Output("unest-panel-body",  "children"),
    Input("unest-panel-filter", "data"),
    State("plan-unest-store",   "data"),
)
def _unest_matrix_panel(cell_sel, items):
    if not cell_sel or not items:
        return _PANEL_CLOSED, _BACKDROP_CLOSED, "", []

    dev      = cell_sel["dev"]
    month    = cell_sel["month"]
    est_type = cell_sel.get("est_type", "u")  # "e" = estimated, "u" = unestimated

    if est_type == "e":
        filtered = sorted(
            [s for s in items if s["dev"] == dev and s["month"] == month
             and s["est_status"] in ("estimated", "estimated_via_tasks")],
            key=lambda s: (s["pri"], s["title"]),
        )
    else:
        filtered = sorted(
            [s for s in items if s["dev"] == dev and s["month"] == month
             and s["est_status"] in ("unestimated", "partial")],
            key=lambda s: (s["pri"], s["title"]),
        )

    def _item_card(s):
        if s["est_status"] in ("estimated", "estimated_via_tasks"):
            est_lbl, est_c = "Estimated", G
        elif s["est_status"] == "partial":
            est_lbl, est_c = "Partial", A
        else:
            est_lbl, est_c = "Missing", R
        task_note = ""
        if s.get("task_count", 0) > 0:
            miss = s["task_missing"]
            task_note = f"{s['task_count']} tasks" + (f", {miss} missing" if miss else "")

        return html.A(
            href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
            style={"textDecoration": "none", "display": "block", "marginBottom": "8px"},
            children=html.Div([
                html.Div([
                    html.Span(f"#{s['id']}",
                              style={"color": P, "fontWeight": "700",
                                     "fontSize": "11px", "marginRight": "8px"}),
                    html.Span(s["pri"], style={
                        "background": f"{_pri_clr(s['pri'])}22",
                        "color": _pri_clr(s["pri"]),
                        "border": f"1px solid {_pri_clr(s['pri'])}44",
                        "borderRadius": "4px", "padding": "1px 6px",
                        "fontSize": "10px", "fontWeight": "700", "marginRight": "6px",
                    }),
                    html.Span(est_lbl, style={
                        "background": f"{est_c}18", "color": est_c,
                        "border": f"1px solid {est_c}44",
                        "borderRadius": "4px", "padding": "1px 6px",
                        "fontSize": "10px", "fontWeight": "600",
                    }),
                ], style={"marginBottom": "6px", "display": "flex",
                           "alignItems": "center", "flexWrap": "wrap", "gap": "4px"}),
                html.Div(s["title"], style={
                    "color": TX, "fontSize": "13px", "fontWeight": "600",
                    "lineHeight": "1.4", "marginBottom": "5px",
                }),
                html.Div([
                    html.Span(task_note, style={"color": MT, "fontSize": "10px"}),
                ]),
            ], style={
                "background": CD,
                "border": f"1px solid {BD}",
                "borderLeft": f"3px solid {_pri_clr(s['pri'])}",
                "borderRadius": "8px", "padding": "12px 14px",
                "transition": "opacity .15s",
            })
        )

    _est_label = "Estimated" if est_type == "e" else "Unestimated"
    title_el = [
        html.Span(dev.split()[0], style={"color": TX}),
        html.Span(f"  ·  {month}", style={"color": P, "fontWeight": "700"}),
        html.Span(f"  ·  {_est_label}",
                  style={"color": G if est_type == "e" else R,
                         "fontSize": "11px", "fontWeight": "700", "marginLeft": "4px"}),
        html.Span(f"  ·  {len(filtered)} item{'s' if len(filtered) != 1 else ''}",
                  style={"color": MT, "fontSize": "13px", "fontWeight": "400"}),
    ]

    def _section_header(label: str, count: int) -> html.Div:
        return html.Div([
            html.Span(label, style={"fontSize": "10px", "fontWeight": "700",
                                    "color": MT, "textTransform": "uppercase",
                                    "letterSpacing": "0.8px"}),
            html.Span(f"  {count}", style={"fontSize": "10px", "color": MT,
                                           "fontWeight": "400"}),
        ], style={
            "borderBottom": f"1px solid {BD}",
            "paddingBottom": "5px", "marginBottom": "8px", "marginTop": "14px",
        })

    enhancements = [s for s in filtered if s["type"] == "Enhancement"]
    issues       = [s for s in filtered if s["type"] == "Issue"]

    body_items = [
        html.Div("↗ Click any item to open in ADO",
                 style={"color": MT, "fontSize": "10px",
                        "marginBottom": "8px", "textAlign": "right"}),
    ]
    for label, group in [("Enhancements", enhancements), ("Issues", issues)]:
        if not group:
            continue
        body_items.append(_section_header(label, len(group)))
        body_items.extend(_item_card(s) for s in group)

    _empty_msg = f"No {_est_label.lower()} items for this cell."
    body = html.Div(body_items) if filtered else html.Div(
        _empty_msg,
        style={"color": MT, "fontSize": "13px", "padding": "20px 0"},
    )

    return _PANEL_OPEN, _BACKDROP_OPEN, title_el, body


# ── 11. Per-ticket sign-off log ───────────────────────────────────────────────
@callback(
    Output("ticket-log-sid", "data"),
    Input({"type": "ticket-log-btn", "sid": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _ticket_log_select(n_clicks):
    # Guard: skip if no button has actually been clicked yet (all n_clicks == 0)
    if not any(n_clicks):
        return no_update
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "ticket-log-btn":
        return triggered["sid"]
    return no_update


@callback(
    Output("tlog-modal",   "is_open"),
    Output("tlog-header",  "children"),
    Output("tlog-body",    "children"),
    Output("tlog-footer",  "children"),
    Input("ticket-log-sid",     "data"),
    State("plan-stories-store", "data"),
    prevent_initial_call=True,
)
def _ticket_log_render(sid, stories_data):
    if not sid:
        return False, "", [], ""

    story    = next((s for s in (stories_data or []) if s["id"] == sid), None)
    title    = story["title"] if story else f"Item #{sid}"
    ba_txt   = story.get("ba", "") if story else ""
    dev_txt  = story.get("dev", "") if story else ""
    mon_txt  = story.get("month", "") if story else ""

    header_el = html.Div([
        html.Span("🕐 Sign-Off History  ", style={"color": MT, "fontSize": "12px"}),
        html.A(title, href=f"{ADO_BASE_URL}{sid}", target="_blank",
               style={"color": TX, "fontWeight": "700", "fontSize": "14px",
                      "textDecoration": "none"}),
        html.Div(
            f"BA: {ba_txt}  ·  Dev: {dev_txt}  ·  {mon_txt}",
            style={"color": MT, "fontSize": "11px", "marginTop": "4px"},
        ) if (ba_txt or dev_txt) else None,
    ])

    try:
        from db.planning import get_log as _get_log
        entries = _get_log(work_item_id=int(sid), limit=100)
    except Exception:
        entries = []

    if not entries:
        body = html.Div(
            "No sign-off actions recorded for this story yet.",
            style={"color": MT, "fontSize": "13px", "padding": "20px"},
        )
    else:
        cards = []
        for entry in entries:   # newest-first from DB
            is_conf  = entry.get("action") == "Confirmed"
            gate_lbl = _GATE_LABEL.get(entry.get("gate", ""), entry.get("gate", ""))
            pat      = entry.get("performed_at")
            if hasattr(pat, "strftime"):
                time_str = pat.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_str = str(pat)[:19] if pat else "—"

            cards.append(html.Div([
                html.Div([
                    html.Span(time_str,
                              style={"color": MT, "fontSize": "11px",
                                     "fontFamily": "monospace", "marginRight": "14px",
                                     "flexShrink": "0"}),
                    html.Span(gate_lbl,
                              style={"color": B, "fontSize": "12px",
                                     "fontWeight": "700", "marginRight": "10px"}),
                    html.Span(("✓ " if is_conf else "✗ ") + entry.get("action", ""),
                              style={"color": G if is_conf else R,
                                     "fontSize": "12px", "fontWeight": "700",
                                     "marginRight": "10px"}),
                    html.Span(
                        entry.get("performed_by", ""),
                        style={"color": MT, "fontSize": "11px"},
                    ),
                ], style={"display": "flex", "alignItems": "center",
                           "flexWrap": "wrap", "marginBottom": "4px"}),
                html.Div(
                    entry.get("new_status", ""),
                    style={"color": G if is_conf else R,
                           "fontSize": "11px", "fontWeight": "600"},
                ),
            ], style={
                "background":   f"{G}08" if is_conf else f"{R}08",
                "border":       f"1px solid {G}22" if is_conf else f"1px solid {R}22",
                "borderLeft":   f"3px solid {G}" if is_conf else f"3px solid {R}",
                "borderRadius": "8px", "padding": "10px 14px", "marginBottom": "8px",
            }))
        body = html.Div(cards)

    confirmed = sum(1 for e in entries if e.get("action") == "Confirmed")
    cleared   = sum(1 for e in entries if e.get("action") == "Cleared")
    footer    = html.Div([
        html.Span(f"✓ {confirmed} confirmed",
                  style={"color": G, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"✗ {cleared} cleared",
                  style={"color": R, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"{len(entries)} total actions",
                  style={"color": MT, "fontSize": "12px"}),
    ]) if entries else ""

    return True, header_el, body, footer


# ═══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE TRACKER HELPERS + CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

def _derive_planning_gates(state: dict) -> dict:
    """
    Derive all 7 planning gate fields from lifecycle tracker step state.

    Gate groupings:
      dor           = g1 (DoR) + g2 (Design Freeze) both fully complete
      story_written = p4 (Playback / Understanding Validation) fully complete
      estimation    = p5 (Estimation Phase) fully complete
      in_dev        = any step in g4 (Dev Complete Gate) checked
      in_qa         = any step in g5 (QA Gate) checked
      ready_to_ship = g5 fully complete
      delivery      = g6 (Ship Gate) fully complete
    """
    def _gate_complete(gate_key: str) -> bool:
        gate = next((g for g in LIFECYCLE if g["key"] == gate_key), None)
        if not gate:
            return False
        return all(state.get(s["key"], False)
                   for p in gate["phases"] for s in p["steps"])

    def _phase_complete(phase_key: str) -> bool:
        for g in LIFECYCLE:
            for p in g["phases"]:
                if p["key"] == phase_key:
                    return all(state.get(s["key"], False) for s in p["steps"])
        return False

    def _gate_has_progress(gate_key: str) -> bool:
        gate = next((g for g in LIFECYCLE if g["key"] == gate_key), None)
        if not gate:
            return False
        return any(state.get(s["key"], False)
                   for p in gate["phases"] for s in p["steps"])

    return {
        "dor":           _gate_complete("g1") and _gate_complete("g2"),
        "story_written": _phase_complete("p4"),
        "estimation":    _phase_complete("p5"),
        "in_dev":        _gate_has_progress("g4"),
        "in_qa":         _gate_has_progress("g5"),
        "ready_to_ship": _gate_complete("g5"),
        "delivery":      _gate_complete("g6"),
    }

def _tracker_gate_progress(gate: dict, state: dict) -> tuple[int, int]:
    """(done_steps, total_steps) for a gate."""
    total = sum(len(p["steps"]) for p in gate["phases"])
    done  = sum(1 for p in gate["phases"] for s in p["steps"] if state.get(s["key"], False))
    return done, total


def _tracker_phase_progress(phase: dict, state: dict) -> tuple[int, int]:
    """(done_steps, total_steps) for a phase."""
    total = len(phase["steps"])
    done  = sum(1 for s in phase["steps"] if state.get(s["key"], False))
    return done, total


def _build_tracker_summary(state: dict) -> html.Div:
    """Compact 6-gate progress dots row for modal header."""
    dots = []
    for gate in LIFECYCLE:
        done, total = _tracker_gate_progress(gate, state)
        gate_done   = done == total and total > 0
        pct         = round(done / total * 100) if total else 0
        clr         = gate["color"]
        dots.append(html.Div([
            html.Div(style={
                "width": "10px", "height": "10px", "borderRadius": "50%",
                "background": clr if gate_done else "transparent",
                "border": f"2px solid {clr}",
                "flexShrink": "0",
            }),
            html.Div(gate["label"],
                     style={"fontSize": "9px", "color": clr if gate_done else MT,
                             "fontWeight": "700" if gate_done else "400",
                             "marginLeft": "4px", "whiteSpace": "nowrap"}),
            html.Div(f"{pct}%",
                     style={"fontSize": "9px", "color": MT, "marginLeft": "4px"}),
        ], style={"display": "flex", "alignItems": "center", "marginRight": "16px"}))

    total_done = sum(1 for v in state.values() if v)
    return html.Div([
        html.Div(dots, style={"display": "flex", "flexWrap": "wrap", "marginBottom": "6px"}),
        html.Div(f"{total_done} / {TOTAL_STEPS} steps complete",
                 style={"fontSize": "11px", "color": MT}),
    ])


def _build_tracker_body(state: dict, gate_filter: dict | None = None) -> list:
    """
    Render lifecycle gates with phases and step checkboxes.
    gate_filter: {"gates": [gate_keys], "phases": [phase_keys] or None}
                 None = show all gates and phases.
    """
    gate_keys  = gate_filter["gates"]  if gate_filter else None
    phase_keys = gate_filter["phases"] if gate_filter else None

    gates_html = []
    for gate in LIFECYCLE:
        if gate_keys and gate["key"] not in gate_keys:
            continue
        g_done, g_total   = _tracker_gate_progress(gate, state)
        gate_complete      = g_done == g_total and g_total > 0
        clr                = gate["color"]
        gate_pct           = round(g_done / g_total * 100) if g_total else 0

        # Phase sections
        phases_html = []
        for phase in gate["phases"]:
            if phase_keys and phase["key"] not in phase_keys:
                continue
            p_done, p_total = _tracker_phase_progress(phase, state)
            phase_complete  = p_done == p_total and p_total > 0
            p_clr           = clr if phase_complete else MT

            step_btns = []
            for step in phase["steps"]:
                checked = state.get(step["key"], False)
                step_btns.append(html.Button([
                    html.Span("✓  " if checked else "○  ",
                              style={"color": clr if checked else "rgba(255,255,255,0.25)",
                                     "fontWeight": "700", "fontSize": "13px",
                                     "flexShrink": "0"}),
                    html.Span(step["label"],
                              style={"fontSize": "12px",
                                     "color": TX if checked else MT,
                                     "textDecoration": "line-through" if False else "none",
                                     "lineHeight": "1.4"}),
                ], id={"type": "tracker-step-btn", "step": step["key"]}, n_clicks=0,
                style={
                    "background":   f"{clr}12" if checked else "transparent",
                    "border":       f"1px solid {clr}44" if checked else f"1px solid {BD}",
                    "borderLeft":   f"3px solid {clr}" if checked else f"3px solid transparent",
                    "borderRadius": "6px", "padding": "6px 12px",
                    "cursor": "pointer", "display": "flex", "alignItems": "flex-start",
                    "width": "100%", "textAlign": "left", "marginBottom": "4px",
                    "transition": "all .12s",
                }))

            phases_html.append(html.Div([
                html.Div([
                    html.Span("✓ " if phase_complete else f"{p_done}/{p_total}  ",
                              style={"color": p_clr, "fontSize": "11px",
                                     "fontWeight": "700", "marginRight": "6px"}),
                    html.Span(phase["label"],
                              style={"color": TX if phase_complete else TX,
                                     "fontSize": "12px", "fontWeight": "600"}),
                ], style={"display": "flex", "alignItems": "center",
                           "marginBottom": "8px", "paddingBottom": "6px",
                           "borderBottom": f"1px solid {BD}"}),
                html.Div(step_btns, style={"display": "flex", "flexDirection": "column",
                                            "gap": "2px"}),
            ], style={
                "background": CD, "borderRadius": "8px", "padding": "12px 14px",
                "marginBottom": "8px",
                "border": f"1px solid {clr}44" if phase_complete else f"1px solid {BD}",
            }))

        # Progress bar
        bar_filled = html.Div(style={
            "width": f"{gate_pct}%", "height": "4px",
            "background": clr, "borderRadius": "2px",
            "transition": "width 0.3s ease",
        })
        bar = html.Div(
            html.Div(bar_filled, style={"width": "100%", "height": "4px",
                                        "background": "rgba(255,255,255,0.08)",
                                        "borderRadius": "2px"}),
            style={"flex": "1", "margin": "0 12px"},
        )

        gate_css = "tracker-gate-card"
        if gate_complete:
            gate_css += " gate-complete"

        gates_html.append(html.Div([
            # Gate header
            html.Div([
                html.Div(style={
                    "width": "12px", "height": "12px", "borderRadius": "50%",
                    "background": clr if gate_complete else "transparent",
                    "border": f"2px solid {clr}", "flexShrink": "0",
                }),
                html.Div([
                    html.Span(gate["label"],
                              style={"color": clr, "fontSize": "13px", "fontWeight": "800",
                                     "marginRight": "8px"}),
                    html.Span(gate["desc"],
                              style={"color": MT, "fontSize": "11px"}),
                ], style={"flex": "1", "marginLeft": "10px"}),
                bar,
                html.Div(f"{g_done}/{g_total}",
                         style={"color": clr if gate_complete else MT,
                                "fontSize": "12px", "fontWeight": "700",
                                "flexShrink": "0"}),
            ], style={"display": "flex", "alignItems": "center",
                       "marginBottom": "12px"}),
            # Phases
            *phases_html,
        ], className=gate_css, style={
            "background": C2, "borderRadius": "12px", "padding": "16px 18px",
            "marginBottom": "12px",
            "border": (f"1px solid {gate['color']}55" if gate_complete
                       else f"1px solid {BD}"),
            "boxShadow": f"0 0 28px {gate['color']}18" if gate_complete else "none",
        }))

    return gates_html


# ── 12. Lifecycle tracker — select ────────────────────────────────────────────
# Handles both the 📋 icon button (tracker-btn) and gate pill clicks (gate-open-btn)
@callback(
    Output("tracker-sid",        "data"),
    Output("tracker-gate-focus", "data"),
    Input({"type": "tracker-btn",      "sid": ALL},            "n_clicks"),
    Input({"type": "gate-open-btn",    "sid": ALL, "gate": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _tracker_select(tracker_clicks, gate_clicks):
    # Guard: skip if no button has actually been clicked yet (all n_clicks == 0)
    all_clicks = list(tracker_clicks or []) + list(gate_clicks or [])
    if not any(all_clicks):
        return no_update, no_update
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict):
        return no_update, no_update
    t = triggered.get("type")
    if t == "tracker-btn":
        return triggered["sid"], None
    if t == "gate-open-btn":
        gate_filter = _GATE_FILTER_MAP.get(triggered["gate"])
        return triggered["sid"], gate_filter
    return no_update, no_update


# ── 13. Lifecycle tracker — open / step toggle ────────────────────────────────
@callback(
    Output("tracker-modal",   "is_open"),
    Output("tracker-header",  "children"),
    Output("tracker-data",    "data"),
    Output("gate-store",      "data"),
    Input("tracker-sid",      "data"),
    Input({"type": "tracker-step-btn", "step": ALL}, "n_clicks"),
    State("tracker-data",       "data"),
    State("plan-stories-store", "data"),
    State("gate-store",         "data"),
    prevent_initial_call=True,
)
def _tracker_main(sid, step_clicks, cur_data, stories_data, gate_store):
    triggered = ctx.triggered_id

    def _header(sid_, title_, state_, story_):
        done = sum(1 for v in state_.values() if v)
        gates_done = sum(
            1 for g in LIFECYCLE
            if all(state_.get(s["key"], False)
                   for p in g["phases"] for s in p["steps"])
        )
        pri = story_.get("pri", "") if story_ else ""
        return html.Div([
            html.Div([
                html.A(title_, href=f"{ADO_BASE_URL}{sid_}", target="_blank",
                       style={"color": TX, "fontWeight": "800", "fontSize": "16px",
                              "textDecoration": "none", "marginRight": "12px"}),
                html.Span(f"  {pri}",
                          style={"color": _pri_clr(pri), "fontSize": "11px",
                                 "fontWeight": "700"}) if pri else None,
                html.Span(
                    f"  {gates_done}/6 gates  ·  {done}/{TOTAL_STEPS} steps",
                    style={"color": MT, "fontSize": "12px", "marginLeft": "8px"},
                ),
            ], style={"display": "flex", "alignItems": "center",
                       "marginBottom": "10px"}),
            _build_tracker_summary(state_),
        ])

    # ── Modal open triggered by a new sid ────────────────────────────────────
    if triggered == "tracker-sid":
        if not sid:
            return False, "", {}, no_update
        try:
            from db.planning import load_tracker_state as _lts
            state = _lts(int(sid))
        except Exception:
            state = {}
        story = next((s for s in (stories_data or []) if s["id"] == sid), None)
        title = story["title"] if story else f"Item #{sid}"
        return True, _header(sid, title, state, story), {"sid": sid, "state": state}, no_update

    # ── Step button click ─────────────────────────────────────────────────────
    if isinstance(triggered, dict) and triggered.get("type") == "tracker-step-btn":
        data  = dict(cur_data or {})
        state = dict(data.get("state", {}))
        sk    = triggered["step"]
        new_v = not state.get(sk, False)
        state[sk] = new_v

        gate_key, phase_key = STEP_INDEX.get(sk, ("", ""))
        step_lbl            = STEP_LABELS.get(sk, sk)

        try:
            from flask_login import current_user as _cu
            performed_by = _cu.display_name if _cu and _cu.is_authenticated else "system"
        except Exception:
            performed_by = "system"
        try:
            from db.planning import toggle_tracker_step as _tts
            _tts(int(data["sid"]), sk, phase_key, gate_key, new_v, performed_by, step_lbl)
        except Exception as _e:
            import logging as _log
            _log.getLogger(__name__).error("toggle_tracker_step failed sid=%s step=%s: %s",
                                           data.get("sid"), sk, _e)

        # ── Auto-sync planning gates from completed lifecycle steps ───────────
        derived   = _derive_planning_gates(state)
        sid_str   = str(data["sid"])
        old_gates = dict(gate_store or {})
        old_g     = old_gates.get(sid_str, {f: False for f in _GATE_FIELDS})
        new_gate_store = no_update

        if derived != {k: old_g.get(k, False) for k in _GATE_FIELDS}:
            old_gates[sid_str] = derived
            new_gate_store = old_gates
            # Persist changed gates to DB
            try:
                from db.planning import upsert_gate as _upsert
                story_obj = next((s for s in (stories_data or []) if s["id"] == data["sid"]), {})
                for gname, gval in derived.items():
                    if gval != old_g.get(gname, False):
                        _upsert(
                            int(data["sid"]), gname, gval, performed_by,
                            title=story_obj.get("title", ""),
                            ba=story_obj.get("ba", ""),
                            dev_name=story_obj.get("dev", ""),
                            month_key=story_obj.get("month", ""),
                            priority=story_obj.get("pri", ""),
                        )
            except Exception:
                pass

        new_data = {"sid": data["sid"], "state": state}
        story    = next((s for s in (stories_data or []) if s["id"] == data["sid"]), None)
        title    = story["title"] if story else f"Item #{data['sid']}"
        return no_update, _header(data["sid"], title, state, story), new_data, new_gate_store

    return no_update, no_update, no_update, no_update


# ── 14. Lifecycle tracker — render body from state ───────────────────────────
@callback(
    Output("tracker-body",       "children"),
    Input("tracker-data",        "data"),
    State("tracker-gate-focus",  "data"),
    prevent_initial_call=True,
)
def _tracker_render(data, gate_filter):
    if not data:
        return []
    return _build_tracker_body(data.get("state", {}), gate_filter)


# ── 15. Reset tracker-sid to None on modal close ──────────────────────────────
# Without this, clicking 📋 on the same story twice sends the same sid value
# so tracker-sid doesn't change → _tracker_open_or_step never re-fires →
# state is not reloaded from DB.
@callback(
    Output("tracker-sid", "data", allow_duplicate=True),
    Input("tracker-modal", "is_open"),
    prevent_initial_call=True,
)
def _reset_tracker_sid_on_close(is_open):
    if not is_open:
        return None
    return no_update
