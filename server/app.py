"""Small server for the watch app: pairs a watch with a login, then answers questions through the one LLM set on the Settings page."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, session, url_for

import providers

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
USERNAME = os.environ.get("LOGIN_USER", "me")
PASSWORD = os.environ.get("LOGIN_PASSWORD", "")
CODE_TTL = 600

os.makedirs(DATA, exist_ok=True)
app = Flask(__name__)


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
    return con


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---- watch API ----

@app.post("/pair/start")
def pair_start():
    """Watch asks for a short code to show on screen; keeps `device_secret` private and polls with it."""
    device_secret = secrets.token_urlsafe(24)
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    with db() as con:
        con.execute("DELETE FROM pairing WHERE created < ?", (time.time() - CODE_TTL,))
        con.execute("INSERT INTO pairing (code, device_hash, created) VALUES (?,?,?)", (code, h(device_secret), time.time()))
    return jsonify(code=code, device_secret=device_secret, expires_in=CODE_TTL)


@app.post("/pair/poll")
def pair_poll():
    body = request.get_json(silent=True) or {}
    secret = body.get("device_secret", "")
    with db() as con:
        row = con.execute("SELECT * FROM pairing WHERE device_hash=?", (h(secret),)).fetchone()
        if not row or time.time() - row["created"] > CODE_TTL:
            return jsonify(status="expired"), 410
        if not row["token"]:
            return jsonify(status="pending")
        token = row["token"]
        con.execute("DELETE FROM pairing WHERE code=?", (row["code"],))  # token is handed out once
    return jsonify(status="approved", token=token)


def authed() -> bool:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return False
    with db() as con:
        return con.execute("SELECT 1 FROM devices WHERE token_hash=?", (h(token),)).fetchone() is not None


def load_llm() -> dict:
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='llm'").fetchone()
    return json.loads(row["v"]) if row else dict(providers.DEFAULT)


@app.post("/ask")
def ask():
    if not authed():
        return jsonify(error="not paired"), 401
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify(error="empty question"), 400
    try:
        return jsonify(answer=providers.answer(load_llm(), question[:2000]))
    except Exception as e:  # noqa: BLE001 - shown on the watch as a short message
        return jsonify(error=str(e)[:200]), 502


# ---- web login to approve a watch ----

def logged_in() -> bool:
    return bool(PASSWORD) and session.get("user") == USERNAME


PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Relay</title>
<link rel=icon href="/icon.png"><link rel=apple-touch-icon href="/icon.png">
<body style="font:16px system-ui;max-width:24rem;margin:3rem auto;padding:0 1rem">
<img src="/icon.png" width=64 height=64 style="border-radius:14px"><h2>AI Relay</h2>{% if msg %}<p><b>{{ msg }}</b></p>{% endif %}
{% if not user %}<form method=post action="/login">
<p><input name=username placeholder=username required autofocus></p>
<p><input name=password type=password placeholder=password required></p><button>Sign in</button></form>
{% else %}<form method=post action="/approve"><p>Code shown on your watch:</p>
<p><input name=code maxlength=6 style="font-size:1.6rem;text-transform:uppercase;width:9rem" required autofocus></p>
<button>Pair watch</button></form>
<h3>Paired watches: {{ n }}</h3><form method=post action="/revoke"><button>Unpair all</button></form>
<p><a href="/settings">Settings: which LLM answers</a></p>{% endif %}
</body>"""

SETTINGS = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Relay settings</title>
<link rel=icon href="/icon.png"><link rel=apple-touch-icon href="/icon.png">
<body style="font:16px system-ui;max-width:28rem;margin:3rem auto;padding:0 1rem">
<p><a href="/">&larr; Back</a></p><h2>Settings</h2>{% if msg %}<p><b>{{ msg }}</b></p>{% endif %}
<form method=post action="/settings">
<p>Which LLM answers your watch?<br><select name=type id=type style="width:100%">
{% for k, label in types %}<option value="{{ k }}"{% if k == cfg.type %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></p>
<p data-for="claude-cli anthropic openai">Model<br><input name=model value="{{ cfg.model or '' }}" style="width:100%" placeholder="{{ hint }}"></p>
<p data-for="openai">Server address (base URL)<br><input name=base_url value="{{ cfg.base_url or '' }}" style="width:100%" placeholder="http://192.168.1.50:11434/v1  (blank = OpenAI)"></p>
<p data-for="claude-cli anthropic openai"><span data-for="claude-cli">Claude Code token (run <code>claude setup-token</code>)</span><span data-for="anthropic openai">API key</span>{% if cfg.api_key %} (saved, leave blank to keep){% endif %}<br><input name=api_key type=password style="width:100%" autocomplete=off></p>
<p data-for="command">Command (question goes to stdin, answer read from stdout)<br><input name=command value="{{ cfg.command or '' }}" style="width:100%"></p>
<button>Save</button></form>
<script>const t=document.getElementById('type');function f(){document.querySelectorAll('[data-for]').forEach(e=>e.style.display=e.dataset.for.split(' ').includes(t.value)?'':'none')}t.onchange=f;f()</script>
</body>"""

TYPE_LABELS = [("claude-cli", "Claude (Claude Code login, default)"), ("anthropic", "Claude API (API key)"),
               ("openai", "OpenAI-compatible (OpenAI, Ollama, LM Studio, vLLM...)"), ("command", "Other command-line agent")]


@app.route("/icon.png")
def icon():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "icon.png", max_age=86400)


@app.route("/")
def index():
    with db() as con:
        n = con.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    return render_template_string(PAGE, user=logged_in(), msg=request.args.get("msg"), n=n)


@app.post("/login")
def login():
    ok = (PASSWORD and hmac.compare_digest(request.form.get("username", ""), USERNAME)
          and hmac.compare_digest(request.form.get("password", ""), PASSWORD))
    if not ok:
        time.sleep(1)
        return redirect(url_for("index", msg="Wrong username or password"))
    session.clear()
    session["user"] = USERNAME
    return redirect(url_for("index"))


@app.post("/approve")
def approve():
    if not logged_in():
        return redirect(url_for("index"))
    code = request.form.get("code", "").strip().upper()
    token = secrets.token_urlsafe(32)
    with db() as con:
        row = con.execute("SELECT * FROM pairing WHERE code=? AND token IS NULL AND created > ?",
                          (code, time.time() - CODE_TTL)).fetchone()
        if not row:
            return redirect(url_for("index", msg="Code not found or expired"))
        con.execute("UPDATE pairing SET token=? WHERE code=?", (token, code))
        con.execute("INSERT INTO devices (token_hash, created) VALUES (?,?)", (h(token), time.time()))
    return redirect(url_for("index", msg="Paired. Your watch will finish in a few seconds."))


@app.get("/settings")
def settings():
    if not logged_in():
        return redirect(url_for("index"))
    return render_template_string(SETTINGS, cfg=load_llm(), types=TYPE_LABELS, msg=request.args.get("msg"),
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


@app.post("/revoke")
def revoke():
    if logged_in():
        with db() as con:
            con.execute("DELETE FROM devices")
    return redirect(url_for("index", msg="All watches unpaired"))


@app.get("/health")
def health():
    return "ok"
