"""
CRUD operations for all platform entities.
All writes go through here — single place for audit logging.
ADO write-back fires on every create and update automatically.
"""
from datetime import datetime
from sqlalchemy import text
from data.loader import engine
from sync.ado_write import write_fields, create_and_link_async


# ── ADO write helpers ─────────────────────────────────────────────────────────

def _user_display_name(user_id: int | None) -> str | None:
    """Resolve a user_id to their ADO-compatible display_name."""
    if not user_id:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT display_name FROM p_users WHERE user_id = :id"),
                {"id": user_id}
            ).fetchone()
        return row.display_name if row else None
    except Exception:
        return None


def _feature_ado_fields(fields: dict, current: dict = None) -> dict:
    """
    Map platform feature fields to ado_write field names.
    Resolves user IDs to display names. Skips None values.
    current: existing record dict (for resolving unchanged user IDs on updates)
    """
    base = current or {}
    out = {}

    if "title" in fields and fields["title"]:
        out["title"] = fields["title"]
    if "state" in fields and fields["state"]:
        out["state"] = fields["state"]
    if "priority" in fields and fields["priority"] is not None:
        out["priority"] = fields["priority"]
    if "iteration" in fields and fields["iteration"]:
        out["iteration"] = fields["iteration"]
    if "original_estimate" in fields and fields["original_estimate"] is not None:
        out["original_estimate"] = fields["original_estimate"]
    if "area" in fields and fields["area"]:
        out["area"] = fields["area"]
    if "tags" in fields and fields["tags"]:
        out["tags"] = fields["tags"]
    if "description" in fields and fields["description"]:
        out["description"] = fields["description"]

    # Resolve user IDs → display names
    uid = fields.get("assigned_to_id") or base.get("assigned_to_id")
    if uid:
        name = _user_display_name(uid)
        if name:
            out["assigned_to"] = name

    uid = fields.get("main_developer_id") or base.get("main_developer_id")
    if uid:
        name = _user_display_name(uid)
        if name:
            out["main_developer"] = name

    uid = fields.get("main_designer_id") or base.get("main_designer_id")
    if uid:
        name = _user_display_name(uid)
        if name:
            out["main_designer"] = name

    return out


def _bug_ado_fields(fields: dict, current: dict = None) -> dict:
    """Map platform bug fields to ado_write field names."""
    base = current or {}
    out = {}

    if "title" in fields and fields["title"]:
        out["title"] = fields["title"]
    if "state" in fields and fields["state"]:
        out["state"] = fields["state"]
    if "priority" in fields and fields["priority"] is not None:
        out["priority"] = fields["priority"]
    if "area" in fields and fields["area"]:
        out["area"] = fields["area"]
    if "found_in_iteration" in fields and fields["found_in_iteration"]:
        out["iteration"] = fields["found_in_iteration"]
    if "repro_steps" in fields and fields["repro_steps"]:
        out["description"] = fields["repro_steps"]

    uid = fields.get("assigned_to_id") or base.get("assigned_to_id")
    if uid:
        name = _user_display_name(uid)
        if name:
            out["assigned_to"] = name

    uid = fields.get("main_developer_id") or base.get("main_developer_id")
    if uid:
        name = _user_display_name(uid)
        if name:
            out["main_developer"] = name

    return out


# ── Reference number generator ───────────────────────────────────────────────

def next_ref(entity_type: str) -> str:
    """
    Atomically increment the counter and return the next ref string.
    e.g. entity_type='epic' → 'EP-001'
    """
    prefix_map = {
        "epic":    "EP",
        "release": "REL",
        "feature": "F",
        "bug":     "B",
        "task":    "T",
    }
    prefix = prefix_map[entity_type]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE p_ref_counters SET last_seq = last_seq + 1 WHERE entity_type = :t"),
            {"t": entity_type}
        )
        row = conn.execute(
            text("SELECT last_seq FROM p_ref_counters WHERE entity_type = :t"),
            {"t": entity_type}
        ).fetchone()
    return f"{prefix}-{row.last_seq:03d}"


# ── Audit helper ─────────────────────────────────────────────────────────────

