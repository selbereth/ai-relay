# AI Relay

Ask Claude from an Apple Watch with no iPhone. A small server answers through the Claude Code CLI (always Haiku); the watch pairs with it using a code.

## Server
Docker image `ghcr.io/selbereth/watch-claude:latest`, built by GitHub Actions on every push to `main` that touches `server/`. Use `docker-compose.yml` (set `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, and `LOGIN_PASSWORD`).

Run without Docker: `cd server && LOGIN_PASSWORD=... gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:8000 app:app` (uses the local `claude` login).

Pairing: the watch shows a 6-character code; sign in on the server's web page and enter it. The server has no HTTPS of its own, so put it behind a reverse proxy before using it outside your LAN.

## Watch app
SwiftUI, watch-only (no iPhone target). `brew install xcodegen && xcodegen generate`, the server address is in `WatchClaude/Config.swift`, then build to the watch from Xcode.
