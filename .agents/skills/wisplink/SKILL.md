---
name: wisplink
description: Connect an Apple silicon Mac to an existing WispLink console, publish local single-file HTML previews, or guide a first deployment on Alibaba Cloud ECS.
---

# Connect, deploy, or publish with WispLink

Run WispLink commands in the host Mac's local terminal. Importing this Skill only makes the instructions available; check the CLI and connection when the user asks to connect, set up WispLink, or publish. Keep the original file and publish options through installation and browser authorization.

## Connect to an existing instance

1. Find `wisplink` on `PATH` and check whether `wisplink connect --help` succeeds. If it is missing or too old, also check the executable at `$(uv tool dir --bin)/wisplink` when `uv` is available. Reuse a compatible CLI and use its verified path for all subsequent commands.
2. Check the saved `server` in `~/Library/Application Support/WispLink/config.json` if present. When the saved server matches the user's target (or no other target was specified), use `wisplink list --json` to verify access without opening a browser. If it succeeds, proceed with the original task. Do not display the listing or credentials. If the server is unreachable, report the problem and allow a retry. If only its authorization is missing or expired, use `wisplink login` for that server.
3. When a new connection is needed, use the console HTTPS origin already supplied by the user. If the target cannot be determined, ask for the console HTTPS address only. If the user says they have no instance, offer the deployment route below.
4. If a compatible CLI is unavailable, run the following on the Mac. If `uv` is missing, guide the user through the [official uv installation](https://docs.astral.sh/uv/getting-started/installation/) and resume at this step once it is available.

   ```sh
   uv tool install --from 'https://github.com/erikhalilx/wisplink/archive/refs/tags/v0.2.0.tar.gz' wisplink
   ```

   For an outdated CLI, use the same command with `--upgrade` only after checking that the executable is managed by uv: compare its resolved path to the uv tool executable and confirm the installation with `uv tool list`. Leave an executable owned by another installer in place. Install a separate uv copy if possible, or explain the collision and ask how to proceed. After installation or update, locate the uv executable again and verify `connect --help` on the exact path you will use; an older executable can still take precedence on `PATH`.

5. Run `wisplink connect "<console-https-origin>"`. The CLI verifies the instance and opens the system browser. Ask the user to sign in and grant access in the browser, and keep the terminal process running until it exits. Report a connection only after success. If authorization is declined, cancelled, or times out, offer to retry. If discovery reports a possible older instance, confirm that the address belongs to the user before retrying with `--legacy`. For other discovery errors, report the error and let the user correct the address or explicitly choose deployment.
6. If the user originally requested a publish, continue with that same file and options as soon as the connection is ready. For a connection-only request, stop after reporting success.

## Deploy to an Alibaba Cloud ECS instance

Use the [Agent deployment guide](https://github.com/erikhalilx/wisplink/blob/v0.2.0/deploy/AGENT-SETUP.md) and the `deploy/install-ecs.sh` it references from the same release. This route targets an existing SSH-accessible ECS with Alibaba Cloud Linux 3.2104 LTS (x86_64). Ask for the server and domain details in that guide. Start with `--check`. Use `--install` only after the user has confirmed the target and requested deployment. On success, guide first-admin creation in the user's terminal, then connect the Mac using the flow above.

## Publish an HTML preview

1. Resolve the explicitly named HTML file, or the single unambiguous HTML file just generated for the user. Ask for the file if it is missing, and ask before uploading if several files match or the file appears to contain credentials, personal data, or other sensitive material.
2. Once the connection is ready, run `wisplink publish "<path>" --json`. Pass the requested `--ttl` or ISO 8601 `--expires-at` with a time zone, and `--max-ips` if specified. Honor `--no-path` when the user asks to omit the local path.
3. Report the URL, expiry (or permanent), publication ID, and any compatibility warnings returned by the CLI. If the CLI explicitly rejects the publish because authorization expired, use `wisplink login` for the current server and retry the original request after authorization succeeds. For a network failure with an uncertain result, check whether the publication already exists before retrying. Keep the HTML contents and credentials out of the conversation.

## Update an existing installation

Reimport this Skill from the updated [v0.2.0 source](https://github.com/erikhalilx/wisplink/tree/v0.2.0/.agents/skills/wisplink) to update its instructions. A compatible CLI can still be reused. If the user requests the updated same-version CLI, verify that uv owns the installed CLI and that `uv tool install --help` supports `--reinstall-package`, then run:

```sh
uv tool install --reinstall-package wisplink --from 'https://github.com/erikhalilx/wisplink/archive/refs/tags/v0.2.0.tar.gz' wisplink
```

Verify the actual executable path afterward. Keep the existing configuration and Keychain authorization.
