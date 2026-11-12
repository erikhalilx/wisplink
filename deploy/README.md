# Linux 原生部署

本手册适用于使用 Nginx 和 systemd 的 Linux 主机。为控制台和预览服务分别配置域名，例如 `console.example.com` 和 `preview.example.com`。启用公网访问前，请确认两个域名都已解析到部署主机，并为它们配置 HTTPS 证书。

## 安装

1. 用 `nginx -T` 检查现有站点的 include 目录和域名，用 `ss -ltn` 检查 8000、8001 端口。端口冲突时同步调整 WispLink 的两个 service 和 Nginx upstream。保留原站点配置和防火墙规则。
2. 在服务器安装 `python3.11`。保留系统 Python。用 `useradd --system --home-dir /var/lib/wisplink --shell /sbin/nologin wisplink` 创建服务用户，准备属主为该用户、权限为 0700 的 `/var/lib/wisplink`。
3. 将代码部署到 `/opt/wisplink`，由管理员持有。用 `uv sync --locked --no-dev --python python3.11` 安装锁定依赖。建议在开发机运行 `cd web && npm ci && npm run build`，将 `web/dist/` 内容复制到 `/var/www/wisplink/`。
4. 将 `wisplink.env.example` 复制到 `/etc/wisplink/wisplink.env`，设置两个 HTTPS origin。用 `.venv/bin/python -m wisplink.manage generate-key` 生成独立密钥，并将配置文件设为 `root:wisplink`、权限 0640。文件只保存配置及密钥。
5. 从代码目录以 `wisplink` 用户运行迁移和初始化。迁移前确认 `/var/lib/wisplink` 已就绪。

   ```bash
   sudo -u wisplink sh -c 'umask 077; set -a; . /etc/wisplink/wisplink.env; set +a; /opt/wisplink/.venv/bin/python -m wisplink.manage migrate'
   sudo -u wisplink sh -c 'umask 077; set -a; . /etc/wisplink/wisplink.env; set +a; /opt/wisplink/.venv/bin/python -m wisplink.manage create-admin YOUR_USERNAME'
   ```

6. 将四个 systemd 单元复制到 `/etc/systemd/system/`，运行 `systemctl daemon-reload`，再运行 `systemctl enable --now wisplink-api wisplink-auth wisplink-cleanup.timer`。
7. 复制一份 `wisplink.nginx.conf` 到现有 Nginx 的 include 目录。将示例域名和 TLS 路径替换成实际值。只在 `nginx -t` 成功后运行 `systemctl reload nginx`。如果 SELinux 拒绝代理到回环端口，按现有系统策略为这些连接配置权限。
8. 测试已有站点和 WispLink。用 Mac 登录控制台、上传样例、检查访客点击前后的计数，再配置 CLI 指向本次部署的控制台域名并授权发布。查看 `journalctl -u wisplink-api -u wisplink-auth -u wisplink-cleanup`，并根据实测带宽调整预览并发与单连接传输上限。

## 备份、恢复、更新

以有权读取数据库的用户加载生产配置，再执行 `python -m wisplink.manage backup /path/to/new-backup.sqlite3`。该命令使用 SQLite 在线备份，可在 WAL 模式下运行。配置与密钥另行加密备份。备份目录应在上传目录之外，且不包含 HTML 或临时文件。

恢复前停掉 WispLink API、授权服务和清理定时器。将备份恢复到干净的数据目录，恢复配套配置和密钥，运行 `migrate` 和 `reconcile`，再启动服务。恢复时撤销旧会话和设备授权，缺失源文件的记录显示为内容不可用。恢复后的用户需重新登录授权。检查现有 Nginx 站点及 WispLink 的登录和发布。

升级前保留旧版本程序和配置，执行数据库备份。构建新前端并安装锁定的 Python 依赖，停服务后执行数据库迁移，再启动新版本。回退时先核对新旧 schema 是否兼容，必要时使用升级前数据库备份恢复。

清理失败可通过 `systemctl --failed` 和 `journalctl -u wisplink-cleanup` 检查。修复磁盘或权限问题后重跑 `systemctl start wisplink-cleanup`。清理任务可重复运行。