def _audit(conn, entity_type, entity_id, entity_ref, field, old_val, new_val, user_id):
    if str(old_val) == str(new_val):
        return
    conn.execute(text("""
        INSERT INTO p_audit_log
            (entity_type, entity_id, entity_ref, field_changed, old_value, new_value, changed_by)
        VALUES
            (:etype, :eid, :eref, :field, :old, :new, :uid)
    """), {
        "etype": entity_type, "eid": entity_id, "eref": entity_ref,
        "field": field, "old": str(old_val) if old_val is not None else None,
        "new":   str(new_val) if new_val is not None else None,
        "uid":   user_id,
    })


# ── Users ─────────────────────────────────────────────────────────────────────

def get_all_users():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT user_id, username, display_name, role, team, email, is_active "
            "FROM p_users ORDER BY display_name"
        )).fetchall()
    return [dict(r._mapping) for r in rows]

def get_active_users():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT user_id, username, display_name, role, team "
            "FROM p_users WHERE is_active = TRUE ORDER BY display_name"
        )).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Epics ─────────────────────────────────────────────────────────────────────

def get_all_epics():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT e.*, u.display_name AS owner_name
            FROM p_epics e
            LEFT JOIN p_users u ON u.user_id = e.owner_id
            ORDER BY e.created_at DESC
        """)).fetchall()
    return [dict(r._mapping) for r in rows]

def get_epic(epic_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM p_epics WHERE epic_id = :id"), {"id": epic_id}
        ).fetchone()
    return dict(row._mapping) if row else None

def create_epic(title, description, owner_id, tags, created_by):
    ref = next_ref("epic")
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO p_epics (epic_ref, title, description, owner_id, tags, created_by)
            VALUES (:ref, :title, :desc, :owner, :tags, :by)
            RETURNING epic_id
        """), {"ref": ref, "title": title, "desc": description,
               "owner": owner_id, "tags": tags, "by": created_by}).fetchone()
        _audit(conn, "epic", row.epic_id, ref, "state", None, "Active", created_by)
    return ref

def update_epic(epic_id, fields: dict, updated_by: int):
    """fields = dict of column → new_value"""
    current = get_epic(epic_id)
    if not current:
        raise ValueError(f"Epic {epic_id} not found")
    allowed = {"title", "description", "owner_id", "status", "tags"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in safe)
    safe["epic_id"]  = epic_id
    safe["updated_at"] = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE p_epics SET {set_clause}, updated_at = :updated_at WHERE epic_id = :epic_id"),
            safe
        )
        for field, new_val in fields.items():
            _audit(conn, "epic", epic_id, current["epic_ref"],
                   field, current.get(field), new_val, updated_by)


# ── Releases ──────────────────────────────────────────────────────────────────

def get_all_releases(include_archived=False):
    where = "" if include_archived else "WHERE status != 'Archived'"
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT r.*, u.display_name AS owner_name
            FROM p_releases r
            LEFT JOIN p_users u ON u.user_id = r.owner_id
            {where}
            ORDER BY r.target_date DESC NULLS LAST
        """)).fetchall()
    return [dict(r._mapping) for r in rows]

def get_release(release_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM p_releases WHERE release_id = :id"), {"id": release_id}
        ).fetchone()
    return dict(row._mapping) if row else None

def create_release(title, description, target_date, owner_id, iterations, created_by):
    ref = next_ref("release")
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO p_releases
                (release_ref, title, description, target_date, owner_id, iterations, created_by)
            VALUES (:ref, :title, :desc, :tdate, :owner, :iters, :by)
            RETURNING release_id
        """), {"ref": ref, "title": title, "desc": description,
               "tdate": target_date, "owner": owner_id,
               "iters": iterations, "by": created_by}).fetchone()
        _audit(conn, "release", row.release_id, ref, "state", None, "Planning", created_by)
    return ref

def update_release(release_id, fields: dict, updated_by: int):
    current = get_release(release_id)
    if not current:
        raise ValueError(f"Release {release_id} not found")
    allowed = {"title", "description", "target_date", "owner_id", "status", "iterations"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in safe)
    safe["release_id"] = release_id
    safe["updated_at"] = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE p_releases SET {set_clause}, updated_at = :updated_at WHERE release_id = :release_id"),
            safe
        )
        for field, new_val in fields.items():
            _audit(conn, "release", release_id, current["release_ref"],
                   field, current.get(field), new_val, updated_by)


