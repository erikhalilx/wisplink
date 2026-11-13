# WispLink

[English](README.en.md)

**0.2 系列适配范围** · 本地 Apple 芯片 Mac（macOS），服务器为阿里云 ECS + Alibaba Cloud Linux 3.2104 LTS（x86_64）。

自托管的单文件 HTML 预览发布工具。用 Web 或 macOS CLI 发布，访客持链接点击「打开预览」后占用一个公网 IP 名额。预览在独立站点和沙箱 iframe 中展示。

## 通过 Agent 接入已有 WispLink

1. 在 Apple 芯片 Mac 上，将 [v0.2.0 的 WispLink Skill](https://github.com/erikhalilx/wisplink/tree/v0.2.0/.agents/skills/wisplink)（整个 `.agents/skills/wisplink` 目录）导入能调用本机终端的 Agent。Codex 可以在源码项目中发现该 Skill；WorkBuddy 可以在本地任务中导入目录。导入时不会安装 CLI。
2. 把下面的示例地址换成你的控制台 HTTPS 地址，发给 Agent：

   ```text
   帮我连接 WispLink。我的控制台地址是 https://console.example.com。
   ```

   Agent 会复用可用的连接或 CLI，需要安装时会通过 `uv` 从 GitHub 的 v0.2.0 源码安装。如果没有 `uv`，Agent 会引导你准备它。
3. 在系统浏览器中登录控制台并同意授权。等 Agent 确认连接成功，再附上单文件 HTML 或提供它在 Mac 上的路径，例如：

   ```text
   把这个 HTML 文件发布成预览链接，有效期 24 小时。
   ```

   也可以在第一条消息里同时提供控制台地址、HTML 和发布参数。授权成功后，Agent 会接着发布并返回预览 URL、有效期和发布 ID。

超级管理员也可在控制台首页下载可选的「Agent 接入包」。ZIP 包含预填的控制台地址、说明、Skill 和安装脚本。把 ZIP 交给 Agent，说「用这个包接入 WispLink」。

### 已经安装过 v0.2.0

从上方链接重新导入 Skill。GitHub 上的更新不会替换 Mac 上已有的副本。兼容的 CLI 可以继续使用；如果希望获取同版本的更新源码，请让 Agent 检查 `uv` 和实际使用的 CLI 路径，再按 Skill 里的命令重装，保留现有配置和授权。

## 首次部署到阿里云 ECS

如果还没有 WispLink 实例，可让 Agent 按照 [阿里云 ECS 部署指南](deploy/AGENT-SETUP.md) 准备域名与证书，并使用同版本的部署脚本。

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

## 手动使用 macOS CLI

如果想手动操作，在 Mac 终端运行以下命令。将示例地址替换为你自己部署的控制台 HTTPS 地址，使用该实例的账号登录。首次安装时，CLI 需要你显式配置服务器地址。

```bash
uv tool install --from 'https://github.com/erikhalilx/wisplink/archive/refs/tags/v0.2.0.tar.gz' wisplink
wisplink connect https://console.example.com
wisplink publish ./report.html --ttl 24h --max-ips 10 --json
```

`connect` 验证控制台并通过系统浏览器授权，凭证保存在 macOS 钥匙串。连接已确认属于自己的 v0.1.0 实例时，使用 `wisplink connect https://console.example.com --legacy`。使用 `wisplink config set-defaults` 设置本机默认值。CLI 默认记录本地绝对路径，可以用 `--no-path` 省略或用 `--path-note` 提供备注。自定义到期时间使用 `--expires-at` 和带时区的 ISO 8601 日期。预设时长和自定义日期二选一。

## 发布规则

- 有效期支持 30 分钟、1/6/24 小时、7/14/30/90/180/365 天、永久或指定到期时间。有效链接可以缩短、延长或切换永久。修改时选择预设档位会从修改时刻重新计算。管理员可设置从首次发布计算的累计上限。
- 首次 GET 或 HEAD 只展示确认页。点开后，同一请求登记 IP 并将内容交给沙箱 iframe。换公网 IP 后重新打开会按新 IP 检查名额。
- 支持 UTF-8 自包含 HTML、内嵌图表和页内脚本。浏览器安全策略限制第三方资源和表单提交。页面本身不应包含需要保密的数据。
- 停用账号会撤销 Web 和 CLI 会话，已发布的有效链接按原规则继续提供。超级管理员可查看和管理全部发布。
- 清理任务删除过期或关闭的文件及明细，保留 PV、UV 和 IP 汇总。备份保存数据库与配置，恢复时将缺失内容标为不可访问。

生产安装、更新和恢复见 [部署手册](deploy/README.md)。

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
