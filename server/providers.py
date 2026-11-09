"""Where the answers come from. The watch only sends a question; the server picks which LLM answers it.

Configure with a JSON file (PROVIDERS_FILE, default <DATA_DIR>/providers.json):

    {
      "default": "claude",
      "fallback": ["local"],
      "providers": {
        "claude":  {"type": "claude-cli"},
        "api":     {"type": "anthropic", "model": "claude-haiku-5-5"},
        "gpt":     {"type": "openai", "model": "gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY"},
        "local":   {"type": "openai", "base_url": "http://ollama:11434/v1", "model": "llama3.2"},
        "other":   {"type": "command", "command": ["codex", "exec", "--skip-git-repo-check", "-"]}
      }
    }

`default` answers; if it fails, each name in `fallback` is tried in order. With no file there is one provider, the
Claude Code CLI on Haiku (what the server always did). `LLM_PROVIDER=<name>` picks a different default at start-up.

Types:
  claude-cli  the Claude Code CLI (`claude -p`), uses CLAUDE_CODE_OAUTH_TOKEN or a local login. model: default Haiku.
  anthropic   the Claude API (Anthropic SDK). Needs ANTHROPIC_API_KEY (or "api_key_env").
  openai      anything that speaks OpenAI chat completions: OpenAI, Ollama, LM Studio, vLLM, OpenRouter, Groq, Gemini's
              OpenAI-compatible endpoint. "base_url" (default https://api.openai.com/v1), "model", "api_key_env".
  command     any other agent CLI: "command" is the argv; the question goes to stdin, the answer is stdout.
"""
import json
import os
import subprocess
import urllib.error
import urllib.request

SYSTEM = ("You answer on a tiny smartwatch screen. Reply in plain text, under 60 words, no markdown, "
          "no lists unless asked. If a question needs more than that, give the short answer first.")
TIMEOUT = 90
DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"  # small and fast: the watch cannot pick a model


class ProviderError(RuntimeError):
    pass


def _key(cfg: dict, default_env: str) -> str:
    env = cfg.get("api_key_env", default_env)
    key = os.environ.get(env, "")
    if not key and cfg.get("type") != "openai":
        raise ProviderError(f"{env} is not set")
    return key  # an OpenAI-compatible local server may need no key


def claude_cli(cfg: dict, question: str) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", cfg.get("model", DEFAULT_CLAUDE_MODEL),
         "--tools", "", "--no-session-persistence", "--disable-slash-commands",
         "--setting-sources", "", "--strict-mcp-config", "--system-prompt", cfg.get("system", SYSTEM)],
        input=question, capture_output=True, text=True, timeout=cfg.get("timeout", TIMEOUT),
        # the CLI provider uses the plan login; the API key is for the "anthropic" provider, so keep it out of here
        env={k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"},
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ProviderError(f"claude CLI failed ({proc.returncode}): {(proc.stderr or proc.stdout)[:200]}")
    if out.get("is_error"):
        raise ProviderError(f"claude CLI error: {str(out.get('result'))[:200]}")
    return str(out.get("result", "")).strip()


def anthropic_api(cfg: dict, question: str) -> str:
    try:
        import anthropic  # only needed when this provider is used
    except ImportError:
        raise ProviderError("the anthropic package is not installed (pip install anthropic)")

    client = anthropic.Anthropic(api_key=_key(cfg, "ANTHROPIC_API_KEY"), timeout=cfg.get("timeout", TIMEOUT))
    try:
        msg = client.messages.create(
            model=cfg.get("model", DEFAULT_CLAUDE_MODEL),
            max_tokens=cfg.get("max_tokens", 1024),
            system=cfg.get("system", SYSTEM),
            output_config={"effort": cfg.get("effort", "low")},  # short answers: little thinking
            messages=[{"role": "user", "content": question}],
        )
    except anthropic.APIStatusError as e:
        raise ProviderError(f"Claude API {e.status_code}: {e.message[:150]}")
    except anthropic.APIConnectionError as e:
        raise ProviderError(f"Claude API unreachable: {e}")
    if msg.stop_reason == "refusal":
        raise ProviderError("Claude declined to answer")
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def openai_compatible(cfg: dict, question: str) -> str:
    if "model" not in cfg:
        raise ProviderError("openai provider needs a model")
    url = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    key = _key(cfg, "OPENAI_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "system", "content": cfg.get("system", SYSTEM)}, {"role": "user", "content": question}],
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=cfg.get("timeout", TIMEOUT)) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        raise ProviderError(f"{url.split('/')[2]} {e.code}: {e.read()[:150].decode(errors='replace')}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise ProviderError(f"{url.split('/')[2]} unreachable: {e}")
    try:
        return out["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError):
        raise ProviderError(f"unexpected reply: {str(out)[:150]}")


def command(cfg: dict, question: str) -> str:
    argv = cfg.get("command")
    if not isinstance(argv, list) or not argv:
        raise ProviderError('command provider needs "command": [argv...]')
    try:
        proc = subprocess.run(argv, input=f"{cfg.get('system', SYSTEM)}\n\n{question}", capture_output=True, text=True,
                              timeout=cfg.get("timeout", TIMEOUT))
    except FileNotFoundError:
        raise ProviderError(f"{argv[0]} is not installed")
    if proc.returncode != 0:
        raise ProviderError(f"{argv[0]} failed ({proc.returncode}): {(proc.stderr or proc.stdout)[:150]}")
    return proc.stdout.strip()


TYPES = {"claude-cli": claude_cli, "anthropic": anthropic_api, "openai": openai_compatible, "command": command}


def load_config(data_dir: str) -> dict:
    path = os.environ.get("PROVIDERS_FILE", os.path.join(data_dir, "providers.json"))
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
    else:
        cfg = {"default": "claude", "providers": {"claude": {"type": "claude-cli"}}}
    if os.environ.get("LLM_PROVIDER"):
        cfg["default"] = os.environ["LLM_PROVIDER"]
    names = [cfg["default"], *cfg.get("fallback", [])]
    for name in names:
        p = cfg.get("providers", {}).get(name)
        if p is None:
            raise SystemExit(f"providers: '{name}' is not defined in {path}")
        if p.get("type") not in TYPES:
            raise SystemExit(f"providers: '{name}' has unknown type {p.get('type')!r} (use {', '.join(TYPES)})")
    return cfg


def answer(cfg: dict, question: str) -> str:
    """Ask the default provider; on failure try each fallback. Raises ProviderError listing what went wrong."""
    problems = []
    for name in [cfg["default"], *cfg.get("fallback", [])]:
        p = cfg["providers"][name]
        try:
            text = TYPES[p["type"]](p, question)
            if text:
                return text
            problems.append(f"{name}: empty answer")
        except ProviderError as e:
            problems.append(f"{name}: {e}")
        except subprocess.TimeoutExpired:
            problems.append(f"{name}: timed out")
    raise ProviderError("; ".join(problems))
