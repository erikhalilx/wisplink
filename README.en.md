# WispLink

[简体中文](README.md)

WispLink is a self-hosted service for sharing single-file HTML previews. Publish from the web console or the macOS CLI. A visitor uses one public IP slot after clicking **Open preview**. The preview runs in a sandboxed iframe on a separate site.

## Run locally

Install Python 3.11 or later, uv, and Node.js 22.12 or later to build the Vue console.

```bash
uv sync --locked
(cd web && npm ci && npm run build)

umask 077
if [ ! -e .env ]; then
  printf 'WISPLINK_KEY=%s\n' "$(uv run python -m wisplink.manage generate-key)" > .env
fi
set -a; . ./.env; set +a
uv run python -m wisplink.manage migrate
uv run python -m wisplink.manage create-admin YOUR_USERNAME
```

Run each command in a separate terminal. Load the same `.env` in the first two terminals.

```bash
uv run uvicorn wisplink.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
uv run gunicorn --bind 127.0.0.1:8001 'wisplink.oauth:create_auth_app()'
cd web && npm run dev
```

Open the [local console](http://localhost:5173). Local preview links use `127.0.0.1:8000`. Run `uv run pytest -q` to check the web and OAuth flows.

## macOS CLI and agents

Install from the source directory. Replace the example URL with your own console's HTTPS address and sign in to that instance.

```bash
git clone https://github.com/Erikhalilx/wisplink.git
cd wisplink
uv tool install .
wisplink config set-server https://console.example.com
wisplink login
wisplink publish ./report.html --ttl 24h --max-ips 10 --json
```

The CLI requires an explicit server address. Browser authorization stores credentials in the macOS Keychain. Use `wisplink config set-defaults` to set local defaults. The CLI records the absolute source path by default. Use `--no-path` to omit it or `--path-note` to supply a note. Use either a preset `--ttl` or an ISO 8601 timestamp with a timezone via `--expires-at`.

Codex can discover the [WispLink skill](.agents/skills/wisplink/SKILL.md) in this repository. To use it in a local WorkBuddy task, import the skill directory and give the task access to the file and local terminal.

## Preview behavior

- Choose 30 minutes, 1/6/24 hours, 7/14/30/90/180/365 days, permanent, or a specific date. An active link can be shortened or extended. A new preset runs from the time of the edit. Administrators can cap the total lifetime.
- A GET or HEAD request shows the confirmation page. Clicking the button registers the public IP and returns the sandboxed page. A different public IP is checked against the same limit.
- The service supports self-contained UTF-8 HTML, embedded charts, and inline scripts. Browser policy restricts external resources and form submissions. Publish content suitable for link sharing.
- Disabling an account revokes web sessions and CLI authorization. Existing links follow their configured lifetime. Super administrators can manage all published links.
- Cleanup removes expired or closed preview files and retains aggregate page views, unique visitors, and IP counts. Backups cover the database and configuration. Restoring a backup marks missing content as unavailable.

For Linux deployment with Nginx and systemd, see the [deployment guide in Chinese](deploy/README.md). Set your own console and preview HTTPS origins before enabling public access.

## License

[MIT](LICENSE)