# ── Features ──────────────────────────────────────────────────────────────────

def get_all_features(epic_id=None, release_id=None):
    where_parts = []
    params = {}
    if epic_id:
        where_parts.append("f.epic_id = :epic_id")
        params["epic_id"] = epic_id
    if release_id:
        where_parts.append("f.planned_release_id = :release_id")
        params["release_id"] = release_id
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT f.*,
                   e.title          AS epic_title,
                   e.epic_ref       AS epic_ref,
                   r.title          AS release_title,
                   r.release_ref    AS release_ref,
                   u.display_name   AS assignee_name,
                   d.display_name   AS developer_name
            FROM p_features f
            LEFT JOIN p_epics    e ON e.epic_id    = f.epic_id
            LEFT JOIN p_releases r ON r.release_id = f.planned_release_id
            LEFT JOIN p_users    u ON u.user_id    = f.assigned_to_id
            LEFT JOIN p_users    d ON d.user_id    = f.main_developer_id
            {where}
            ORDER BY f.created_at DESC
        """), params).fetchall()
    return [dict(r._mapping) for r in rows]

def get_feature(feature_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM p_features WHERE feature_id = :id"), {"id": feature_id}
        ).fetchone()
    return dict(row._mapping) if row else None

def create_feature(title, description, epic_id, planned_release_id, iteration,
                   priority, assigned_to_id, main_developer_id, main_designer_id,
                   original_estimate, area, func, tags, created_by):
    ref = next_ref("feature")
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO p_features
                (feature_ref, title, description, epic_id, planned_release_id,
                 iteration, priority, assigned_to_id, main_developer_id,
                 main_designer_id, original_estimate, area, func, tags, created_by)
            VALUES
                (:ref, :title, :desc, :epic, :rel, :iter, :pri,
                 :ato, :mdev, :mdes, :est, :area, :func, :tags, :by)
            RETURNING feature_id
        """), {
            "ref": ref, "title": title, "desc": description,
            "epic": epic_id, "rel": planned_release_id, "iter": iteration,
            "pri": priority, "ato": assigned_to_id, "mdev": main_developer_id,
            "mdes": main_designer_id, "est": original_estimate,
            "area": area, "func": func, "tags": tags, "by": created_by,
        }).fetchone()
        _audit(conn, "feature", row.feature_id, ref, "state", None, "Backlog", created_by)
        local_id = row.feature_id

    # Fire-and-forget: create in ADO and link ado_id back
    create_and_link_async("feature", local_id, _feature_ado_fields({
        "title": title, "state": "Backlog", "priority": priority,
        "iteration": iteration, "original_estimate": original_estimate,
        "area": area, "tags": tags, "description": description,
        "assigned_to_id": assigned_to_id, "main_developer_id": main_developer_id,
        "main_designer_id": main_designer_id,
    }))
    return ref, local_id

def update_feature(feature_id, fields: dict, updated_by: int):
    current = get_feature(feature_id)
    if not current:
        raise ValueError(f"Feature {feature_id} not found")
    allowed = {
        "title", "description", "epic_id", "planned_release_id", "actual_release_id",
        "iteration", "priority", "state", "assigned_to_id", "main_developer_id",
        "main_designer_id", "original_estimate", "area", "func", "tags"
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return

    # Auto-set spill_over if actual_release differs from planned
    if "actual_release_id" in safe:
        planned = current.get("planned_release_id")
        actual  = safe["actual_release_id"]
        safe["spill_over"] = (actual is not None and planned is not None and actual != planned)

    # Auto-set closed_at on Done
    if safe.get("state") == "Done" and current.get("state") != "Done":
        safe["closed_at"] = datetime.utcnow()

    safe["feature_id"] = feature_id
    safe["updated_at"] = datetime.utcnow()
    set_clause = ", ".join(f"{k} = :{k}" for k in safe if k != "feature_id")
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE p_features SET {set_clause} WHERE feature_id = :feature_id"),
            safe
        )
        for field, new_val in fields.items():
            _audit(conn, "feature", feature_id, current["feature_ref"],
                   field, current.get(field), new_val, updated_by)

    # Fire-and-forget ADO update if this feature has an ado_id
    if current.get("ado_id"):
        write_fields(current["ado_id"], _feature_ado_fields(fields, current))


