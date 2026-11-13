# WispLink

[简体中文](README.md)

**0.2 compatibility** · Apple silicon Mac (macOS) for the local Agent and CLI, and Alibaba Cloud ECS with Alibaba Cloud Linux 3.2104 LTS (x86_64) for the server.

WispLink is a self-hosted service for sharing single-file HTML previews. Publish from the web console or the macOS CLI. Opening a link displays the HTML directly. The browser runs the preview in a sandbox on a separate site, with access limited by public IP.

## Connect to an existing WispLink instance with an Agent

1. On an Apple silicon Mac, import the [v0.2.0 WispLink skill](https://github.com/erikhalilx/wisplink/tree/v0.2.0/.agents/skills/wisplink) (the entire `.agents/skills/wisplink` directory) into an Agent with access to the local terminal. Codex can discover it in the source checkout. In a local WorkBuddy task, import the directory. Importing the skill does not install the CLI.
2. Replace the example URL with your console's HTTPS address and send this to the Agent:

   ```text
   Connect my Mac to WispLink. My console address is https://console.example.com.
   ```

   The Agent reuses a working connection or a compatible CLI. If the CLI is missing, it installs it from the GitHub v0.2.0 source with `uv`. If `uv` is missing, the Agent will guide you through setting it up.
3. Sign in to the console and grant access in your system browser. After the Agent confirms the connection, attach a single-file HTML document or provide its path on the Mac. For example:

   ```text
   Publish this HTML file as a preview link that expires in 24 hours.
   ```

   You can also give the Agent the console address, file and options in your first message. It continues the original publish after authorization and returns the preview URL, expiry and publication ID.

Super administrators can also download the optional **Agent setup package** from the console overview. The ZIP includes the prefilled console address, instructions, a skill and an installer. Give the ZIP to the Agent and ask it to connect using the package.

### Already installed v0.2.0?

Reimport the skill from the link above. The update on GitHub does not replace copies already on your Mac. Keep using a compatible CLI, or ask the Agent to check `uv` and the active CLI path and run the same-version reinstall from the skill. Your settings and authorization are retained.

## First deployment on Alibaba Cloud ECS

If you do not have a WispLink instance yet, ask the Agent to follow the [Alibaba Cloud ECS setup guide](deploy/AGENT-SETUP.md) to prepare the domains and certificates and run the deployment script from the same release.

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

## Use the macOS CLI manually

Run these commands in the Mac terminal. Replace the example URL with your own console's HTTPS address and sign in to that instance.

```bash
uv tool install --from 'https://github.com/erikhalilx/wisplink/archive/refs/tags/v0.2.0.tar.gz' wisplink
wisplink connect https://console.example.com
wisplink publish ./report.html --ttl 24h --max-ips 10 --json
```

The CLI requires an explicit server address. The `connect` command verifies the console and starts browser authorization. Credentials are stored in the macOS Keychain. To connect to a confirmed v0.1.0 instance, use `wisplink connect https://console.example.com --legacy`. Use `wisplink config set-defaults` to set local defaults. The CLI records the absolute source path by default. Use `--no-path` to omit it or `--path-note` to supply a note. Use either a preset `--ttl` or an ISO 8601 timestamp with a timezone via `--expires-at`.

## Preview behavior

- Choose 30 minutes, 1/6/24 hours, 7/14/30/90/180/365 days, permanent, or a specific date. An active link can be shortened or extended. A new preset runs from the time of the edit. Administrators can cap the total lifetime.
- A GET request registers the public IP and serves the HTML directly. Visitors on a registered IP can return. Once the limit is reached, new IPs see an error page. A HEAD check uses no slot. Link preview services that send GET requests follow the same rules.
- The service supports self-contained UTF-8 HTML, embedded charts, and inline scripts. Browser policy restricts external resources and form submissions. Publish content suitable for link sharing.
- Disabling an account revokes web sessions and CLI authorization. Existing links follow their configured lifetime. Super administrators can manage all published links.
- Cleanup removes expired or closed preview files and retains aggregate page views, unique visitors, and IP counts. Backups cover the database and configuration. Restoring a backup marks missing content as unavailable.

For Linux deployment with Nginx and systemd, see the [deployment guide in Chinese](deploy/README.md). Set your own console and preview HTTPS origins before enabling public access.

## License

[MIT](LICENSE)
