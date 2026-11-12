---
name: wisplink
description: Publish a user-authorized local single-file HTML page to the configured WispLink server, then return its preview URL, expiry, and publication ID.
---

# Publish an HTML preview

1. Resolve the explicitly named HTML file, or the single unambiguous HTML file just generated for this user. Ask before uploading if several files match or the file appears to contain credentials, personal data, or other sensitive material.
2. Use the host Mac terminal and run `wisplink publish "<path>" --json`. Pass the requested `--ttl` or ISO 8601 `--expires-at` with a time zone, and `--max-ips` if specified. Honor `--no-path` when the user asks to omit the local path.
3. Report the URL, expiry (or permanent), publication ID, and any compatibility warnings returned by the CLI.

Use the instance already configured in the CLI. If the command is missing, the server is unconfigured, or authorization has expired, report the exact setup step to the user. Keep uploaded HTML and credentials out of the conversation. Follow the user's requested scope for any retry.
