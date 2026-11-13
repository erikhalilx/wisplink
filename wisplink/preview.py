import re
from contextlib import closing

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import insert, select, update

from .db import ip_grants, publishes, visitors, write_transaction
from .security import digest, fingerprint, token
from .service import now_seconds, peer_ip, publication_status

router = APIRouter()
TOKEN_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}\Z")
STYLE = """
:root{font:16px system-ui;color:#142f2a;background:#f0f6f3}
body{margin:0;min-height:100vh;display:grid;place-items:center}
main{max-width:34rem;padding:2rem;margin:1rem;background:white;border:1px solid #d0e1d9;border-radius:16px}
h1{margin:0;font-size:1.5rem;overflow-wrap:anywhere}p{color:#48625a}
"""
CONTENT_CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:; "
    "connect-src 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'"
)


def error_page(message, status):
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{message}</title><style>{STYLE}</style>"
        f"<main><h1>{message}</h1></main>",
        status,
        headers={"Content-Security-Policy": CONTENT_CSP},
    )


def unavailable(row, state):
    if row is None:
        return error_page("链接无效。", 404)
    if (
        publication_status(row, now_seconds(), state.settings.uploads / row["id"])
        != "active"
    ):
        return error_page("链接已失效。", 410)
    return None


def lookup(connection, secret):
    if TOKEN_FORMAT.fullmatch(secret):
        return (
            connection.execute(
                select(publishes).where(publishes.c.token_digest == digest(secret))
            )
            .mappings()
            .first()
        )
    return None


@router.head("/p/{secret}")
def preview_metadata(secret: str, request: Request):
    state = request.app.state
    with state.engine.connect() as connection:
        row = lookup(connection, secret)
    error = unavailable(row, state)
    return Response(
        status_code=error.status_code if error else 200,
        media_type="text/html",
        headers={"Content-Security-Policy": CONTENT_CSP},
    )


def stream(file):
    with closing(file):
        while chunk := file.read(64 * 1024):
            yield chunk


@router.get("/p/{secret}")
def open_preview(secret: str, request: Request):
    state = request.app.state
    settings = state.settings
    address = peer_ip(request)
    visitor = request.cookies.get(state.visitor_cookie) or token()
    if not TOKEN_FORMAT.fullmatch(visitor):
        visitor = token()
    file = None
    try:
        with write_transaction(state.engine) as connection:
            row = lookup(connection, secret)
            if error := unavailable(row, state):
                return error
            publish_id = row["id"]
            path = settings.uploads / publish_id
            ip_key = fingerprint(settings.key, f"ip:{publish_id}", address)
            visitor_key = fingerprint(settings.key, f"visitor:{publish_id}", visitor)
            ip_seen = connection.scalar(
                select(ip_grants.c.fingerprint).where(
                    ip_grants.c.publish_id == publish_id,
                    ip_grants.c.fingerprint == ip_key,
                )
            )
            if not ip_seen and row["ip_count"] >= row["max_ips"]:
                return error_page("访问 IP 名额已满。", 403)
            try:
                file = path.open("rb")
            except FileNotFoundError:
                return error_page("预览文件不可用。", 410)
            if not ip_seen:
                connection.execute(
                    insert(ip_grants).values(publish_id=publish_id, fingerprint=ip_key)
                )
            visitor_seen = connection.scalar(
                select(visitors.c.fingerprint).where(
                    visitors.c.publish_id == publish_id,
                    visitors.c.fingerprint == visitor_key,
                )
            )
            if not visitor_seen:
                connection.execute(
                    insert(visitors).values(
                        publish_id=publish_id, fingerprint=visitor_key
                    )
                )
            connection.execute(
                update(publishes)
                .where(publishes.c.id == publish_id)
                .values(
                    pv=row["pv"] + 1,
                    uv=row["uv"] + int(not visitor_seen),
                    ip_count=row["ip_count"] + int(not ip_seen),
                )
            )
    except Exception:
        if file:
            file.close()
        raise
    response = StreamingResponse(
        stream(file),
        media_type="text/html",
        headers={"Content-Security-Policy": CONTENT_CSP},
    )
    response.set_cookie(
        state.visitor_cookie,
        visitor,
        max_age=365 * 86400,
        httponly=True,
        secure=settings.preview_origin.startswith("https:"),
        samesite="lax",
    )
    return response
