import os
import time
import pandas as pd
import psycopg2
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from config.team_mapping import TEAM_MAPPING
from config.settings import ANALYSIS_START_DATE

load_dotenv()

# ── Database Configuration ───────────────────────────────────────────────────
DB_USER = "postgres"
DB_PASS = os.getenv("DB_PASSWORD", "1234")
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "vsts_analytics"

# Connection string for SQLAlchemy (requires psycopg2 installed)
CONN_STR = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(CONN_STR, pool_size=10, max_overflow=20)

# Global cache for data
_DATA_CACHE = None
_LAST_LOAD_TIME = 0
CACHE_TTL = 300  # 5 minutes cache duration

def get_db_connection():
    """Fallback for raw psycopg2 if needed, but engine is preferred."""
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT
    )

def load_data(force_refresh=False):
    """
    Load data from PostgreSQL with memory caching.
    Ensures that multiple concurrent dashboards don't overload the DB.
    """
    global _DATA_CACHE, _LAST_LOAD_TIME
    
    now = time.time()
    if not force_refresh and _DATA_CACHE is not None and (now - _LAST_LOAD_TIME) < CACHE_TTL:
        return _DATA_CACHE.copy()
    
    query = """
    SELECT *
    FROM work_items_main
    WHERE
        created_date >= '2025-01-01'
        OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (
            created_date < '2025-01-01'
            AND (closed_date IS NULL OR closed_date >= '2025-01-01')
        );
    """
    
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
            
        # 1. Numerical Cleanups
        if "priority" in df.columns:
            # Convert to numeric, force to int, handle NaNs as 0 or 4
            df["priority"] = pd.to_numeric(df["priority"], errors='coerce').fillna(4).astype(int)
        
        if "remaining_work" in df.columns:
            df["remaining_work"] = pd.to_numeric(df["remaining_work"], errors='coerce').fillna(0)

        # 2. String Normalization (Strip whitespace and handle 'None'/'nan')
        string_cols = ["state", "assigned_to", "work_item_type", "release_date", "function", "iteration_path", "story_owner"]
        for col in string_cols:
            if col in df.columns:
                # Fill actual NaNs with empty string before cleanup
                df[col] = df[col].fillna("").astype(str).str.strip()
                # Treat "None", "nan", or empty as "Not Specified" or "Unassigned" as appropriate
                if col == "assigned_to":
                    df[col] = df[col].replace(["None", "nan", ""], "Unassigned")
                elif col == "story_owner":
                    df[col] = df[col].replace(["None", "nan"], "")
                else:
                    df[col] = df[col].replace(["None", "nan", ""], "Not Specified")

        # 3. Handle Date Conversions
        date_cols = ['created_date', 'closed_date', 'changed_date']
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                if hasattr(df[col].dt, 'tz') and df[col].dt.tz is not None:
                    df[col] = df[col].dt.tz_localize(None)

        # 4. Add team column from assigned_to (used by bugs/QA/items pages)
        if "assigned_to" in df.columns:
            df["team"] = df["assigned_to"].map(TEAM_MAPPING).fillna("Unassigned")
        else:
            df["team"] = "Unassigned"

        # 5. Add main_dev_team from main_developer (used by capacity page)
        if "main_developer" in df.columns:
            md = df["main_developer"].astype(str).str.split(" <").str[0].str.strip()
            df["main_dev_team"] = md.map(TEAM_MAPPING).fillna("Unassigned")
        else:
            df["main_dev_team"] = "Unassigned"

        # 6. Patch parent_id for Tasks linked via "Related" instead of "Child"
        #    People sometimes create tasks under Related instead of Child in ADO.
        #    Pick lowest Enhancement/Bug ID when a task relates to multiple.
        try:
            with engine.connect() as _rc:
                rel_df = pd.read_sql(text("""
                    SELECT DISTINCT ON (t.work_item_id)
                           t.work_item_id AS task_id,
                           CASE WHEN rel.source_id = t.work_item_id
                                THEN rel.target_id
                                ELSE rel.source_id END AS parent_id
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
                      AND t.parent_id IS NULL
                      AND e.work_item_type IN (
                            'Enhancement','Bug','Bug_UI','Bug_Text')
                    ORDER BY t.work_item_id, parent_id
                """), _rc)
            if not rel_df.empty:
                rel_map = rel_df.set_index("task_id")["parent_id"].to_dict()
                mask = (
                    (df["work_item_type"] == "Task")
                    & df["parent_id"].isna()
                    & df["work_item_id"].isin(rel_map)
                )
                df.loc[mask, "parent_id"] = (
                    df.loc[mask, "work_item_id"].map(rel_map)
                )
        except Exception as _re:
            print(f"⚠️  Related-task patch skipped: {_re}")

        # Update cache
        _DATA_CACHE = df
        _LAST_LOAD_TIME = now
        return df.copy()
        
    except Exception as e:
        print(f"❌ Error loading data from DB: {e}")
        # If DB fails and we have old cache, return it as fallback
        if _DATA_CACHE is not None:
            return _DATA_CACHE.copy()
        raise e

def update_db_workitem(work_item_id, field_name, new_value):
    """
    Updates a specific field of a work item in the local PostgreSQL database.
    Uses SQLAlchemy for proper connection management.
    """
    query = text(f"UPDATE work_items_main SET {field_name} = :val WHERE work_item_id = :id")
    
    try:
        with engine.begin() as conn:  # engine.begin() handles transaction commit/rollback
            conn.execute(query, {"val": new_value, "id": work_item_id})
        
        # After a local update, clear the cache to ensure next load gets fresh data
        global _DATA_CACHE
        _DATA_CACHE = None 
        
    except Exception as e:
        print(f"❌ Error updating DB: {e}")
        raise e

def filter_activity_since(df, start_date, end_date=None):
    """
    Keep items relevant to tracking window.
    """
    d = df.copy()
    start = pd.to_datetime(start_date)

    for c in ["created_date", "closed_date"]:
        if c in d.columns:
            d[c] = pd.to_datetime(d[c], errors="coerce")

    created = d["created_date"] if "created_date" in d.columns else pd.Series(pd.NaT, index=d.index)
    closed  = d["closed_date"]  if "closed_date"  in d.columns else pd.Series(pd.NaT, index=d.index)

    keep = (created >= start) | (closed >= start) | closed.isna()
    return d[keep]

def apply_filters(df, item_types=None, release=None, iterations=None, team=None, employee=None):
    """Apply standard dashboard filters."""
    df_filtered = df.copy()

    if item_types and "work_item_type" in df.columns:
        df_filtered = df_filtered[df_filtered["work_item_type"].isin(item_types)]

    if release and release != "All" and "release_date" in df.columns:
        df_filtered = df_filtered[df_filtered["release_date"] == release]

    if iterations and "iteration_path" in df.columns:
        df_filtered = df_filtered[df_filtered["iteration_path"].isin(iterations)]

    if team and team != "All":
        df_filtered = df_filtered[df_filtered["team"] == team]

    if employee and employee != "All":
        person_col = "main_developer" if "main_developer" in df_filtered.columns else "assigned_to"
        df_filtered = df_filtered[df_filtered[person_col] == employee]

    return df_filtered
