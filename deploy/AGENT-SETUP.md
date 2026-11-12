# Agent 引导部署 · Alibaba Cloud ECS

适配范围为阿里云 ECS 上的 Alibaba Cloud Linux 3.2104 LTS（x86_64），本地使用 Apple 芯片 Mac。此流程适用于在已有 ECS 上首次安装 WispLink。

1. 向用户确认 ECS 的 SSH 地址或配置别名、实例公网 IPv4、控制台域名和预览域名。确认目标是用户管理的 ECS。用户在自己的终端完成 SSH 主机身份核验和 sudo 认证。凭据留在 SSH 客户端或浏览器。
2. 通过 SSH 只读检查 `/etc/os-release`、`uname -m`、现有 Nginx 和监听端口。服务器需要系统 Python 3.11、Nginx、systemd，以及 sudo 可执行的 `uv`。在 Alibaba Cloud Linux 上可用 `sudo dnf install python3.11 nginx` 准备系统依赖。需要安装包时先让用户知道具体变更。Nginx 的 HTTP 配置需要包含 `/etc/nginx/conf.d/*.conf`。
3. 引导用户将两个域名的 A 记录指向该 ECS，准备可被系统信任的证书和私钥。默认读取 `/etc/letsencrypt/live/<控制台域名>/fullchain.pem` 和 `privkey.pem`，证书需覆盖两个域名。独立证书可通过 `WISPLINK_CONSOLE_TLS_DIR`、`WISPLINK_PREVIEW_TLS_DIR` 指定。若需申请证书，根据用户的 DNS 提供商引导 DNS 验证。公网站点需要开放 TCP 80/443。使用中国内地 ECS 时，核对 [阿里云备案要求](https://help.aliyun.com/zh/icp-filing/basic-icp-service/product-overview/faq-about-icp-filing-applications-in-different-scenarios)。
4. 从 [v0.2.0 源码归档](https://github.com/erikhalilx/wisplink/archive/refs/tags/v0.2.0.tar.gz) 下载和解压。以普通用户在源码目录运行 `(cd web && npm ci && npm run build)`，需要 Node.js 22.12+。可以在 Mac 构建后，将解压后的源码和 `web/dist/` 一起传到 ECS 的临时工作目录。在 ECS 的源码目录检查：

   ```bash
   sudo bash deploy/install-ecs.sh --check console.example.com preview.example.com 203.0.113.10
   ```

5. 检查通过并确认目标后，将 `--check` 改为 `--install`。脚本准备系统用户和目录、安装锁定的 Python 依赖、生成实例密钥、迁移数据库、启动 systemd 服务并添加独立的 Nginx 站点。再次执行时使用同一版本、域名和证书路径。若发现已有的非托管安装或配置冲突，先按提示处理。若 Nginx 无法代理到回环端口，检查系统日志及 SELinux 的现有策略。
6. 让用户在自己的 SSH 终端创建首个管理员，输入自己的用户名和密码。

   ```bash
   sudo -u wisplink sh -c 'umask 077; set -a; . /etc/wisplink/wisplink.env; set +a; /opt/wisplink/.venv/bin/python -m wisplink.manage create-admin "$1"' sh YOUR_USERNAME
   ```

7. 从 Mac 验证控制台 HTTPS 地址，运行 `wisplink connect <控制台域名>`。浏览器授权后发布一份用户指定的 HTML，打开生成的预览链接验证整个流程。

维护和手动升级见 [Linux 部署手册](README.md)。
