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
    volumes:
      - ./data:/data
```

Environment variables (none of them hold LLM secrets: the LLM, its model, address and token or API key are all set on the Settings page):

| Variable | Required | What it does |
| --- | --- | --- |
| `LOGIN_PASSWORD` | yes | Password for the website (needed to pair a watch and open Settings). |
| `LOGIN_USER` | no | Website user name. Default `me`. |
| `SECRET_KEY` | no | Session signing key. Generated on first start and saved in `/data` if not set. |
| `TOKEN_MAX_IDLE_DAYS` | no | A watch not used for this many days must pair again. Default `90`. |
| `PUID` / `PGID` | no | User and group the server runs as. Defaults `1000` / `100`. |

Put the data volume somewhere persistent: it holds the paired watches, the LLM setting and any API key entered on the page.

Run without Docker: `cd server && LOGIN_PASSWORD=... gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:8000 app:app`.

### Which LLM answers
One LLM, set on the website: sign in, open **Settings**, pick the type and fill in the fields. It applies right away and is stored in the data volume (`/data/watch.db`). The watch has no model setting.

- **Claude (Claude Code login)**: the default, Haiku unless you enter a model. Paste the token from `claude setup-token` on the Settings page.
- **Claude API**: model plus an API key.
- **OpenAI-compatible**: model, server address and optional API key. Works with OpenAI, Ollama (`http://HOST:11434/v1`), LM Studio, vLLM, OpenRouter, Groq and Gemini's compatible endpoint. This is how you use a self-hosted LLM.
- **Other command-line agent**: a command that reads the question on stdin and prints the answer (it must be installed in the image).

Tokens and API keys entered on the page are saved in the data volume, so protect that folder. The page never shows a saved key; leave the box blank to keep it.

### Watches and messages
Each paired watch is listed on the home page with its name (the watch sends its own name when pairing; you can also type one when pairing). Rename it or remove just that watch there; "Unpair all" removes every watch. Every question and answer is saved (Settings > Messages turns saving off); **Messages** shows them with the watch name and time, and lets you delete one or all. Messages stay when a watch is removed. They are stored unencrypted in `/data/watch.db`.

### Security notes
- Every web form carries a CSRF token and the session cookie is `SameSite=Strict` (and `Secure` when served over HTTPS), so another site cannot change your settings. Pages send `X-Frame-Options: DENY` and a Content-Security-Policy.
- Login allows 5 wrong passwords per address and 20 overall per 15 minutes, then locks for the rest of the window (the watch keeps working). Pairing is rate-limited and request bodies are capped at 64 KB.
- `/data` is private to the server user (`0700`, files `0600`). It holds the LLM token or API key, saved messages and paired watches, all unencrypted: back it up somewhere equally private.
- The Claude CLI and the "other command" option only see `PATH`, `HOME`, `LANG`, `TZ` (plus the Claude token): never `LOGIN_PASSWORD` or `SECRET_KEY`.
- The "other command" and OpenAI-compatible options make the server run a command or call an address you choose: only you can set them (signed in), but treat the password accordingly. Put the server behind HTTPS, and ideally Cloudflare Access or a VPN for the web pages (the watch only needs `/pair/*`, `/ask` and `/health`).
- The watch app only accepts `http://` for addresses on your own network.

Pairing: the watch shows a 6-character code; sign in on the server's web page and enter it. The server has no HTTPS of its own, so put it behind a reverse proxy before using it outside your LAN.

## Watch app
SwiftUI, watch-only (no iPhone target). `brew install xcodegen && xcodegen generate`, then build to the watch from Xcode. There is no built-in server address: the first screen asks for it (type `claude.example.com`, no `https://` needed), and the gear button on every later screen changes it or re-pairs the watch.
