"""
Flask-Login User model.
Loads user records from p_users table.
"""
from flask_login import UserMixin
from sqlalchemy import text
from data.loader import engine


class User(UserMixin):
    def __init__(self, user_id, username, email, display_name, role, team, is_active):
        self.id           = user_id       # Flask-Login requires self.id
        self.username     = username
        self.email        = email
        self.display_name = display_name
        self.role         = role
        self.team         = team
        self._is_active   = is_active

    @property
    def is_active(self):
        return self._is_active

    # ── Permission helpers ─────────────────────────────────────────────────────
    def can(self, action: str) -> bool:
        """
        Check if this user can perform an action.
        action examples: 'create_epic', 'create_release', 'create_feature',
                         'create_bug', 'edit_any', 'manage_users'
        """
        return action in ROLE_PERMISSIONS.get(self.role, set())

    @staticmethod
    def get(user_id: int):
        """Load a user by ID — called by Flask-Login's user_loader."""
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT * FROM p_users WHERE user_id = :id AND is_active = TRUE"),
                    {"id": user_id}
                ).fetchone()
            if row:
                return User(
                    user_id=row.user_id,
                    username=row.username,
                    email=row.email,
                    display_name=row.display_name,
                    role=row.role,
                    team=row.team,
                    is_active=row.is_active,
                )
        except Exception as e:
            print(f"[auth] user_loader error: {e}")
        return None

    @staticmethod
    def get_by_username(username: str):
        """Load a user by username for login."""
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT * FROM p_users WHERE username = :u AND is_active = TRUE"),
                    {"u": username}
                ).fetchone()
            if row:
                return User(
                    user_id=row.user_id,
                    username=row.username,
                    email=row.email,
                    display_name=row.display_name,
                    role=row.role,
                    team=row.team,
                    is_active=row.is_active,
                ), row.password_hash
        except Exception as e:
            print(f"[auth] get_by_username error: {e}")
        return None, None


# ── Role → Permission mapping ─────────────────────────────────────────────────
# Extend this dict as new actions are added — no code changes needed elsewhere.
ROLE_PERMISSIONS = {
    "admin": {
        "create_epic", "edit_epic", "archive_epic",
        "create_release", "edit_release",
        "create_feature", "edit_feature", "edit_any_feature",
        "create_bug", "edit_bug", "edit_any_bug",
        "manage_users", "view_all",
    },
    "pm": {
        "create_epic", "edit_epic",
        "create_release", "edit_release",
        "create_feature", "edit_feature", "edit_any_feature",
        "create_bug", "edit_bug", "edit_any_bug",
        "view_all",
    },
    "developer": {
        "create_feature", "edit_feature",
        "create_bug", "edit_bug",
        "view_all",
    },
    "qa": {
        "create_bug", "edit_bug",
        "view_all",
    },
    "designer": {
        "create_feature", "edit_feature",
        "create_bug", "edit_bug",
        "view_all",
    },
    "viewer": {
        "view_all",
    },
}