# ── Bugs ──────────────────────────────────────────────────────────────────────

def get_all_bugs(linked_feature_id=None, pool_only=False):
    where_parts = []
    params = {}
    if pool_only:
        where_parts.append("b.linked_feature_id IS NULL")
    elif linked_feature_id:
        where_parts.append("b.linked_feature_id = :fid")
        params["fid"] = linked_feature_id
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT b.*,
                   f.title         AS feature_title,
                   f.feature_ref   AS feature_ref,
                   u.display_name  AS assignee_name,
                   d.display_name  AS main_developer_name
            FROM p_bugs b
            LEFT JOIN p_features f ON f.feature_id = b.linked_feature_id
            LEFT JOIN p_users    u ON u.user_id     = b.assigned_to_id
            LEFT JOIN p_users    d ON d.user_id     = b.main_developer_id
            {where}
            ORDER BY b.created_at DESC
        """), params).fetchall()
    return [dict(r._mapping) for r in rows]

def get_bug(bug_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM p_bugs WHERE bug_id = :id"), {"id": bug_id}
        ).fetchone()
    return dict(row._mapping) if row else None

def create_bug(title, bug_type, linked_feature_id, priority, severity,
               assigned_to_id, main_developer_id, area, func,
               found_in_iteration, found_in_release_id, repro_steps, created_by):
    ref = next_ref("bug")
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO p_bugs
                (bug_ref, title, bug_type, linked_feature_id, priority, severity,
                 assigned_to_id, main_developer_id, area, func,
                 found_in_iteration, found_in_release_id, repro_steps, created_by)
            VALUES
                (:ref, :title, :btype, :fid, :pri, :sev,
                 :ato, :mdev, :area, :func,
                 :iter, :rel, :repro, :by)
            RETURNING bug_id
        """), {
            "ref": ref, "title": title, "btype": bug_type, "fid": linked_feature_id,
            "pri": priority, "sev": severity, "ato": assigned_to_id, "mdev": main_developer_id,
            "area": area, "func": func, "iter": found_in_iteration,
            "rel": found_in_release_id, "repro": repro_steps, "by": created_by,
        }).fetchone()
        _audit(conn, "bug", row.bug_id, ref, "state", None, "New", created_by)
        local_id = row.bug_id

    # Fire-and-forget: create in ADO and link ado_id back
    create_and_link_async("bug", local_id, _bug_ado_fields({
        "title": title, "state": "New", "priority": priority,
        "area": area, "found_in_iteration": found_in_iteration,
        "repro_steps": repro_steps,
        "assigned_to_id": assigned_to_id, "main_developer_id": main_developer_id,
    }))
    return ref

def update_bug(bug_id, fields: dict, updated_by: int):
    current = get_bug(bug_id)
    if not current:
        raise ValueError(f"Bug {bug_id} not found")
    allowed = {
        "title", "bug_type", "linked_feature_id", "priority", "severity",
        "state", "assigned_to_id", "main_developer_id", "area", "func",
        "found_in_iteration", "found_in_release_id", "repro_steps"
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return

    # Track re-opens
    if safe.get("state") == "Active" and current.get("state") in ("Closed", "Resolved"):
        safe["closed_at"] = None  # clear closed date on reopen

    if safe.get("state") == "Closed" and current.get("state") != "Closed":
        safe["closed_at"] = datetime.utcnow()

    safe["bug_id"]    = bug_id
    safe["updated_at"] = datetime.utcnow()
    set_clause = ", ".join(f"{k} = :{k}" for k in safe if k != "bug_id")
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE p_bugs SET {set_clause} WHERE bug_id = :bug_id"),
            safe
        )
        for field, new_val in fields.items():
            _audit(conn, "bug", bug_id, current["bug_ref"],
                   field, current.get(field), new_val, updated_by)

    # Fire-and-forget ADO update if this bug has an ado_id
    if current.get("ado_id"):
        write_fields(current["ado_id"], _bug_ado_fields(fields, current))

