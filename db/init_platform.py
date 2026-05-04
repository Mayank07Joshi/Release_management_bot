"""
Run once to create all platform tables and seed the admin user.
Usage: python db/init_platform.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from werkzeug.security import generate_password_hash
from data.loader import engine
from sqlalchemy import text

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

ADMIN_USER = {
    "username":     "mayank",
    "email":        "mayank.joshi@expenseondemand.com",
    "display_name": "Mayank Joshi",
    "password":     "admin123",   # change after first login
    "role":         "admin",
    "team":         "QA",
}

def run():
    print("Creating platform tables...")
    with open(SCHEMA_PATH, "r") as f:
        sql = f.read()

    with engine.begin() as conn:
        # Execute each statement individually (psycopg2 doesn't handle multi-statement well)
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
    print("  Tables created.")

    print("Seeding admin user...")
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT user_id FROM p_users WHERE username = :u"),
            {"u": ADMIN_USER["username"]}
        ).fetchone()

        if existing:
            print(f"  Admin user '{ADMIN_USER['username']}' already exists — skipping.")
        else:
            conn.execute(text("""
                INSERT INTO p_users
                    (username, email, display_name, password_hash, role, team)
                VALUES
                    (:username, :email, :display_name, :password_hash, :role, :team)
            """), {
                "username":      ADMIN_USER["username"],
                "email":         ADMIN_USER["email"],
                "display_name":  ADMIN_USER["display_name"],
                "password_hash": generate_password_hash(ADMIN_USER["password"]),
                "role":          ADMIN_USER["role"],
                "team":          ADMIN_USER["team"],
            })
            print(f"  Admin user '{ADMIN_USER['username']}' created.")
            print(f"  Default password: {ADMIN_USER['password']}  (change this!)")

    print("\nPlatform DB initialised successfully.")

if __name__ == "__main__":
    run()
