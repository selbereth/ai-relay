"""Small server for the watch app: pairs a watch with a login, then answers questions through the one LLM set on the Settings page."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_from_directory, session, url_for
from flask.sessions import SecureCookieSessionInterface

import providers

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
USERNAME = os.environ.get("LOGIN_USER", "me")
PASSWORD = os.environ.get("LOGIN_PASSWORD", "")
CODE_TTL = 600
TOKEN_MAX_IDLE = float(os.environ.get("TOKEN_MAX_IDLE_DAYS", "90")) * 86400  # a watch unused this long must pair again
WEB_POSTS_EXEMPT = {"/pair/start", "/pair/poll", "/ask"}  # the watch API: Bearer token or device secret, no cookies

os.umask(0o077)  # everything the server (and the Claude CLI) writes in /data is private to this user
os.makedirs(DATA, exist_ok=True)
try:
    os.chmod(DATA, 0o700)
except OSError:
    pass  # not our directory (bind mount owned by someone else): nothing we can tighten
app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=64 * 1024, SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_HTTPONLY=True)


class Sessions(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):  # Secure when the request came in over HTTPS (also behind a proxy / tunnel)
        return request.is_secure or request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https"


app.session_interface = Sessions()


def load_secret_key() -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(DATA, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    return open(path).read().strip()


app.secret_key = load_secret_key()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(os.path.join(DATA, "watch.db"))
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS pairing (
        code TEXT PRIMARY KEY, device_hash TEXT NOT NULL, created REAL NOT NULL, token_hash TEXT, token TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS devices (token_hash TEXT PRIMARY KEY, created REAL NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
        device TEXT, question TEXT NOT NULL, answer TEXT, error TEXT)""")
    for table, column, kind in (("pairing", "name", "TEXT"), ("devices", "name", "TEXT"), ("devices", "last_used", "REAL")):
        if column not in [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]:  # upgrade older databases
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    con.execute("UPDATE devices SET last_used = ? WHERE last_used IS NULL", (time.time(),))
    return con


try:
    db().close()
    for suffix in ("", "-journal", "-wal", "-shm"):  # databases made by older versions were world-readable
        if os.path.exists(os.path.join(DATA, "watch.db") + suffix):
            os.chmod(os.path.join(DATA, "watch.db") + suffix, 0o600)
except OSError:
    pass


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---- abuse limits (in memory, per process: the server runs one worker) ----

_hits: dict = {}


def too_many(bucket: str, limit: int, window: float, record: bool = True) -> bool:
    """True when `bucket` already has `limit` events in the last `window` seconds; otherwise records one."""
    now = time.time()
    recent = [t for t in _hits.get(bucket, []) if now - t < window]
    if len(recent) >= limit:
        _hits[bucket] = recent
        return True
    if record:
        recent.append(now)
    _hits[bucket] = recent
    if len(_hits) > 5000:  # forget idle buckets
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > 3600]:
            del _hits[k]
    return False


def client_ip() -> str:
    return request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
        or request.remote_addr or "?"


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


@app.context_processor
def inject_csrf():
    return {"csrf": csrf_token()}