def get_audit_trail(entity_type: str, entity_id: int):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT a.*, u.display_name AS actor_name
            FROM p_audit_log a
            LEFT JOIN p_users u ON u.user_id = a.changed_by
            WHERE a.entity_type = :etype AND a.entity_id = :eid
            ORDER BY a.changed_at ASC
        """), {"etype": entity_type, "eid": entity_id}).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Tasks ─────────────────────────────────────────────────────────────────────

def get_tasks_for_feature(feature_id: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT t.*,
                   u.display_name AS assignee_name
            FROM p_tasks t
            LEFT JOIN p_users u ON u.user_id = t.assigned_to_id
            WHERE t.parent_feature_id = :fid
            ORDER BY t.created_at ASC
        """), {"fid": feature_id}).fetchall()
    return [dict(r._mapping) for r in rows]


def get_tasks_for_iteration(iteration: str) -> list[dict]:
    """All tasks for features assigned to the given iteration."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                t.task_id, t.task_ref, t.title, t.state, t.priority,
                t.original_estimate, t.completed_work, t.remaining_work,
                t.activity, t.template_key, t.tags,
                t.created_at, t.closed_at,
                f.title        AS feature_title,
                f.feature_ref  AS feature_ref,
                f.feature_id   AS feature_id,
                u.display_name AS assignee_name
            FROM p_tasks t
            JOIN p_features f ON f.feature_id = t.parent_feature_id
            LEFT JOIN p_users u ON u.user_id = t.assigned_to_id
            WHERE f.iteration = :iter
            ORDER BY t.state, u.display_name NULLS LAST, t.task_ref
        """), {"iter": iteration}).fetchall()
    return [dict(r._mapping) for r in rows]


def get_all_items_for_iteration(iteration: str) -> dict:
    """
    Returns all work items for an iteration grouped by type:
      features — p_features.iteration = iteration
      tasks    — tasks whose parent feature is in that iteration
      bugs     — bugs linked to features in that iteration
    Capacity is calculated from tasks only; all three appear on the board.
    """
    with engine.connect() as conn:
        features = conn.execute(text("""
            SELECT
                f.feature_id, f.feature_ref, f.title, f.state, f.priority,
                f.original_estimate, f.iteration, f.tags,
                f.created_at, f.closed_at,
                u.display_name AS assignee_name
            FROM p_features f
            LEFT JOIN p_users u ON u.user_id = f.assigned_to_id
            WHERE f.iteration = :iter
            ORDER BY f.state, u.display_name NULLS LAST, f.feature_ref
        """), {"iter": iteration}).fetchall()

        feat_ids = [r.feature_id for r in features]

        tasks = conn.execute(text("""
            SELECT
                t.task_id, t.task_ref, t.title, t.state, t.priority,
                t.original_estimate, t.completed_work, t.remaining_work,
                t.activity, t.tags, t.created_at, t.closed_at,
                f.title        AS feature_title,
                f.feature_ref  AS feature_ref,
                f.feature_id   AS feature_id,
                u.display_name AS assignee_name
            FROM p_tasks t
            JOIN p_features f ON f.feature_id = t.parent_feature_id
            LEFT JOIN p_users u ON u.user_id = t.assigned_to_id
            WHERE f.iteration = :iter
            ORDER BY t.state, u.display_name NULLS LAST, t.task_ref
        """), {"iter": iteration}).fetchall()

        bugs = []
        if feat_ids:
            bugs = conn.execute(text("""
                SELECT
                    b.bug_id, b.bug_ref, b.title, b.state, b.priority,
                    b.severity, b.bug_type, b.tags, b.created_at, b.closed_at,
                    f.title        AS feature_title,
                    f.feature_ref  AS feature_ref,
                    f.feature_id   AS feature_id,
                    u.display_name AS assignee_name
                FROM p_bugs b
                JOIN p_features f ON f.feature_id = b.linked_feature_id
                LEFT JOIN p_users u ON u.user_id = b.assigned_to_id
                WHERE b.linked_feature_id = ANY(:fids)
                ORDER BY b.state, u.display_name NULLS LAST, b.bug_ref
            """), {"fids": feat_ids}).fetchall()

    return {
        "features": [dict(r._mapping) for r in features],
        "tasks":    [dict(r._mapping) for r in tasks],
        "bugs":     [dict(r._mapping) for r in bugs],
    }


