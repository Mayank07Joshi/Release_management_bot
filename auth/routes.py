"""
Flask routes for login and logout.
Registered on app.server (the underlying Flask app).
"""
from flask import render_template_string, request, redirect, url_for, session
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from auth.models import User
from sqlalchemy import text
from data.loader import engine


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Release Analytics — Login</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #0d0d1a;
      font-family: 'Inter', system-ui, sans-serif;
      color: #e2e8f0;
    }
    .card {
      background: #13132b;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      padding: 48px 40px;
      width: 100%;
      max-width: 400px;
      box-shadow: 0 24px 64px rgba(0,0,0,0.5);
    }
    .logo {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 32px;
    }
    .logo-badge {
      width: 40px; height: 40px;
      background: linear-gradient(135deg, #6366f1, #818cf8);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 14px; color: white;
    }
    .logo-text { font-size: 16px; font-weight: 600; color: #e2e8f0; }
    .logo-sub  { font-size: 11px; color: #64748b; margin-top: 1px; }
    h2 { font-size: 22px; font-weight: 600; margin-bottom: 6px; }
    .subtitle { font-size: 13px; color: #64748b; margin-bottom: 28px; }
    label { display: block; font-size: 12px; font-weight: 500;
            color: #94a3b8; margin-bottom: 6px; }
    input {
      width: 100%; padding: 10px 14px;
      background: #1e1e38;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 8px; color: #e2e8f0; font-size: 14px;
      outline: none; margin-bottom: 18px;
      transition: border-color 0.2s;
    }
    input:focus { border-color: #6366f1; }
    .error {
      background: rgba(239,68,68,0.1);
      border: 1px solid rgba(239,68,68,0.3);
      color: #f87171; font-size: 13px;
      padding: 10px 14px; border-radius: 8px; margin-bottom: 18px;
    }
    button {
      width: 100%; padding: 11px;
      background: linear-gradient(135deg, #6366f1, #818cf8);
      border: none; border-radius: 8px;
      color: white; font-size: 14px; font-weight: 600;
      cursor: pointer; transition: opacity 0.2s;
    }
    button:hover { opacity: 0.9; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">
      <div class="logo-badge">RA</div>
      <div>
        <div class="logo-text">Release Analytics</div>
        <div class="logo-sub">ADO Dashboard</div>
      </div>
    </div>
    <h2>Welcome back</h2>
    <p class="subtitle">Sign in to your workspace</p>
    {% if error %}
    <div class="error">{{ error }}</div>
    {% endif %}
    <form method="POST" action="/login">
      <label for="username">Username</label>
      <input type="text" id="username" name="username"
             value="{{ username or '' }}" autocomplete="username" autofocus required>
      <label for="password">Password</label>
      <input type="password" id="password" name="password"
             autocomplete="current-password" required>
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>
"""


def register_auth_routes(server):
    """Register /login and /logout on the Flask server."""

    @server.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect("/")

        error    = None
        username = ""

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user, pw_hash = User.get_by_username(username)

            if user and pw_hash and check_password_hash(pw_hash, password):
                login_user(user, remember=True)
                # Record last login
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE p_users SET last_login = NOW() WHERE user_id = :id"),
                            {"id": user.id}
                        )
                except Exception:
                    pass
                next_url = request.args.get("next") or "/"
                return redirect(next_url)
            else:
                error = "Incorrect username or password."

        return render_template_string(LOGIN_HTML, error=error, username=username)

    @server.route("/logout")
    def logout():
        logout_user()
        return redirect("/login")
