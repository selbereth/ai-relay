# AI Relay

Ask Claude from an Apple Watch with no iPhone. A small server answers through the Claude Code CLI (Haiku by default), the Claude API or any other LLM you configure; the watch pairs with it using a code.

## Server
Docker image `ghcr.io/selbereth/ai-relay:latest`, built from `server/` (CI is deferred for now). Example `docker-compose.yml` (also works as a Portainer stack):

```yaml
services:
  ai-relay:
    image: ghcr.io/selbereth/ai-relay:latest
    container_name: ai-relay
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      LOGIN_PASSWORD: change-me
      CLAUDE_CODE_OAUTH_TOKEN: ""   # only for the Claude Code option
    volumes:
      - ./data:/data
```

Environment variables:

| Variable | Required | What it does |
| --- | --- | --- |
| `LOGIN_PASSWORD` | yes | Password for the website (needed to pair a watch and open Settings). |
| `LOGIN_USER` | no | Website user name. Default `me`. |
| `CLAUDE_CODE_OAUTH_TOKEN` | for the Claude Code option | Token from `claude setup-token`. |
| `ANTHROPIC_API_KEY` | no | API key for the Claude API option, instead of entering it on the Settings page. |
| `OPENAI_API_KEY` | no | Same, for the OpenAI-compatible option. |
| `SECRET_KEY` | no | Session signing key. Generated on first start and saved in `/data` if not set. |
| `PUID` / `PGID` | no | User and group the server runs as. Defaults `1000` / `100`. |

Put the data volume somewhere persistent: it holds the paired watches, the LLM setting and any API key entered on the page.

Run without Docker: `cd server && LOGIN_PASSWORD=... gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:8000 app:app` (uses the local `claude` login).

### Which LLM answers
One LLM, set on the website: sign in, open **Settings**, pick the type and fill in the fields. It applies right away and is stored in the data volume (`/data/watch.db`). The watch has no model setting.

- **Claude (Claude Code login)**: the default, Haiku unless you enter a model. Uses `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`).
- **Claude API**: model plus an API key (or the `ANTHROPIC_API_KEY` env var).
- **OpenAI-compatible**: model, server address and optional API key. Works with OpenAI, Ollama (`http://HOST:11434/v1`), LM Studio, vLLM, OpenRouter, Groq and Gemini's compatible endpoint. This is how you use a self-hosted LLM.
- **Other command-line agent**: a command that reads the question on stdin and prints the answer (it must be installed in the image).

API keys entered on the page are saved in the data volume, so protect that folder. The page never shows a saved key; leave the box blank to keep it.

Pairing: the watch shows a 6-character code; sign in on the server's web page and enter it. The server has no HTTPS of its own, so put it behind a reverse proxy before using it outside your LAN.

## Watch app
SwiftUI, watch-only (no iPhone target). `brew install xcodegen && xcodegen generate`, then build to the watch from Xcode. There is no built-in server address: the first screen asks for it (type `claude.example.com`, no `https://` needed), and the gear button on every later screen changes it or re-pairs the watch.
