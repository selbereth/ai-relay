# AI Relay

Ask Claude from an Apple Watch with no iPhone. A small server answers through the Claude Code CLI (Haiku by default), the Claude API or any other LLM you configure; the watch pairs with it using a code.

## Server
Docker image `ghcr.io/selbereth/ai-relay:latest`, built by GitHub Actions on every push to `main` that touches `server/`. Use `docker-compose.yml` (set `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, and `LOGIN_PASSWORD`).

Run without Docker: `cd server && LOGIN_PASSWORD=... gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:8000 app:app` (uses the local `claude` login).

### Which LLM answers
By default the Claude Code CLI on Haiku. To use the Claude API or any other model, put a `providers.json` in the data volume (`/data/providers.json`, or set `PROVIDERS_FILE`). `default` answers; if it fails, the names in `fallback` are tried in order. The watch never picks, so add or change providers without touching the app.

```json
{
  "default": "claude",
  "fallback": ["api", "local"],
  "providers": {
    "claude": {"type": "claude-cli"},
    "api":    {"type": "anthropic", "model": "claude-haiku-5-5"},
    "gpt":    {"type": "openai", "model": "gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY"},
    "local":  {"type": "openai", "base_url": "http://ollama:11434/v1", "model": "llama3.2"},
    "other":  {"type": "command", "command": ["my-agent", "--stdin"]}
  }
}
```

- `claude-cli`: the Claude Code CLI (`CLAUDE_CODE_OAUTH_TOKEN` or a local login).
- `anthropic`: the Claude API through the Anthropic SDK (`ANTHROPIC_API_KEY`, or `api_key_env`).
- `openai`: anything that speaks OpenAI chat completions: OpenAI, Ollama, LM Studio, vLLM, OpenRouter, Groq, Gemini's compatible endpoint.
- `command`: any agent CLI; the question goes to stdin and the answer is read from stdout (the command must be installed in the image).
- Every provider also accepts `system` (the prompt), `timeout` and, where it makes sense, `model`. `LLM_PROVIDER=<name>` overrides `default` without editing the file.

Pairing: the watch shows a 6-character code; sign in on the server's web page and enter it. The server has no HTTPS of its own, so put it behind a reverse proxy before using it outside your LAN.

## Watch app
SwiftUI, watch-only (no iPhone target). `brew install xcodegen && xcodegen generate`, then build to the watch from Xcode. There is no built-in server address: the first screen asks for it (type `claude.example.com`, no `https://` needed), and the gear button on every later screen changes it or re-pairs the watch.
