---
name: wisplink
description: Set up WispLink on a local Apple silicon Mac, connect to an existing instance or guide a first deployment on Alibaba Cloud ECS, then publish local single-file HTML and return a preview URL.
---

# Connect, deploy, or publish with WispLink

Use the Mac's local terminal. If the user asks to set up WispLink or has no working connection, ask whether they already have a WispLink control panel address. Reuse a working connection for an ordinary publish request. Start deployment only if the user chooses that route.

## Connect an existing instance

1. Ask for the user's own control panel address if it was not supplied. Use its HTTPS origin.
2. Install the released CLI when needed. If `uv` is missing, guide the user through the [official uv installation](https://docs.astral.sh/uv/getting-started/installation/). Run:

   ```sh
   uv tool install --from 'https://github.com/erikhalilx/wisplink/archive/refs/tags/v0.2.0.tar.gz' wisplink
   ```

   If `wisplink` exists without the `connect` command, use the same install command with `--upgrade`. If the command is outside PATH, locate it under `uv tool dir --bin`.
3. Run `wisplink connect "<console-address>"` and have the user sign in and grant authorization in their browser. A successful connection verifies listing access and saves the server on this Mac. If the CLI reports a possible older instance, ask the user to verify the control panel address, then use `wisplink connect "<console-address>" --legacy`. If discovery fails for another reason, report it and let the user choose an address or deployment explicitly.

## Deploy to an Alibaba Cloud ECS instance

Use the [Agent deployment guide](https://github.com/erikhalilx/wisplink/blob/v0.2.0/deploy/AGENT-SETUP.md) and the `deploy/install-ecs.sh` it references from the same release. This route targets an existing SSH-accessible ECS with Alibaba Cloud Linux 3.2104 LTS (x86_64). Ask for the server and domain details in that guide. Start with `--check`. Use `--install` only after the user has confirmed the target and requested deployment. On success, guide first-admin creation in the user's terminal, then connect the Mac using the flow above.

## Publish an HTML preview

1. Resolve the explicitly named HTML file, or the single unambiguous HTML file just generated for this user. Ask before uploading if several files match or the file appears to contain credentials, personal data, or other sensitive material.
2. Use the host Mac terminal and run `wisplink publish "<path>" --json`. Pass the requested `--ttl` or ISO 8601 `--expires-at` with a time zone, and `--max-ips` if specified. Honor `--no-path` when the user asks to omit the local path.
3. Report the URL, expiry (or permanent), publication ID, and any compatibility warnings returned by the CLI.

If authorization has expired, use `wisplink login` for the current server. Keep uploaded HTML and credentials out of the conversation. Follow the user's requested scope for any retry.
