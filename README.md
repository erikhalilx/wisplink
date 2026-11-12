# WispLink

[English](README.en.md)

自托管的单文件 HTML 预览发布工具。用 Web 或 macOS CLI 发布，访客持链接点击「打开预览」后占用一个公网 IP 名额。预览在独立站点和沙箱 iframe 中展示。

## 本地运行

需要 Python 3.11+、uv，以及构建 Vue 所需的 Node.js 22.12+ 或更新版本。

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

在三个终端分别启动以下命令。前两个终端需要加载同一个 `.env`。

```bash
uv run uvicorn wisplink.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
uv run gunicorn --bind 127.0.0.1:8001 'wisplink.oauth:create_auth_app()'
cd web && npm run dev
```

打开 [本地控制台](http://localhost:5173)。预览内容使用 `127.0.0.1:8000`，链接供本机验收。运行 `uv run pytest -q` 可复核 Web 和 OAuth 行为。

## macOS CLI 与 Agent

在下载或克隆的 WispLink 源码目录中运行以下命令。将示例地址替换为你自己部署的控制台 HTTPS 地址，使用该实例的账号登录。首次安装时，CLI 需要你显式配置服务器地址。

```bash
git clone https://github.com/Erikhalilx/wisplink.git
cd wisplink
uv tool install .
wisplink config set-server https://console.example.com
wisplink login
wisplink publish ./report.html --ttl 24h --max-ips 10 --json
```

`login` 通过系统浏览器授权，凭证保存在 macOS 钥匙串。使用 `wisplink config set-defaults` 设置本机默认值。CLI 默认记录本地绝对路径，可以用 `--no-path` 省略或用 `--path-note` 提供备注。自定义到期时间使用 `--expires-at` 和带时区的 ISO 8601 日期。预设时长和自定义日期二选一。

Codex 可从仓库内的 `.agents/skills/wisplink` 发现 Skill。WorkBuddy 使用本地任务，把 [发布 Skill](.agents/skills/wisplink/SKILL.md) 所在目录作为本地 Skill 导入，并确认当前任务可读文件及调用本机终端。

## 发布规则

- 有效期支持 30 分钟、1/6/24 小时、7/14/30/90/180/365 天、永久或指定到期时间。有效链接可以缩短、延长或切换永久。修改时选择预设档位会从修改时刻重新计算。管理员可设置从首次发布计算的累计上限。
- 首次 GET 或 HEAD 只展示确认页。点开后，同一请求登记 IP 并将内容交给沙箱 iframe。换公网 IP 后重新打开会按新 IP 检查名额。
- 支持 UTF-8 自包含 HTML、内嵌图表和页内脚本。浏览器安全策略限制第三方资源和表单提交。页面本身不应包含需要保密的数据。
- 停用账号会撤销 Web 和 CLI 会话，已发布的有效链接按原规则继续提供。超级管理员可查看和管理全部发布。
- 清理任务删除过期或关闭的文件及明细，保留 PV、UV 和 IP 汇总。备份保存数据库与配置，恢复时将缺失内容标为不可访问。

生产安装、更新和恢复见 [部署手册](deploy/README.md)。

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
