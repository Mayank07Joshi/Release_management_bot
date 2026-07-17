# Auth Layer

Flask-Login wraps the whole Dash app. There is no separate identity provider,
OAuth flow, or SSO integration — accounts live in one Postgres table
(`p_users`, defined in `db/schema.sql`, see `db.md` §2) and are checked with
`werkzeug.security` password hashing. Three files make up the layer:

| File | Role |
|---|---|
| `auth/manager.py` | Flask-Login wiring: `LoginManager`, `user_loader`, the global `before_request` access gate |
| `auth/models.py` | `User` model (loads from `p_users`) + `ROLE_PERMISSIONS` dict |
| `auth/routes.py` | `/login`, `/logout`, and two download routes that also check auth manually |

Six roles exist as plain strings on `p_users.role`: `admin`, `pm`, `developer`,
`qa`, `designer`, `viewer` (see `db/schema.sql:29`'s comment listing them).

## 1. Overview

`app.py:267-269` wires everything together at import time:

```python
app.server.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod-!@#$%")
setup_login_manager(app.server)
register_auth_routes(app.server)
```

`setup_login_manager()` (`auth/manager.py:11-34`) attaches Flask-Login to the
Flask server underlying the Dash app, sets `login_view = "/login"`
(`manager.py:14`), and registers the `user_loader` (`manager.py:17-19`) that
Flask-Login calls on every request to rehydrate a `User` from the session
cookie's user-id via `User.get(int(user_id))`. `register_auth_routes()`
(`auth/routes.py:114`) then adds `/login`, `/logout`, `/download-report`, and
`/download-generated` directly on `app.server` — these are plain Flask routes,
not Dash pages, so they render server-side HTML/files rather than going
through `dash.register_page`.

## 2. Login flow

`GET /login` and `POST /login` are both handled by one view function,
`login()` (`auth/routes.py:117-147`):

- If already authenticated, it just redirects to `/` (`routes.py:119-120`) —
  visiting `/login` while logged in doesn't show the form.
- On `POST`, it reads `username`/`password` from the form (`routes.py:126-127`),
  looks up the user with `User.get_by_username(username)`
  (`auth/models.py:56-77`), which returns a `(User, password_hash)` tuple (not
  just a `User` — `get()` and `get_by_username()` have different return
  shapes, see §7).
- Credentials are verified with `check_password_hash(pw_hash, password)`
  (`routes.py:131`), the stdlib/werkzeug hash-compare — no custom hashing code.
- On success, `login_user(user, remember=True)` (`routes.py:132`) always sets
  a persistent "remember me" cookie; there is no non-remembered login option
  and no UI checkbox for it.
- `last_login` is updated (`routes.py:134-141`) in a `try/except: pass` — if
  that `UPDATE` fails for any reason, the login still succeeds silently with
  no log line.
- Redirect target comes from `request.args.get("next") or "/"`
  (`routes.py:142`) — whatever `next` was on the `/login?next=...` URL that
  the `before_request` gate (§3) redirected the user to. This value is not
  validated against being an external URL before being passed to
  `redirect()` (see §7).
- On failure, `error = "Incorrect username or password."` is set and the same
  `LOGIN_HTML` template (`routes.py:13-111`, inline `render_template_string`,
  not a Jinja file) is re-rendered with the entered `username` prefilled.

`GET /logout` (`routes.py:149-152`) calls `logout_user()` and redirects to
`/login` unconditionally — no confirmation step, and it's exempted from the
auth gate itself so it always works even mid-session-expiry.

## 3. Access control

The actual gate is `require_login()`, a `before_request` hook registered
inside `setup_login_manager()` (`auth/manager.py:21-33`), so it runs before
**every** request to `app.server` — Dash's own callback/asset requests
included:

```python
public = {"/login", "/logout"}
path   = request.path
if path in public or path.startswith("/assets/") or path.startswith("/_reload-hash"):
    return None
if not current_user.is_authenticated:
    if path.startswith("/_dash"):
        return jsonify({"error": "unauthenticated"}), 401
    return redirect("/login")
```

Three path shapes are exempt from auth entirely: exact `/login` and
`/logout`, anything under `/assets/` (static JS/CSS Dash serves), and
`/_reload-hash` (Dash's dev-server hot-reload polling endpoint). Everything
else — including every dashboard route in `pages_dash/` and Dash's own
`/_dash-*` callback/update endpoints — requires `current_user.is_authenticated`.

The branch at `manager.py:30-32` is what makes the app usable as a
single-page app once logged out mid-session: a normal page navigation
(`GET /overview`, etc.) gets a `302` to `/login` (browser follows it, user
sees the login form), but an in-page Dash callback request (`POST
/_dash-update-component`, always under `/_dash`) gets a `401` JSON body
instead of a redirect — redirecting an XHR call would just hand the browser
an HTML login page as if it were callback JSON, which Dash's client-side
code can't parse. Note this distinction is made purely on the `/_dash` path
prefix, not on `Accept`/`X-Requested-With` headers.

`/download-report` and `/download-generated` (`routes.py:154-198`) also
contain their own `if not current_user.is_authenticated: return
redirect("/login")` checks (`routes.py:156-157`, `175-176`) — these are
redundant with the `before_request` gate, which already blocks unauthenticated
requests to those paths before the view function ever runs (see §7).

## 4. Roles & permissions

`ROLE_PERMISSIONS` (`auth/models.py:82-114`) is a plain `dict[str, set[str]]`
mapping each role to the action strings it's allowed to perform:

| Role | Permissions |
|---|---|
| `admin` | `create_epic`, `edit_epic`, `archive_epic`, `create_release`, `edit_release`, `create_feature`, `edit_feature`, `edit_any_feature`, `create_bug`, `edit_bug`, `edit_any_bug`, `manage_users`, `view_all` — everything |
| `pm` | Same as admin minus `archive_epic` and `manage_users` |
| `developer` | `create_feature`, `edit_feature`, `create_bug`, `edit_bug`, `view_all` — no epic/release actions |
| `qa` | `create_bug`, `edit_bug`, `view_all` only |
| `designer` | Same set as `developer` (`create_feature`, `edit_feature`, `create_bug`, `edit_bug`, `view_all`) |
| `viewer` | `view_all` only — read-only |

`User.can(action: str) -> bool` (`models.py:25-31`) is the single check point:
`action in ROLE_PERMISSIONS.get(self.role, set())`. An unrecognized role
(e.g. a typo in `p_users.role`, or a role added to the DB but not to this
dict) silently resolves to the empty set — `can()` returns `False` for
everything rather than raising, so a misconfigured role fails closed but with
no visible error.

This is an **additive dict pattern**, called out explicitly in both the
comment above the dict (`models.py:81`, "Extend this dict as new actions are
added — no code changes needed elsewhere") and `master.md` §6's conventions
list: new permission checks should be added as a new key/action in
`ROLE_PERMISSIONS`, not as a scattered `if current_user.role == "admin"` (or
similar) check inline in page code. Grep for `current_user.role ==` before
adding a new role check to confirm whether existing page code already
violates this — this doc does not assert page-by-page compliance.

## 5. Session security

`SECRET_KEY` (`app.py:267`) is read from the environment with a hardcoded
fallback:

```python
app.server.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod-!@#$%")
```

Checked `.env` directly (key names only, values not inspected): it defines
`AZURE_DEVOPS_PAT`, `DASH_DEBUG`, `DB_PASSWORD`, `ORGANIZATION_URL`, and
`PROJECT_NAME` — **no `SECRET_KEY` entry**. So in the current environment
this fallback is not a theoretical edge case, it's the value actually in use:
every session cookie (login session and the `remember_token` Flask-Login
sets) is being signed with the hardcoded string
`"dev-secret-change-in-prod-!@#$%"`. `.env` itself is gitignored
(`.gitignore:2-3`, `.env` and `*.env`), so this isn't leaking via git — but
anyone with read access to `app.py` has the fallback secret regardless of
`.env`, which defeats the purpose of it being a secret once a real
`SECRET_KEY` still isn't set.

Debug mode and host binding are controlled by `app.py`'s `if __name__ ==
"__main__":` block (`app.py:533-617`), specifically:

```python
if os.environ.get("PRODUCTION", "false").lower() == "true":
    serve(app.server, host="0.0.0.0", port=8050, threads=8)   # Waitress
else:
    app.run(host="0.0.0.0", port=8050, debug=True)            # Flask dev server
```

`PRODUCTION` is read fresh here and is **not** one of the five keys present
in `.env` (see above) — so unless it's exported some other way at process
start, the default branch runs: Flask's own dev server, `debug=True` (Werkzeug
debugger + auto-reload active), bound to `0.0.0.0` either way regardless of
which branch is taken. `DASH_DEBUG`, despite being defined in `.env`, is not
read anywhere in the codebase (confirmed by a full-repo search) — it has no
effect on this or any other debug switch; it's a dead/unused variable.

## 6. Bootstrap

The first (and, per current DB state, only clearly-documented) admin account
is created by running `python db/init_platform.py` once, by hand
(`db/init_platform.py:1-3`, `db.md` §5). `run()` (`init_platform.py:23-62`)
executes `schema.sql` statement-by-statement, then seeds a single row into
`p_users`:

```python
ADMIN_USER = {
    "username":     "mayank",
    "email":        "mayank.joshi@expenseondemand.com",
    "display_name": "Mayank Joshi",
    "password":     "admin123",   # change after first login
    "role":         "admin",
    "team":         "QA",
}
```

The credential really is hardcoded exactly as shown (`init_platform.py:14-21`).
The password is hashed with `generate_password_hash()`
(`init_platform.py:55`) before being stored — it is not stored in plaintext —
but the plaintext is printed to stdout on first creation
(`init_platform.py:60`, `Default password: {password}  (change this!)`), and
the insert is skip-if-exists (`init_platform.py:38-44`): if this script is
ever re-run against a database that doesn't already have a `mayank` row, it
recreates `mayank`/`admin123` as a standing admin credential with no
forced rotation. There's no code path that forces a password change on first
login.

## 7. Known issues / quirks

- **`SECRET_KEY` is not set in `.env` today**, confirmed by reading the key
  names in the current file — the app is running on the hardcoded fallback
  `"dev-secret-change-in-prod-!@#$%"` (`app.py:267`). This is also called out
  in `master.md` §7; this doc adds the confirmation that it's not merely a
  theoretical fallback but the value actually in effect right now.
- **No CSRF protection on `POST /login`** — no `flask-wtf`/`Flask-SeaSurf`
  or any CSRF token is present anywhere in the repo (checked: no import of
  `flask_wtf`, no `csrf` token field in `LOGIN_HTML`,
  `auth/routes.py:99-107`). The form posts directly with no hidden token.
- **No login rate-limiting or lockout** — `login()` (`routes.py:117-147`)
  has no attempt counter, no delay, no CAPTCHA, and no dependency on
  `flask-limiter` or similar exists in the repo. Nothing prevents unlimited
  password-guessing against `/login`.
- **`debug=True` is the default run mode**, not an opt-in — `PRODUCTION` is
  absent from `.env`, so `os.environ.get("PRODUCTION", "false")` falls
  through to the Flask dev server with the Werkzeug debugger enabled
  (`app.py:613-617`). Combined with binding to `0.0.0.0` in *both* branches,
  this means the interactive Werkzeug debugger (which allows arbitrary code
  execution from the browser if reached) is exposed on every network
  interface by default. Flagged from the app.py side in `master.md` §7; this
  is the detail behind that line.
- **`DASH_DEBUG` in `.env` is unused** — defined but never read anywhere in
  the codebase (verified by a full-repo search). Whoever set it likely
  expected it to control Flask's `debug=` flag; it doesn't. `PRODUCTION` is
  the only variable that actually matters, and it's a `PRODUCTION=true`
  opt-in for the Waitress branch, not a debug opt-out.
- **Hardcoded, printed-to-stdout default admin credential**
  (`mayank`/`admin123`, `db/init_platform.py:14-21`, printed at line 60),
  skip-if-exists so it never rotates on rerun. Same issue as documented in
  `db.md` §5/§7 — noted here because it's the actual bootstrap mechanism for
  the *only* account that can log in before any other user is created
  through whatever admin-user-management UI exists (this doc did not audit
  whether one currently does).
- **`next` redirect parameter is not validated** (`routes.py:142`,
  `next_url = request.args.get("next") or "/"` then `redirect(next_url)`) —
  it's taken straight from the query string with no check that it's a
  same-site relative path. Framed the way `before_request` uses it
  (`redirect("/login")` with no `next` appended at all — see `manager.py:32`),
  the app itself never sends a request through `/login?next=<external-url>`,
  but nothing stops a crafted link from doing so and using this app as an
  open-redirect step in a phishing chain.
- **Redundant auth checks on the download routes** — `/download-report` and
  `/download-generated` (`routes.py:154-198`) each re-check
  `current_user.is_authenticated` inline, but the `before_request` gate in
  `manager.py:21-33` already blocks unauthenticated requests to any path
  outside `public`/`/assets/`/`/_reload-hash` before these view functions
  run. Not a bug, just dead defensive code — worth knowing so it isn't
  mistaken for the actual enforcement point when auditing this path.
- **`User.get()` and `User.get_by_username()` have different return
  shapes** (`models.py:33-54` returns a bare `User` or `None`;
  `models.py:56-77` returns a `(User, password_hash)` tuple or `(None,
  None)`) — easy to call the wrong one expecting the other's shape when
  extending this module.
- **Inactive users (`is_active = FALSE`) are invisible, not just blocked** —
  both `User.get()` and `get_by_username()` filter on `is_active = TRUE` in
  their `WHERE` clause (`models.py:39`, `models.py:62`), so a deactivated
  account fails login with the generic "Incorrect username or password"
  message rather than a "this account is disabled" message — indistinguishable
  from a wrong password by design or by accident, not documented either way.