def get_task(task_id: int) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM p_tasks WHERE task_id = :id"), {"id": task_id}
        ).fetchone()
    return dict(row._mapping) if row else None


def create_task(
    title, activity, template_key, parent_feature_id,
    assigned_to_id, priority, original_estimate,
    description, dod, tags, created_by,
) -> str:
    ref = next_ref("task")
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO p_tasks
                (task_ref, title, activity, template_key, parent_feature_id,
                 assigned_to_id, priority, original_estimate,
                 description, dod, tags, created_by)
            VALUES
                (:ref, :title, :act, :tkey, :fid,
                 :ato, :pri, :est,
                 :desc, :dod, :tags, :by)
            RETURNING task_id
        """), {
            "ref": ref, "title": title, "act": activity, "tkey": template_key,
            "fid": parent_feature_id, "ato": assigned_to_id, "pri": priority,
            "est": original_estimate, "desc": description, "dod": dod,
            "tags": tags, "by": created_by,
        }).fetchone()
        _audit(conn, "task", row.task_id, ref, "state", None, "To Do", created_by)
        local_id = row.task_id

    # Resolve assignee name for ADO
    assignee_name = _user_display_name(assigned_to_id)
    ado_fields = {"title": title, "state": "To Do", "priority": priority}
    if original_estimate is not None:
        ado_fields["original_estimate"] = original_estimate
    if assignee_name:
        ado_fields["assigned_to"] = assignee_name
    if tags:
        ado_fields["tags"] = tags

    create_and_link_async("task", local_id, ado_fields)
    return ref


def update_task(task_id: int, fields: dict, updated_by: int) -> None:
    current = get_task(task_id)
    if not current:
        raise ValueError(f"Task {task_id} not found")
    allowed = {
        "title", "activity", "assigned_to_id", "state", "priority",
        "original_estimate", "completed_work", "remaining_work",
        "description", "dod", "tags",
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return

    if safe.get("state") == "Done" and current.get("state") != "Done":
        safe["closed_at"] = datetime.utcnow()
    if safe.get("state") in ("To Do", "In Progress", "Blocked") and current.get("state") == "Done":
        safe["closed_at"] = None

    safe["task_id"]    = task_id
    safe["updated_at"] = datetime.utcnow()
    set_clause = ", ".join(f"{k} = :{k}" for k in safe if k != "task_id")
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE p_tasks SET {set_clause} WHERE task_id = :task_id"),
            safe
        )
        for field, new_val in fields.items():
            _audit(conn, "task", task_id, current["task_ref"],
                   field, current.get(field), new_val, updated_by)

    if current.get("ado_id"):
        ado_fields = {}
        if "state" in fields:
            ado_fields["state"] = fields["state"]
        if "assigned_to_id" in fields:
            name = _user_display_name(fields["assigned_to_id"])
            if name:
                ado_fields["assigned_to"] = name
        if "original_estimate" in fields:
            ado_fields["original_estimate"] = fields["original_estimate"]
        if "completed_work" in fields:
            ado_fields["completed_work"] = fields["completed_work"]
        if ado_fields:
            write_fields(current["ado_id"], ado_fields)


def create_tasks_from_templates(
    feature_id: int,
    feature_ref: str,
    feature_title: str,
    template_keys: list[str],
    assigned_to_id: int | None,
    created_by: int,
) -> list[str]:
    """
    Batch-create tasks from template keys for a feature.
    Returns list of task refs created.
    """
    from db.templates import generate_tasks
    task_dicts = generate_tasks(feature_ref, feature_title, template_keys)
    refs = []
    for t in task_dicts:
        ref = create_task(
            title=t["title"],
            activity=t["activity"],
            template_key=t["template_key"],
            parent_feature_id=feature_id,
            assigned_to_id=assigned_to_id,
            priority=t["priority"],
            original_estimate=t["original_estimate"],
            description=t["description"],
            dod=t["dod"],
            tags=t["tags"],
            created_by=created_by,
        )
        refs.append(ref)
    return refs


# ── Iteration Capacity Configuration ─────────────────────────────────────────

def get_iteration_capacity(iteration: str = None) -> list[dict]:
    """Return capacity configs, optionally filtered to a single iteration."""
    where = "WHERE iteration = :iter" if iteration else ""
    params = {"iter": iteration} if iteration else {}
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT * FROM p_iteration_capacity
            {where}
            ORDER BY iteration, person
        """), params).fetchall()
    return [dict(r._mapping) for r in rows]


