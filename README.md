# AI Relay

Ask Claude from an Apple Watch with no iPhone. A small server answers through the Claude Code CLI (always Haiku); the watch pairs with it using a code.

## Server
Docker image `ghcr.io/selbereth/ai-relay:latest`, built by GitHub Actions on every push to `main` that touches `server/`. Use `docker-compose.yml` (set `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, and `LOGIN_PASSWORD`).

### Portainer
1. Stacks > Add stack > Web editor, name it `ai-relay`, paste [`portainer.yaml`](portainer.yaml).
2. Under Environment variables set `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) and `LOGIN_PASSWORD`. Optionally `LOGIN_USER` (default `me`).
3. Deploy. The web page is on host port 8012 (change the left side of `8012:8000` to use another port). Data (paired watches, session key) is in `/mnt/user/appdata/ai-relay`.
4. Update: Stacks > ai-relay > Editor > "Re-pull image and redeploy". Never commit the token or password.

Run without Docker: `cd server && LOGIN_PASSWORD=... gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:8000 app:app` (uses the local `claude` login).

Pairing: the watch shows a 6-character code; sign in on the server's web page and enter it. The server has no HTTPS of its own, so put it behind a reverse proxy before using it outside your LAN.

## Watch app
SwiftUI, watch-only (no iPhone target). `brew install xcodegen && xcodegen generate`, copy `LocalConfig.swift.example` to `WatchClaude/LocalConfig.swift` (gitignored) and put your server address in it, then build to the watch from Xcode.
