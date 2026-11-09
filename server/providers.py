"""Where the answers come from: one LLM, chosen on the website's Settings page (stored in the data volume).

The watch only sends a question. The server answers it with the configured LLM, a dict with a "type":

  claude-cli  the Claude Code CLI (`claude -p`), uses CLAUDE_CODE_OAUTH_TOKEN or a local login. "model": default Haiku.
  anthropic   the Claude API (Anthropic SDK). "model", "api_key" (or the ANTHROPIC_API_KEY env var).
  openai      anything that speaks OpenAI chat completions: OpenAI, Ollama, LM Studio, vLLM, OpenRouter, Groq, Gemini's
              OpenAI-compatible endpoint. "base_url" (default https://api.openai.com/v1), "model", "api_key" (optional).
  command     any other agent CLI: "command" is the command line; the question goes to stdin, the answer is stdout.
"""
import json
import os
import shlex
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
    key = cfg.get("api_key") or os.environ.get(default_env, "")
    if not key and cfg.get("type") != "openai":
        raise ProviderError("no API key set (Settings page)")
    return key  # an OpenAI-compatible local server may need no key


def claude_cli(cfg: dict, question: str) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", cfg.get("model") or DEFAULT_CLAUDE_MODEL,
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
            model=cfg.get("model") or DEFAULT_CLAUDE_MODEL,
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
    if not cfg.get("model"):
        raise ProviderError("no model set (Settings page)")
    url = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
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
    try:
        argv = shlex.split(cfg.get("command") or "")
    except ValueError as e:
        raise ProviderError(f"bad command: {e}")
    if not argv:
        raise ProviderError("no command set (Settings page)")
    try:
        proc = subprocess.run(argv, input=f"{cfg.get('system', SYSTEM)}\n\n{question}", capture_output=True, text=True,
                              timeout=cfg.get("timeout", TIMEOUT))
    except FileNotFoundError:
        raise ProviderError(f"{argv[0]} is not installed")
    if proc.returncode != 0:
        raise ProviderError(f"{argv[0]} failed ({proc.returncode}): {(proc.stderr or proc.stdout)[:150]}")
    return proc.stdout.strip()


TYPES = {"claude-cli": claude_cli, "anthropic": anthropic_api, "openai": openai_compatible, "command": command}
DEFAULT = {"type": "claude-cli"}


def answer(cfg: dict, question: str) -> str:
    """Ask the configured LLM. Raises ProviderError with a short reason."""
    fn = TYPES.get(cfg.get("type"))
    if fn is None:
        raise ProviderError("no LLM set up (Settings page)")
    try:
        text = fn(cfg, question)
    except subprocess.TimeoutExpired:
        raise ProviderError("timed out")
    if not text:
        raise ProviderError("empty answer")
    return text
