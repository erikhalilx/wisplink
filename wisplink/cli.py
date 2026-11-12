import base64
import fcntl
import hashlib
import json
import os
import time
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import typer

from .security import token

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
config_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
CONFIG = Path.home() / "Library" / "Application Support" / "WispLink"
CLIENT_ID = "wisplink-cli"


def fail(message):
    typer.echo(message, err=True)
    raise typer.Exit(1)


@contextmanager
def profile():
    CONFIG.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = CONFIG / "config.json"
    lock = os.open(CONFIG / "profile.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock, "r+") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        try:
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
            yield config
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def save_config(config):
    path = CONFIG / "config.json"
    temporary = path.with_suffix(".tmp")
    with os.fdopen(
        os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "w"
    ) as file:
        json.dump(config, file)
    temporary.replace(path)


def normalize_origin(value):
    try:
        origin = value.strip().rstrip("/")
        parsed = urlsplit(origin)
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        if parsed.scheme == "https" or (
            parsed.scheme == "http"
            and parsed.hostname in ("localhost", "127.0.0.1", "::1")
        ):
            port = parsed.port
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            default = 443 if parsed.scheme == "https" else 80
            authority = (
                f"{host}:{port}" if port is not None and port != default else host
            )
            return f"{parsed.scheme}://{authority}"
    except ValueError:
        pass
    fail("请输入服务器的 HTTPS 根地址。")


def configured(config):
    origin = config.get("server")
    if not origin:
        fail("请先运行 wisplink config set-server https://你的后台域名")
    return normalize_origin(origin)


def vault():
    try:
        from keyring.backends.macOS import Keyring

        backend = Keyring()
        if backend.priority <= 0:
            raise RuntimeError
        return backend
    except Exception:
        fail("无法连接 macOS 钥匙串。请在本地 macOS 登录会话中运行 wisplink。")


def credential(vault_backend, origin):
    try:
        payload = vault_backend.get_password("WispLink CLI", origin)
        return json.loads(payload) if payload else None
    except Exception:
        fail("无法读取 macOS 钥匙串中的 WispLink 授权。")


def store(vault_backend, origin, payload):
    data = {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "expires_at": int(time.time()) + payload["expires_in"],
    }
    try:
        vault_backend.set_password("WispLink CLI", origin, json.dumps(data))
    except Exception:
        fail("无法将授权写入 macOS 钥匙串。")
    return data


def token_request(client, data):
    try:
        response = client.post("/oauth/token", data={"client_id": CLIENT_ID, **data})
        if response.is_success:
            try:
                payload = response.json()
                if isinstance(payload, dict) and all(
                    key in payload
                    for key in ("access_token", "refresh_token", "expires_in")
                ):
                    return payload
            except ValueError:
                pass
    except httpx.RequestError:
        fail("无法连接 WispLink 服务器。")
    fail("CLI 授权失败或已失效，请重新运行 wisplink login。")


def browser_code(origin):
    state = token()
    verifier = token()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parts = urlsplit(self.path)
            params = parse_qs(parts.query)
            matches = (
                self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
                and parts.path == "/callback"
                and params.get("state") == [state]
                and params.get("iss") == [origin]
            )
            code = params.get("code", [])
            if matches and len(code) == 1:
                result["code"] = code[0]
            elif matches and params.get("error") == ["access_denied"]:
                result["denied"] = True
            self.send_response(200 if result else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            message = (
                "已收到授权结果，可以关闭此页面。" if result else "无效的授权回调。"
            )
            self.wfile.write(message.encode())

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
        query = urlencode(
            {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": redirect_uri,
                "scope": "publish:read publish:write",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        if not webbrowser.open(f"{origin}/oauth/authorize?{query}"):
            fail("无法打开系统浏览器。")
        typer.echo("请在系统浏览器完成 WispLink 授权。", err=True)
        deadline = time.monotonic() + 180
        server.timeout = 1
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if "code" not in result:
        fail("授权被拒绝或等待超时。")
    return {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }


@config_app.command("set-server")
def set_server(url: str):
    with profile() as config:
        config["server"] = normalize_origin(url)
        save_config(config)
    typer.echo("服务器地址已保存。")


@config_app.command("set-defaults")
def set_defaults(ttl: str = "24h", max_ips: int = typer.Option(10, min=1, max=10000)):
    from .expiry import PRESETS

    if ttl not in PRESETS and ttl != "forever":
        fail("无效的预设时长。")
    with profile() as config:
        config.update(ttl=ttl, max_ips=max_ips)
        save_config(config)
    typer.echo("发布默认值已保存。")


@app.command()
def login():
    with profile() as config:
        origin = configured(config)
        backend = vault()
        previous = credential(backend, origin)
        exchange = browser_code(origin)
        with httpx.Client(base_url=origin, timeout=30) as client:
            data = token_request(client, exchange)
            store(backend, origin, data)
            if previous:
                try:
                    client.post(
                        "/oauth/revoke",
                        data={
                            "client_id": CLIENT_ID,
                            "token": previous["refresh_token"],
                        },
                    ).raise_for_status()
                except httpx.HTTPError:
                    typer.echo("请在后台检查并撤销旧的设备授权。", err=True)
    typer.echo("已授权当前设备。")


@app.command()
def logout():
    with profile() as config:
        origin = configured(config)
        backend = vault()
        data = credential(backend, origin)
        if data:
            try:
                response = httpx.post(
                    origin + "/oauth/revoke",
                    data={"client_id": CLIENT_ID, "token": data["refresh_token"]},
                    timeout=15,
                )
            except httpx.RequestError:
                fail("无法联系服务器撤销授权。连接恢复后重试，或在后台撤销设备。")
            if not response.is_success:
                fail("服务器未确认撤销。请在后台检查授权设备。")
            try:
                backend.delete_password("WispLink CLI", origin)
            except Exception:
                fail("服务器已撤销授权，无法从本机钥匙串移除旧凭证。")
    typer.echo("当前设备已退出。")


def call(config, method, endpoint, **kwargs):
    origin = configured(config)
    backend = vault()
    data = credential(backend, origin)
    if not data:
        fail("请先运行 wisplink login。")
    with httpx.Client(base_url=origin, timeout=120) as client:
        if data["expires_at"] <= time.time() + 30:
            data = store(
                backend,
                origin,
                token_request(
                    client,
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": data["refresh_token"],
                    },
                ),
            )
        try:
            response = client.request(
                method,
                "/api/v1/publishes" + endpoint,
                headers={"Authorization": "Bearer " + data["access_token"]},
                **kwargs,
            )
        except httpx.RequestError:
            fail("无法连接服务器，请检查网络后重试。")
        if response.status_code == 401:
            fail("CLI 授权已失效，请重新运行 wisplink login。")
        if response.status_code == 413:
            fail("HTML 文件超出服务器上传大小限制。")
        if response.status_code == 429:
            fail("请求过于频繁，请稍后重试。")
        try:
            payload = response.json()
        except ValueError:
            fail(f"服务器返回了非预期响应（HTTP {response.status_code}）。")
        if not response.is_success:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            fail(detail if isinstance(detail, str) else "请求失败，请检查参数。")
        return payload


def show(payload, as_json):
    if as_json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    elif "url" in payload:
        typer.echo(payload["url"])
        typer.echo("到期 " + (payload["expires_at"] or "永久"))
        typer.echo("发布 ID " + payload["id"])
        for warning in payload["warnings"]:
            typer.echo(warning, err=True)
    elif "items" in payload:
        for row in payload["items"]:
            typer.echo(f"{row['id']}  {row['status']}  {row['filename']}")
    else:
        typer.echo(
            f"{payload['id']}  {payload['status']}  {payload['expires_at'] or '永久'}"
        )


@app.command()
def publish(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    ttl: str | None = None,
    expires_at: str | None = None,
    max_ips: int | None = typer.Option(None, min=1, max=10000),
    path_note: str | None = None,
    no_path: bool = typer.Option(False, "--no-path"),
    as_json: bool = typer.Option(False, "--json"),
):
    if ttl and expires_at:
        fail("--ttl 和 --expires-at 二选一。")
    if path_note and no_path:
        fail("--path-note 和 --no-path 二选一。")
    with profile() as config:
        expiry = (
            {"at": expires_at}
            if expires_at
            else {"preset": ttl or config.get("ttl", "24h")}
        )
        data = {
            "expiry": json.dumps(expiry),
            "max_ips": max_ips or config.get("max_ips", 10),
        }
        if not no_path:
            data["path_note"] = path_note or str(path.absolute())
        with path.open("rb") as file:
            payload = call(
                config,
                "POST",
                "",
                files={"file": (path.name, file, "text/html")},
                data=data,
            )
    show(payload, as_json)


@app.command("list")
def list_publishes(
    search: str = "",
    offset: int = typer.Option(0, min=0),
    as_json: bool = typer.Option(False, "--json"),
):
    with profile() as config:
        payload = call(config, "GET", "", params={"search": search, "offset": offset})
    show(payload, as_json)


@app.command()
def status(publish_id: str, as_json: bool = typer.Option(False, "--json")):
    with profile() as config:
        payload = call(config, "GET", "/" + publish_id)
    show(payload, as_json)


@app.command()
def close(publish_id: str, as_json: bool = typer.Option(False, "--json")):
    with profile() as config:
        payload = call(config, "POST", "/" + publish_id + "/close")
    show(payload, as_json)
