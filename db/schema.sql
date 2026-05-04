-- ============================================================
-- In-House Platform Schema
-- Database: vsts_analytics (PostgreSQL)
-- All platform tables are prefixed with "p_" to distinguish
-- from ADO-synced tables (work_items_main etc.)
-- ============================================================

-- ── Reference counters (auto-generates EP-001, REL-001 etc.) ─────────────────
CREATE TABLE IF NOT EXISTS p_ref_counters (
    entity_type  TEXT PRIMARY KEY,  -- 'epic', 'release', 'feature', 'bug'
    last_seq     INTEGER NOT NULL DEFAULT 0
);
INSERT INTO p_ref_counters (entity_type, last_seq) VALUES
    ('epic',    0),
    ('release', 0),
    ('feature', 0),
    ('bug',     0),
    ('task',    0)
ON CONFLICT (entity_type) DO NOTHING;

-- ── Users ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS p_users (
    user_id      SERIAL PRIMARY KEY,
    username     TEXT UNIQUE NOT NULL,
    email        TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'viewer',
        -- roles: admin | pm | developer | qa | designer | viewer
    team         TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login   TIMESTAMPTZ
);

-- ── Epics ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS p_epics (
    epic_id      SERIAL PRIMARY KEY,
    epic_ref     TEXT UNIQUE NOT NULL,  -- EP-001
    title        TEXT NOT NULL,
    description  TEXT,
    owner_id     INTEGER REFERENCES p_users(user_id),
    status       TEXT NOT NULL DEFAULT 'Active',  -- Active | Archived
    tags         TEXT,                            -- comma-separated
    ado_id       INTEGER,                         -- ADO work_item_id if synced
    created_by   INTEGER REFERENCES p_users(user_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Releases ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS p_releases (
    release_id   SERIAL PRIMARY KEY,
    release_ref  TEXT UNIQUE NOT NULL,  -- REL-001
    title        TEXT NOT NULL,
    description  TEXT,
    target_date  DATE,
    owner_id     INTEGER REFERENCES p_users(user_id),
    status       TEXT NOT NULL DEFAULT 'Planning',
        -- Planning | In Progress | Released | On Hold | Archived
    iterations   TEXT,   -- JSON array: ["Iteration 2026 04-April", ...]
    ado_id       INTEGER,
    created_by   INTEGER REFERENCES p_users(user_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Features ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS p_features (
    feature_id          SERIAL PRIMARY KEY,
    feature_ref         TEXT UNIQUE NOT NULL,  -- F-001
    title               TEXT NOT NULL,
    description         TEXT,
    epic_id             INTEGER REFERENCES p_epics(epic_id),
    planned_release_id  INTEGER REFERENCES p_releases(release_id),
    actual_release_id   INTEGER REFERENCES p_releases(release_id),
    spill_over          BOOLEAN NOT NULL DEFAULT FALSE,
    iteration           TEXT,
    priority            INTEGER NOT NULL DEFAULT 2,  -- 1-4
    state               TEXT NOT NULL DEFAULT 'Backlog',
        -- Backlog | In Planning | In Design | In Development | In QA | Done
        -- | On Hold | Rejected
    assigned_to_id      INTEGER REFERENCES p_users(user_id),
    main_developer_id   INTEGER REFERENCES p_users(user_id),
    main_designer_id    INTEGER REFERENCES p_users(user_id),
    original_estimate   NUMERIC(10,2),
    area                TEXT,
    func                TEXT,   -- "function" is reserved in SQL
    tags                TEXT,
    ado_id              INTEGER,  -- linked ADO work_item_id (Enhancement)
    created_by          INTEGER REFERENCES p_users(user_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ
);

-- ── Bugs ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS p_bugs (
    bug_id              SERIAL PRIMARY KEY,
    bug_ref             TEXT UNIQUE NOT NULL,  -- B-001
    title               TEXT NOT NULL,
    bug_type            TEXT NOT NULL DEFAULT 'Bug',  -- Bug | Bug_UI | Bug_Text
    linked_feature_id   INTEGER REFERENCES p_features(feature_id),
        -- NULL = Bug Pool (standalone)
    priority            INTEGER NOT NULL DEFAULT 2,
    severity            TEXT,  -- Critical | High | Medium | Low
    state               TEXT NOT NULL DEFAULT 'New',
        -- New | Active | Resolved | Closed | Rejected
    assigned_to_id      INTEGER REFERENCES p_users(user_id),
    main_developer_id   INTEGER REFERENCES p_users(user_id),
    area                TEXT,
    func                TEXT,
    found_in_iteration  TEXT,
    found_in_release_id INTEGER REFERENCES p_releases(release_id),
    repro_steps         TEXT,
    ado_id              INTEGER,
    created_by          INTEGER REFERENCES p_users(user_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ
);

-- ── Audit Log ────────────────────────────────────────────────────────────────
-- Captures every state/field change on any platform entity.
-- Required for bug re-open history and spill-over tracking.
CREATE TABLE IF NOT EXISTS p_audit_log (
    log_id        SERIAL PRIMARY KEY,
    entity_type   TEXT NOT NULL,   -- 'epic' | 'release' | 'feature' | 'bug'
    entity_id     INTEGER NOT NULL,
    entity_ref    TEXT,            -- e.g. "F-042" — denormalised for easy reading
    field_changed TEXT NOT NULL,   -- e.g. "state", "planned_release_id"
    old_value     TEXT,
    new_value     TEXT,
    changed_by    INTEGER REFERENCES p_users(user_id),
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON p_audit_log (entity_type, entity_id);

-- ── Tasks ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS p_tasks (
    task_id           SERIAL PRIMARY KEY,
    task_ref          TEXT UNIQUE NOT NULL,       -- T-001
    title             TEXT NOT NULL,
    activity          TEXT NOT NULL DEFAULT 'Development',
    template_key      TEXT,                       -- which template created this (null = manual)
    parent_feature_id INTEGER REFERENCES p_features(feature_id) ON DELETE CASCADE,
    assigned_to_id    INTEGER REFERENCES p_users(user_id),
    state             TEXT NOT NULL DEFAULT 'To Do',
        -- To Do | In Progress | Done | Blocked
    priority          INTEGER NOT NULL DEFAULT 2,
    original_estimate NUMERIC(10,2),
    completed_work    NUMERIC(10,2) NOT NULL DEFAULT 0,
    remaining_work    NUMERIC(10,2),
    description       TEXT,
    dod               TEXT,          -- Definition of Done (pre-filled by template)
    tags              TEXT,
    ado_id            INTEGER,
    created_by        INTEGER REFERENCES p_users(user_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at         TIMESTAMPTZ
);

-- ── Iteration Capacity Configuration ────────────────────────────────────────
-- Per-person, per-iteration available hours. Local only — never synced to ADO.
-- Used by the Capacity Planning board to compute utilisation and fire alerts.
CREATE TABLE IF NOT EXISTS p_iteration_capacity (
    config_id          SERIAL PRIMARY KEY,
    person             TEXT NOT NULL,          -- display_name (matches ADO assigned_to)
    iteration          TEXT NOT NULL,          -- ADO iteration name (stripped)
    available_days     NUMERIC(5,1) NOT NULL DEFAULT 10,
    hours_per_day      NUMERIC(4,1) NOT NULL DEFAULT 8,
    leave_days         NUMERIC(5,1) NOT NULL DEFAULT 0,
    total_available_hours NUMERIC(8,2)
        GENERATED ALWAYS AS ((available_days - leave_days) * hours_per_day) STORED,
    notes              TEXT,
    created_by         INTEGER REFERENCES p_users(user_id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (person, iteration)
);

-- ── Planning Sign-off Gates ──────────────────────────────────────────────────
-- Stores explicit BA/PO manual sign-off state per ADO work item.
-- NOT derived from ADO state — pure local, manually toggled on the Planning board.
CREATE TABLE IF NOT EXISTS p_planning_gates (
    work_item_id  INTEGER PRIMARY KEY,
    written       BOOLEAN NOT NULL DEFAULT FALSE,
    ac_locked     BOOLEAN NOT NULL DEFAULT FALSE,
    estimated     BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by    TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Planning Sign-off Audit Log ───────────────────────────────────────────────
-- Immutable history: every gate toggle (Confirmed / Cleared) is appended here.
CREATE TABLE IF NOT EXISTS p_planning_log (
    log_id        SERIAL PRIMARY KEY,
    work_item_id  INTEGER NOT NULL,
    title         TEXT,
    gate          TEXT NOT NULL,        -- 'written' | 'ac' | 'est'
    action        TEXT NOT NULL,        -- 'Confirmed' | 'Cleared'
    performed_by  TEXT NOT NULL DEFAULT 'system',
    performed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ba            TEXT,
    dev_name      TEXT,
    month_key     TEXT,
    priority      TEXT,
    new_status    TEXT
);
CREATE INDEX IF NOT EXISTS idx_planning_log_item  ON p_planning_log (work_item_id);
CREATE INDEX IF NOT EXISTS idx_planning_log_month ON p_planning_log (month_key);

-- ── Indexes ──────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_features_epic       ON p_features (epic_id);
CREATE INDEX IF NOT EXISTS idx_features_release    ON p_features (planned_release_id);
CREATE INDEX IF NOT EXISTS idx_bugs_feature        ON p_bugs (linked_feature_id);
CREATE INDEX IF NOT EXISTS idx_bugs_release        ON p_bugs (found_in_release_id);
CREATE INDEX IF NOT EXISTS idx_iter_capacity_iter  ON p_iteration_capacity (iteration);
CREATE INDEX IF NOT EXISTS idx_iter_capacity_person ON p_iteration_capacity (person);
CREATE INDEX IF NOT EXISTS idx_tasks_feature        ON p_tasks (parent_feature_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee       ON p_tasks (assigned_to_id);
