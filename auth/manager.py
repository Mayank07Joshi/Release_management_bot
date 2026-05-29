"""
Initialise Flask-Login and register the user_loader.
Call setup_login_manager(server) from app.py before running.
"""
from flask_login import LoginManager
from auth.models import User

login_manager = LoginManager()


def setup_login_manager(server):
    """Attach Flask-Login to the Flask server and configure it."""
    login_manager.init_app(server)
    login_manager.login_view    = "/login"
    login_manager.login_message = "Please log in to access this page."

    @login_manager.user_loader
    def load_user(user_id):
        return User.get(int(user_id))

    @server.before_request
    def require_login():
        from flask import request, redirect, jsonify
        from flask_login import current_user
        public = {"/login", "/logout"}
        path   = request.path
        if path in public or path.startswith("/assets/") or path.startswith("/_reload-hash"):
            return None
        if not current_user.is_authenticated:
            if path.startswith("/_dash"):
                return jsonify({"error": "unauthenticated"}), 401
            return redirect("/login")

    return login_manager