@app.before_request
def csrf_check():
    """Every web form must carry the session's CSRF token (the watch API is exempt: it has no cookies)."""
    if request.method == "POST" and request.path not in WEB_POSTS_EXEMPT:
        sent = request.form.get("csrf", "")
        if not sent or not hmac.compare_digest(sent.encode(), session.get("csrf", "").encode()):
            abort(400, "Missing or wrong CSRF token. Reload the page and try again.")


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = ("default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                                               "script-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---- watch API ----

@app.post("/pair/start")
def pair_start():
    """Watch asks for a short code to show on screen; keeps `device_secret` private and polls with it."""
    if too_many(f"pair:{client_ip()}", 10, 60):
        return jsonify(error="too many requests"), 429
    name = str((request.get_json(silent=True) or {}).get("name") or "").strip()[:40]
    device_secret = secrets.token_urlsafe(24)
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    with db() as con:
        con.execute("DELETE FROM pairing WHERE created < ?", (time.time() - CODE_TTL,))
        if con.execute("SELECT COUNT(*) FROM pairing").fetchone()[0] >= 200:
            return jsonify(error="too many pending pairings"), 429
        con.execute("INSERT INTO pairing (code, device_hash, created, name) VALUES (?,?,?,?)",
                    (code, h(device_secret), time.time(), name))
    return jsonify(code=code, device_secret=device_secret, expires_in=CODE_TTL)


@app.post("/pair/poll")
def pair_poll():
    body = request.get_json(silent=True) or {}
    secret = body.get("device_secret", "")
    if not isinstance(secret, str) or too_many(f"poll:{client_ip()}", 120, 60):
        return jsonify(status="expired"), 429
    with db() as con:
        con.execute("DELETE FROM pairing WHERE created < ?", (time.time() - CODE_TTL,))  # also drops unclaimed tokens
        row = con.execute("SELECT * FROM pairing WHERE device_hash=?", (h(secret),)).fetchone()
        if not row or time.time() - row["created"] > CODE_TTL:
            return jsonify(status="expired"), 410
        if not row["token"]:
            return jsonify(status="pending")
        token = row["token"]
        con.execute("DELETE FROM pairing WHERE code=?", (row["code"],))  # token is handed out once
    return jsonify(status="approved", token=token)


def current_device():
    """The paired device making this request (its row), or None."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return None
    with db() as con:
        row = con.execute("SELECT * FROM devices WHERE token_hash=?", (h(token),)).fetchone()
        if row is None:
            return None
        now = time.time()
        if now - (row["last_used"] or row["created"]) > TOKEN_MAX_IDLE:
            con.execute("DELETE FROM devices WHERE token_hash=?", (row["token_hash"],))  # idle too long: pair again
            return None
        if now - (row["last_used"] or 0) > 3600:
            con.execute("UPDATE devices SET last_used=? WHERE token_hash=?", (now, row["token_hash"]))
        return row


def authed() -> bool:
    return current_device() is not None


def saving_messages() -> bool:
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='save_messages'").fetchone()
    return row is None or row["v"] == "1"  # on unless switched off


def save_message(device, question: str, answer: str = None, error: str = None) -> None:
    if saving_messages():
        with db() as con:
            con.execute("INSERT INTO messages (created, device, question, answer, error) VALUES (?,?,?,?,?)",
                        (time.time(), (device["name"] if device else None) or "Watch", question, answer, error))


def load_llm() -> dict:
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='llm'").fetchone()
    return json.loads(row["v"]) if row else dict(providers.DEFAULT)


@app.post("/ask")
def ask():
    device = current_device()
    if device is None:
        return jsonify(error="not paired"), 401
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify(error="empty question"), 400
    question = question[:2000]
    try:
        text = providers.answer(load_llm(), question)
    except Exception as e:  # noqa: BLE001 - shown on the watch as a short message
        save_message(device, question, error=str(e)[:200])
        return jsonify(error=str(e)[:200]), 502
    save_message(device, question, answer=text)
    return jsonify(answer=text)


# ---- web login to approve a watch ----

def logged_in() -> bool:
    return bool(PASSWORD) and session.get("user") == USERNAME


PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Relay</title>
<link rel=icon href="/icon.png"><link rel=apple-touch-icon href="/icon.png">
<body style="font:16px system-ui;max-width:24rem;margin:3rem auto;padding:0 1rem">
<img src="/icon.png" width=64 height=64 style="border-radius:14px"><h2>AI Relay</h2>{% if msg %}<p><b>{{ msg }}</b></p>{% endif %}
{% if not user %}<form method=post action="/login"><input type=hidden name=csrf value="{{ csrf }}">
<p><input name=username placeholder=username required autofocus></p>
<p><input name=password type=password placeholder=password required></p><button>Sign in</button></form>
{% else %}<form method=post action="/approve"><input type=hidden name=csrf value="{{ csrf }}"><p>Code shown on your watch:</p>
<p><input name=code maxlength=6 style="font-size:1.6rem;text-transform:uppercase;width:9rem" required autofocus></p>
<p><input name=name maxlength=40 placeholder="Name (optional)" style="width:14rem"></p>
<button>Pair watch</button></form>
<h3>Paired watches: {{ devices|length }}</h3>
{% for d in devices %}<form method=post action="/device/{{ d.id }}" style="margin:.4rem 0"><input type=hidden name=csrf value="{{ csrf }}">
<input name=name value="{{ d.name }}" maxlength=40 style="width:9rem">
<button name=action value=rename>Rename</button>
<button name=action value=remove onclick="return confirm('Remove this watch?')">Remove</button></form>{% endfor %}
{% if devices|length > 1 %}<form method=post action="/revoke"><input type=hidden name=csrf value="{{ csrf }}"><button>Unpair all</button></form>{% endif %}
<p><a href="/messages">Messages</a> &middot; <a href="/settings">Settings</a></p>
<form method=post action="/logout"><button>Sign out</button></form>{% endif %}
</body>"""

SETTINGS = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Relay settings</title>
<link rel=icon href="/icon.png"><link rel=apple-touch-icon href="/icon.png">
<body style="font:16px system-ui;max-width:28rem;margin:3rem auto;padding:0 1rem">
<p><a href="/">&larr; Back</a></p><h2>Settings</h2>{% if msg %}<p><b>{{ msg }}</b></p>{% endif %}
<form method=post action="/settings"><input type=hidden name=csrf value="{{ csrf }}">
<p>Which LLM answers your watch?<br><select name=type id=type style="width:100%">
{% for k, label in types %}<option value="{{ k }}"{% if k == cfg.type %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></p>
<p data-for="claude-cli anthropic openai">Model<br><input name=model value="{{ cfg.model or '' }}" style="width:100%" placeholder="{{ hint }}"></p>
<p data-for="openai">Server address (base URL)<br><input name=base_url value="{{ cfg.base_url or '' }}" style="width:100%" placeholder="http://192.168.1.50:11434/v1  (blank = OpenAI)"></p>
<p data-for="claude-cli anthropic openai"><span data-for="claude-cli">Claude Code token (run <code>claude setup-token</code>)</span><span data-for="anthropic openai">API key</span>{% if cfg.api_key %} (saved, leave blank to keep){% endif %}<br><input name=api_key type=password style="width:100%" autocomplete=off></p>
<p data-for="command">Command (question goes to stdin, answer read from stdout)<br><input name=command value="{{ cfg.command or '' }}" style="width:100%"></p>
<button>Save</button></form>
<h3>Messages</h3><form method=post action="/settings/messages"><input type=hidden name=csrf value="{{ csrf }}">
<label><input type=checkbox name=save value=1{% if saving %} checked{% endif %}> Save all questions and answers</label>
<button>Save</button></form><p><a href="/messages">View saved messages</a></p>
<script>const t=document.getElementById('type');function f(){document.querySelectorAll('[data-for]').forEach(e=>e.style.display=e.dataset.for.split(' ').includes(t.value)?'':'none')}t.onchange=f;f()</script>
</body>"""

MESSAGES = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Relay messages</title>
<link rel=icon href="/icon.png"><link rel=apple-touch-icon href="/icon.png">
<body style="font:16px system-ui;max-width:34rem;margin:3rem auto;padding:0 1rem">
<p><a href="/">&larr; Back</a></p><h2>Messages</h2>
{% if not saving %}<p><i>Saving is off (Settings), so new messages are not kept.</i></p>{% endif %}
{% for r in rows %}<div style="border-top:1px solid #8884;padding:.6rem 0">
<small>{{ when(r.created) }} &middot; {{ r.device }}</small>
<form method=post action="/messages/delete" style="float:right"><input type=hidden name=csrf value="{{ csrf }}"><input type=hidden name=id value="{{ r.id }}"><button>Delete</button></form>
<div><b>{{ r.question }}</b></div><div style="white-space:pre-wrap">{% if r.error %}<i>Error: {{ r.error }}</i>{% else %}{{ r.answer }}{% endif %}</div></div>
{% else %}<p>No messages yet.</p>{% endfor %}
{% if rows %}<form method=post action="/messages/delete" onsubmit="return confirm('Delete all messages?')"><input type=hidden name=csrf value="{{ csrf }}"><button>Delete all messages</button></form>{% endif %}
</body>"""

TYPE_LABELS = [("claude-cli", "Claude (Claude Code login, default)"), ("anthropic", "Claude API (API key)"),
               ("openai", "OpenAI-compatible (OpenAI, Ollama, LM Studio, vLLM...)"), ("command", "Other command-line agent")]


@app.route("/icon.png")
def icon():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "icon.png", max_age=86400)


@app.route("/")
def index():
    with db() as con:
        devices = [dict(r) for r in con.execute("SELECT rowid AS id, name FROM devices ORDER BY created")]
    return render_template_string(PAGE, user=logged_in(), msg=request.args.get("msg"), devices=devices)


@app.post("/login")
def login():
    # 5 wrong passwords per address per 15 minutes, 20 across all addresses: nothing sleeps, so a flood cannot stall the server
    if too_many(f"login:{client_ip()}", 5, 900, record=False) or too_many("login:all", 20, 900, record=False):
        return redirect(url_for("index", msg="Too many failed logins. Try again in 15 minutes."))
    ok = bool(PASSWORD) and hmac.compare_digest(request.form.get("username", "").encode(), USERNAME.encode()) \
        and hmac.compare_digest(request.form.get("password", "").encode(), PASSWORD.encode())
    if not ok:
        too_many(f"login:{client_ip()}", 5, 900)
        too_many("login:all", 20, 900)
        return redirect(url_for("index", msg="Wrong username or password"))
    session.clear()
    session["user"] = USERNAME
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index", msg="Signed out"))


@app.post("/approve")
def approve():
    if not logged_in():
        return redirect(url_for("index"))
    code = request.form.get("code", "").strip().upper()
    token = secrets.token_urlsafe(32)
    with db() as con:
        con.execute("DELETE FROM pairing WHERE created < ?", (time.time() - CODE_TTL,))
        row = con.execute("SELECT * FROM pairing WHERE code=? AND token IS NULL AND created > ?",
                          (code, time.time() - CODE_TTL)).fetchone()
        if not row:
            return redirect(url_for("index", msg="Code not found or expired"))
        con.execute("UPDATE pairing SET token=? WHERE code=?", (token, code))
        name = request.form.get("name", "").strip()[:40] or row["name"] or "Watch"
        con.execute("INSERT INTO devices (token_hash, created, name, last_used) VALUES (?,?,?,?)",
                    (h(token), time.time(), name, time.time()))
    return redirect(url_for("index", msg="Paired. Your watch will finish in a few seconds."))


@app.get("/settings")
def settings():
    if not logged_in():
        return redirect(url_for("index"))
    return render_template_string(SETTINGS, cfg=load_llm(), types=TYPE_LABELS, msg=request.args.get("msg"), saving=saving_messages(),
                                  hint="blank = Claude Haiku")


@app.post("/settings")
def save_settings():
    if not logged_in():
        return redirect(url_for("index"))
    f = request.form
    kind = f.get("type", "")
    if kind not in providers.TYPES:
        return redirect(url_for("settings", msg="Pick an LLM"))
    old = load_llm()
    cfg = {"type": kind, "model": f.get("model", "").strip(), "base_url": f.get("base_url", "").strip(),
           "command": f.get("command", "").strip(),
           # a blank key box keeps the saved key (the page never shows it)
           "api_key": f.get("api_key", "").strip() or (old.get("api_key", "") if old.get("type") == kind else "")}
    if kind == "openai" and not cfg["model"]:
        return redirect(url_for("settings", msg="OpenAI-compatible needs a model name"))
    if kind == "command" and not cfg["command"]:
        return redirect(url_for("settings", msg="Enter the command"))
    with db() as con:
        con.execute("INSERT OR REPLACE INTO settings (k, v) VALUES ('llm', ?)", (json.dumps(cfg),))
    return redirect(url_for("settings", msg="Saved"))


@app.post("/device/<int:rowid>")
def device_action(rowid: int):
    if not logged_in():
        return redirect(url_for("index"))
    with db() as con:
        if request.form.get("action") == "remove":
            con.execute("DELETE FROM devices WHERE rowid=?", (rowid,))
            return redirect(url_for("index", msg="Watch removed"))
        name = request.form.get("name", "").strip()[:40]
        if name:
            con.execute("UPDATE devices SET name=? WHERE rowid=?", (name, rowid))
    return redirect(url_for("index", msg="Renamed"))


@app.post("/settings/messages")
def save_messages_setting():
    if logged_in():
        with db() as con:
            con.execute("INSERT OR REPLACE INTO settings (k, v) VALUES ('save_messages', ?)",
                        ("1" if request.form.get("save") else "0",))
    return redirect(url_for("settings", msg="Saved"))


@app.get("/messages")
def messages():
    if not logged_in():
        return redirect(url_for("index"))
    with db() as con:
        rows = con.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 300").fetchall()
    return render_template_string(MESSAGES, rows=rows, saving=saving_messages(), msg=request.args.get("msg"),
                                  when=lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)))


@app.post("/messages/delete")
def delete_messages():
    if logged_in():
        with db() as con:
            if request.form.get("id"):
                con.execute("DELETE FROM messages WHERE id=?", (request.form["id"],))
            else:
                con.execute("DELETE FROM messages")
    return redirect(url_for("messages"))


@app.post("/revoke")
def revoke():
    if logged_in():
        with db() as con:
            con.execute("DELETE FROM devices")
    return redirect(url_for("index", msg="All watches unpaired"))


@app.get("/health")
def health():
    return "ok"
