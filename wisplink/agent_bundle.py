import shlex
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

CLI_SOURCE = "https://github.com/erikhalilx/wisplink/archive/refs/tags/v0.2.0.tar.gz"

README = """# WispLink Agent 接入包

在新 Mac 把这个 ZIP 交给能运行本机终端的 Agent，告诉它「用这个包接入 WispLink」。
如果附件界面无法读取 ZIP，请把下载文件的本地路径交给 Agent。Agent 解包后读取
`wisplink/SKILL.md`，再从同一目录运行 `/bin/bash install.sh`。

浏览器打开后，用这个实例的账号登录并授权。授权成功后，可以让 Agent
发布本机 HTML 并返回预览链接。包内的安装脚本已预填控制台地址。
"""

SKILL = """---
name: wisplink
description: Connect this Apple silicon Mac to the WispLink instance configured in this package, then publish user-approved local HTML previews.
---

# Connect and publish with WispLink

When the user asks to connect using this package, use the local Mac terminal.
Run `/bin/bash install.sh` from this Skill's directory. The script displays
the preconfigured control panel address, installs or reuses the CLI and opens
browser authorization. If it reports that uv is missing, help the user
install it using https://docs.astral.sh/uv/getting-started/installation/
and retry. Ask the user to complete authorization in their browser. Wait for
the command to succeed before reporting that publishing is available.

For a publish request, use the explicitly identified local single-file HTML.
Run `wisplink publish "<path>" --json` and return the preview URL, expiry and
publication ID. Honor requested expiry and IP limits with `--ttl` or
`--expires-at` and `--max-ips`. If the command is outside PATH, locate it under
`uv tool dir --bin`. Ask before publishing an ambiguous or sensitive file.
If authorization expires, run `wisplink login` and wait for browser approval.
"""

INSTALL = """if [[ $(uname -s) != Darwin || $(uname -m) != arm64 ]]; then
    printf '%s\n' '此接入包适用于 Apple 芯片 Mac。' >&2
    exit 1
fi
printf 'WispLink 控制台地址：%s\n' "$origin"
cli=$(command -v wisplink || true)
if [[ -z "$cli" ]] || ! "$cli" connect --help >/dev/null 2>&1; then
    if ! command -v uv >/dev/null 2>&1; then
        printf '%s\n' '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/' >&2
        exit 1
    fi
    cli="$(uv tool dir --bin)/wisplink"
    if [[ ! -x "$cli" ]] || ! "$cli" connect --help >/dev/null 2>&1; then
        uv tool install --from "$source" --upgrade wisplink
    fi
fi
exec "$cli" connect "$origin"
"""


def build_agent_bundle(console_origin: str) -> bytes:
    installer = (
        "#!/bin/bash\nset -euo pipefail\n"
        f"origin={shlex.quote(console_origin)}\n"
        f"source={shlex.quote(CLI_SOURCE)}\n" + INSTALL
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("README.md", README)
        bundle.writestr("wisplink/SKILL.md", SKILL)
        bundle.writestr("wisplink/install.sh", installer)
    return buffer.getvalue()