def upsert_iteration_capacity(
    person: str,
    iteration: str,
    available_days: float,
    hours_per_day: float,
    leave_days: float,
    notes: str,
    created_by: int,
) -> None:
    """
    Insert or update a capacity config for one person in one iteration.
    Uses ON CONFLICT (person, iteration) DO UPDATE — safe to call repeatedly.
    """
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_iteration_capacity
                (person, iteration, available_days, hours_per_day, leave_days, notes, created_by)
            VALUES
                (:person, :iter, :avail, :hpd, :leave, :notes, :by)
            ON CONFLICT (person, iteration) DO UPDATE SET
                available_days = EXCLUDED.available_days,
                hours_per_day  = EXCLUDED.hours_per_day,
                leave_days     = EXCLUDED.leave_days,
                notes          = EXCLUDED.notes,
                updated_at     = NOW()
        """), {
            "person": person, "iter": iteration,
            "avail": available_days, "hpd": hours_per_day,
            "leave": leave_days, "notes": notes, "by": created_by,
        })


def delete_iteration_capacity(config_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM p_iteration_capacity WHERE config_id = :id"),
            {"id": config_id}
        )


def get_capacity_summary(iteration: str) -> list[dict]:
    """
    Per-person capacity summary for a given iteration.
    Merges configured available hours (p_iteration_capacity) with
    actual assigned task estimates (p_tasks → p_features by iteration).
    Returns one dict per person, sorted alphabetically.
    """
    with engine.connect() as conn:
        cap_rows = conn.execute(text("""
            SELECT person, total_available_hours, available_days,
                   hours_per_day, leave_days, notes, config_id
            FROM p_iteration_capacity
            WHERE iteration = :iter
        """), {"iter": iteration}).fetchall()
        cap_map = {r.person: dict(r._mapping) for r in cap_rows}

        task_rows = conn.execute(text("""
            SELECT
                u.display_name                       AS person,
                COUNT(t.task_id)                     AS task_count,
                COALESCE(SUM(t.original_estimate), 0) AS assigned_hours
            FROM p_tasks t
            JOIN p_features f ON f.feature_id = t.parent_feature_id
            JOIN p_users    u ON u.user_id    = t.assigned_to_id
            WHERE f.iteration = :iter
              AND t.state NOT IN ('Done')
            GROUP BY u.display_name
        """), {"iter": iteration}).fetchall()
        task_map = {r.person: dict(r._mapping) for r in task_rows}

    all_persons = sorted(set(cap_map.keys()) | set(task_map.keys()))
    result = []
    for person in all_persons:
        cap      = cap_map.get(person, {})
        task     = task_map.get(person, {})
        avail    = float(cap.get("total_available_hours") or 0)
        assigned = float(task.get("assigned_hours") or 0)
        util_pct = round(assigned / avail * 100, 1) if avail else None
        result.append({
            "person":          person,
            "config_id":       cap.get("config_id"),
            "available_hours": avail,
            "available_days":  cap.get("available_days"),
            "hours_per_day":   cap.get("hours_per_day"),
            "leave_days":      cap.get("leave_days"),
            "notes":           cap.get("notes"),
            "assigned_hours":  assigned,
            "task_count":      int(task.get("task_count") or 0),
            "util_pct":        util_pct,
        })
    return result


def get_all_iterations_from_features() -> list[str]:
    """Return distinct non-null iterations from p_features, sorted."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT iteration FROM p_features
            WHERE iteration IS NOT NULL AND iteration != ''
            ORDER BY iteration
        """)).fetchall()
    return [r.iteration for r in rows]
