"""One-time import: Enhancement_Tracking CSV → p_release_stages + p_release_rows.

Parses the free-text stage cells (dates, ETAs, Complete flags) and upserts
into the two p_release_* tables that back the Release Status page.

Usage:
  python scripts/import_release_stages.py
  python scripts/import_release_stages.py --dry-run
  python scripts/import_release_stages.py --csv path/to/other.csv
"""
from __future__ import annotations
import argparse
import csv
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.loader import engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).parent.parent / "Enhancement_Tracking(Enhancements_v2).csv"

# CSV column header → stage_key (headers are stripped before lookup)
STAGE_COLS = [
    ("Development Status",       "dev_status"),
    ("Testing on Demo Status",   "testing_demo"),
    ("QA Sign Off",              "qa_sign_off"),
    ("Sunil's Sign Off",         "sunil_sign_off"),
    ("Final Demo 1 on Demo env", "final_demo_1"),
    ("Deployment on Dev",        "deploy_dev"),
    ("Dev Env.",                 "dev_env"),
    ("Deployment on QA",         "deploy_qa"),
    ("Final Demo 2 on QA Env.",  "final_demo_2"),
    ("QA Env.",                  "qa_env"),
    ("Live",                     "live"),
    ("Overall Status",           "overall_status"),
]


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date | None:
    s = s.strip()
    if not s:
        return None
    # Strip ordinal suffixes: 1st, 2nd, 3rd, 4th …
    s = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)
    # Try formats in priority order
    for fmt in (
        "%m/%d/%Y",      # 6/15/2026  (US — dominant in this CSV)
        "%d-%m-%Y",      # 26-5-2026  (hyphen, day-first)
        "%A, %B %d, %Y", # Friday, May 22, 2026
        "%B %d, %Y",     # May 22, 2026
        "%d %B %Y",      # 15 May 2026
        "%d %B",         # 15 June  (no year — see below)
    ):
        try:
            d = datetime.strptime(s, fmt)
            if d.year == 1900:          # format had no year
                d = d.replace(year=2026)
            return d.date()
        except ValueError:
            pass
    # D/M/YYYY with slash when first part > 12 (unambiguously day-first)
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            try:
                return date(y, b, a)
            except ValueError:
                pass
    return None


# ── Stage cell parsing ────────────────────────────────────────────────────────

def _parse_cell(raw: str) -> tuple[str, date | None]:
    """Return (status, stage_date) from a raw CSV stage cell."""
    # Collapse internal newlines/extra whitespace to a single space
    cell = " ".join(raw.split()).strip()

    if not cell or cell.upper() in ("NA", "N/A", "-", "—"):
        return "not_started", None

    cl = cell.lower()

    # ETA: <date>  →  wip + eta date
    if re.match(r'^eta\s*:', cl):
        date_part = re.sub(r'^eta\s*:\s*', '', cell, flags=re.IGNORECASE).strip()
        # Take first date if there are multiple ("ETA: 27-04-2026, 28-04-2026")
        first = re.split(r'[,;]', date_part)[0].strip()
        return "wip", _parse_date(first)

    # "Inprogress" / "In Progress" variants  →  wip
    if re.search(r'\bin\s*progress\b', cl) or "inprogress" in cl:
        return "wip", None

    # "Dev Complete" / "Dev complete"  →  done (development stage finished)
    if re.match(r'^dev\s+complete\b', cl):
        return "done", None

    # "Complete" / "Completed" with optional trailing date
    if re.match(r'^completed?\b', cl):
        remainder = re.sub(r'^completed?\s*', '', cell, flags=re.IGNORECASE).strip()
        # Remove noise like "Web testing done -"
        remainder = re.sub(r'^[a-zA-Z\s\-]+\s*', '', remainder).strip()
        d = _parse_date(remainder) if remainder else None
        return "done", d

    # Pure date or a cell whose primary content is a date  →  done + date
    d = _parse_date(cell)
    if d:
        return "done", d

    # Cell contains meaningful text AND a date somewhere (e.g. "Web done - 24-4-2026")
    m = re.search(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b', cell)
    if m:
        d = _parse_date(m.group(1))
        if d:
            return "done", d

    # Unrecognised content — treat as wip (something is recorded, not done)
    return "wip", None


# ── ID validation ─────────────────────────────────────────────────────────────

def _to_int_id(raw: str) -> int | None:
    raw = raw.strip()
    if re.match(r'^\d+$', raw):
        return int(raw)
    return None   # skip composite IDs like "36381/38449"


# ── Main ──────────────────────────────────────────────────────────────────────

def run(csv_path: Path, dry_run: bool) -> None:
    if not csv_path.exists():
        log.error("CSV not found: %s", csv_path)
        sys.exit(1)

    with open(csv_path, newline='', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    log.info("Loaded %d rows from %s", len(rows), csv_path.name)

    stages_written = rows_written = skipped = 0
    parse_errors: list[str] = []

    with engine.begin() as conn:
        for row in rows:
            # Normalise all header keys (strip whitespace)
            row = {k.strip(): v for k, v in row.items()}

            wid = _to_int_id(row.get("ID", ""))
            if wid is None:
                log.warning("  Skip bad ID: %r", row.get("ID", ""))
                skipped += 1
                continue

            # ── p_release_rows: QA person + comment ──────────────────────────
            qa      = row.get("QA's Assigned", "").strip()
            comment = row.get("Comment", "").strip()

            if qa or comment:
                if not dry_run:
                    conn.execute(text("""
                        INSERT INTO p_release_rows (work_item_id, qa_person, comment)
                        VALUES (:id, :qa, :comment)
                        ON CONFLICT (work_item_id) DO UPDATE
                            SET qa_person  = EXCLUDED.qa_person,
                                comment    = EXCLUDED.comment,
                                updated_at = NOW()
                    """), {"id": wid, "qa": qa, "comment": comment})
                rows_written += 1

            # ── p_release_stages: 12 pipeline stages ─────────────────────────
            for col, stage_key in STAGE_COLS:
                raw = row.get(col, "") or ""
                status, stage_date = _parse_cell(raw)

                if not dry_run:
                    conn.execute(text("""
                        INSERT INTO p_release_stages
                               (work_item_id, stage_key, status, stage_date)
                        VALUES (:id, :key, :status, :date)
                        ON CONFLICT (work_item_id, stage_key) DO UPDATE
                            SET status     = EXCLUDED.status,
                                stage_date = EXCLUDED.stage_date
                    """), {"id": wid, "key": stage_key,
                           "status": status, "date": stage_date})
                stages_written += 1

    mode = "DRY RUN — " if dry_run else ""
    log.info(
        "%sComplete. %d stage rows, %d release rows upserted. %d rows skipped.",
        mode, stages_written, rows_written, skipped,
    )
    if parse_errors:
        log.warning("Parse issues:\n  %s", "\n  ".join(parse_errors))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv",     default=str(DEFAULT_CSV), help="Path to CSV file")
    ap.add_argument("--dry-run", action="store_true",      help="Parse only, no DB writes")
    args = ap.parse_args()
    run(Path(args.csv), args.dry_run)
