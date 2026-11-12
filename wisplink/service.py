import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy import select

from .db import audit, devices, oauth_tokens, preferences, publishes, sessions, users
from .security import canonical_ip, digest

USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
SESSION_SECONDS = 12 * 3600


def now_seconds() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def logged(connection, actor, action, target, now):
    connection.execute(
        audit.insert().values(
            actor_id=actor, action=action, target_id=target, created_at=now
        )
    )


def session_user(connection, secret):
    if not secret:
        return None
    return (
        connection.execute(
            select(users)
            .join(sessions, sessions.c.user_id == users.c.id)
            .where(
                sessions.c.digest == digest(secret),
                sessions.c.expires_at > now_seconds(),
                users.c.disabled.is_(False),
            )
        )
        .mappings()
        .first()
    )


def actor(connection, request: Request):
    authorization = request.headers.get("authorization", "")
    if cli_route(request) and authorization.startswith("Bearer "):
        required_scope = "publish:read" if request.method == "GET" else "publish:write"
        now = now_seconds()
        credential = (
            connection.execute(
                select(users, oauth_tokens.c.scope)
                .join(devices, devices.c.user_id == users.c.id)
                .join(oauth_tokens, oauth_tokens.c.device_id == devices.c.id)
                .where(
                    oauth_tokens.c.access_digest == digest(authorization[7:]),
                    oauth_tokens.c.access_expires_at > now,
                    oauth_tokens.c.rotated.is_(False),
                    devices.c.expires_at > now,
                    devices.c.revoked.is_(False),
                    users.c.disabled.is_(False),
                )
            )
            .mappings()
            .first()
        )
        if credential is None:
            raise HTTPException(401, "CLI 授权已失效。")
        if required_scope not in credential["scope"].split():
            raise HTTPException(403, "CLI 授权范围不足。")
        return {**credential, "role": "publisher"}
    user = session_user(
        connection, request.cookies.get(request.app.state.session_cookie)
    )
    if user is None:
        raise HTTPException(401, "会话已失效，请重新登录。")
    return user


def cli_route(request: Request) -> bool:
    path = request.url.path
    return path == "/api/v1/publishes" or path.startswith("/api/v1/publishes/")


def require_admin(user):
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限。")


def owned(connection, publish_id, user):
    row = (
        connection.execute(select(publishes).where(publishes.c.id == publish_id))
        .mappings()
        .first()
    )
    if row is None or (row["owner_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "找不到发布记录。")
    return row


def publication_status(row, now, path: Path | None = None):
    if row["closed_at"] is not None:
        return "closed"
    if row["expires_at"] is not None and row["expires_at"] <= now:
        return "expired"
    if row["missing"] or (path is not None and not path.is_file()):
        return "missing"
    return "active"


def max_days(connection):
    return connection.scalar(
        select(preferences.c.value).where(preferences.c.name == "max_days")
    )


def peer_ip(request: Request):
    try:
        return canonical_ip(request.client.host if request.client else "")
    except ValueError:
        raise HTTPException(400, "无法识别访问来源。") from None


class DependencyCheck(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external = False
        self.forms = False
        self.nested_frames = False
        self.saw_markup = False

    def handle_starttag(self, tag, attrs):
        self.saw_markup = True
        self.forms |= tag == "form"
        self.nested_frames |= tag in ("frame", "iframe")
        for attr, value in attrs:
            if attr in ("src", "href", "poster", "action") and value:
                cleaned = value.strip()
                if cleaned and not cleaned.lower().startswith(("#", "data:")):
                    self.external = True

    def warnings(self):
        warnings = []
        if self.external:
            warnings.append("检测到非内嵌资源或链接。预览将限制外部资源和导航。")
        if self.forms:
            warnings.append("表单可用于页内交互，提交会被阻止。")
        if self.nested_frames:
            warnings.append("嵌套 iframe 会被阻止。")
        return warnings


def inspect_html(filename, content_type, data, size_limit):
    if not filename.lower().endswith((".html", ".htm")):
        raise HTTPException(422, "请选择 .html 或 .htm 文件。")
    if content_type and content_type.split(";", 1)[0] not in (
        "text/html",
        "application/octet-stream",
    ):
        raise HTTPException(422, "上传的文件类型须为 HTML。")
    if len(data) > size_limit:
        raise HTTPException(413, "HTML 文件超出大小限制。")
    try:
        document = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "请将 HTML 保存为 UTF-8。") from None
    checker = DependencyCheck()
    checker.feed(document)
    checker.close()
    if not checker.saw_markup or "\0" in document:
        raise HTTPException(422, "文件没有可识别的 HTML 内容。")
    return checker.warnings()


def store_file(path, data):
    file = open(path, "xb", opener=private_opener)
    try:
        with file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def private_opener(path, flags):
    return os.open(path, flags, 0o600)
