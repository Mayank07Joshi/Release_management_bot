"""Import/refresh: Story Tracking CSV → p_story_tracking.

Parses the BA-maintained Story Tracking sheet (exported from the Enhancement
Tracking Excel workbook) and upserts into p_story_tracking.

Only work_item_ids already in work_items_main are imported.
Composite IDs like "36381/38449" are split and both are imported.

Usage:
  python scripts/import_story_tracking.py
  python scripts/import_story_tracking.py --dry-run
  python scripts/import_story_tracking.py --csv path/to/other.csv
"""
from __future__ import annotations
import argparse
import csv
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.loader import engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).parent.parent / "Story_Tracking.csv"


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date | None:
    s = s.strip()
    if not s:
        return None
    s = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)
    for fmt in (
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%d %B %Y",
        "%d %B",
    ):
        try:
            d = datetime.strptime(s, fmt)
            if d.year == 1900:
                d = d.replace(year=2026)
            return d.date()
        except ValueError:
            pass
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            try:
                return date(y, b, a)
            except ValueError:
                pass
    return None


def _parse_float(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_ids(raw: str) -> list[int]:
    return [int(p) for p in re.split(r'[/,]', raw.strip()) if re.match(r'^\d+$', p.strip())]


# ── Main ──────────────────────────────────────────────────────────────────────

def run(csv_path: Path, dry_run: bool) -> None:
    if not csv_path.exists():
        log.error("CSV not found: %s", csv_path)
        sys.exit(1)

    with open(csv_path, newline='', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    log.info("Loaded %d rows from %s", len(rows), csv_path.name)

    with engine.connect() as conn:
        known_ids = set(
            r[0] for r in conn.execute(
                text("SELECT work_item_id FROM work_items_main")
            ).fetchall()
        )
    log.info("%d stories in work_items_main", len(known_ids))

    # Ensure table exists
    if not dry_run:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS p_story_tracking (
                    work_item_id   INTEGER PRIMARY KEY,
                    est_start_date DATE,
                    est_end_date   DATE,
                    est_hours      NUMERIC(8,2),
                    actual_hours   NUMERIC(8,2),
                    story_size     TEXT,
                    story_status   TEXT,
                    story_type     TEXT,
                    design_type    TEXT,
                    responsible_qa TEXT,
                    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))

    written = skipped_missing = skipped_bad = 0

    with engine.begin() as conn:
        for row in rows:
            row = {(k or "").strip(): (v.strip() if isinstance(v, str) else "") for k, v in row.items()}

            wids = _parse_ids(row.get("ID", ""))
            if not wids:
                log.warning("  Skip bad ID: %r", row.get("ID", ""))
                skipped_bad += 1
                continue

            est_start = _parse_date(row.get("Estimated Start Date", ""))
            est_end   = _parse_date(row.get("Estimated End Date", ""))
            est_hrs   = _parse_float(row.get("Estimated Hours", ""))
            act_hrs   = _parse_float(row.get("Actual Spent Hours", ""))

            raw_size   = row.get("Story Size", "").strip()
            raw_status = row.get("Story Status", "").strip()
            raw_type   = row.get("Story Type", "").strip()
            raw_design = row.get("Design", "").strip()
            raw_qa     = row.get("Responsible QA", "").strip()

            for wid in wids:
                if wid not in known_ids:
                    log.debug("  Skip #%d — not in work_items_main", wid)
                    skipped_missing += 1
                    continue

                if not dry_run:
                    conn.execute(text("""
                        INSERT INTO p_story_tracking
                            (work_item_id, est_start_date, est_end_date, est_hours,
                             actual_hours, story_size, story_status, story_type,
                             design_type, responsible_qa, updated_at)
                        VALUES
                            (:id, :est_start, :est_end, :est_hrs,
                             :act_hrs, :size, :status, :stype,
                             :design, :qa, NOW())
                        ON CONFLICT (work_item_id) DO UPDATE
                            SET est_start_date = EXCLUDED.est_start_date,
                                est_end_date   = EXCLUDED.est_end_date,
                                est_hours      = EXCLUDED.est_hours,
                                actual_hours   = EXCLUDED.actual_hours,
                                story_size     = EXCLUDED.story_size,
                                story_status   = EXCLUDED.story_status,
                                story_type     = EXCLUDED.story_type,
                                design_type    = EXCLUDED.design_type,
                                responsible_qa = EXCLUDED.responsible_qa,
                                updated_at     = NOW()
                    """), {
                        "id": wid, "est_start": est_start, "est_end": est_end,
                        "est_hrs": est_hrs, "act_hrs": act_hrs,
                        "size": raw_size or None, "status": raw_status or None,
                        "stype": raw_type or None, "design": raw_design or None,
                        "qa": raw_qa or None,
                    })
                written += 1
                log.info("  OK  #%d  %s", wid, row.get("Title", "")[:70])

    mode = "DRY RUN — " if dry_run else ""
    log.info(
        "%sComplete. %d rows written. Skipped: %d not in DB, %d bad ID.",
        mode, written, skipped_missing, skipped_bad,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv",     default=str(DEFAULT_CSV), help="Path to CSV file")
    ap.add_argument("--dry-run", action="store_true",      help="Parse only, no DB writes")
    args = ap.parse_args()
    run(Path(args.csv), args.dry_run)
