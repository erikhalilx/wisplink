import re
from contextlib import closing
from html import escape
from typing import Annotated

from fastapi import APIRouter, Form, Request
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
button{font:inherit;font-weight:650;border:0;background:#075a45;color:white;padding:.8rem 1.2rem;border-radius:8px;cursor:pointer}
iframe{position:fixed;inset:0;width:100%;height:100%;border:0;background:white}
"""
CONTENT_CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:; "
    "connect-src 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; "
    "base-uri 'none'; frame-ancestors 'self'"
)


def page(title, body, status=200, nonce=None):
    csp = (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; "
        "form-action 'self'; frame-src 'self'; base-uri 'none'"
    )
    if nonce:
        csp += f"; script-src 'nonce-{nonce}'"
    html = (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}</style>{body}</html>"
    )
    return HTMLResponse(
        html,
        status,
        headers={"Content-Security-Policy": csp, "Referrer-Policy": "strict-origin"},
    )


def unavailable(row, state):
    if row is None:
        return page("链接无效", "<main><h1>链接无效</h1></main>", 404)
    if (
        publication_status(row, now_seconds(), state.settings.uploads / row["id"])
        != "active"
    ):
        return page("链接已失效", "<main><h1>链接已失效</h1></main>", 410)
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


@router.api_route("/p/{secret}", methods=["GET", "HEAD"])
def landing(secret: str, request: Request):
    state = request.app.state
    with state.engine.connect() as connection:
        row = lookup(connection, secret)
    if error := unavailable(row, state):
        return error
    nonce = token()
    challenge = state.cipher.encrypt(f"preview:{row['id']}".encode()).decode()
    title = escape(row["filename"])
    return page(
        row["filename"],
        f"""
      <main id="prompt"><h1>{title}</h1><p>打开预览会登记当前公网 IP。</p>
      <form method="post" target="preview"><input type="hidden" name="challenge" value="{challenge}">
      <button>打开预览</button></form></main>
      <iframe name="preview" id="preview" title="{title}" sandbox="allow-scripts" hidden></iframe>
      <script nonce="{nonce}">
        const frame = document.getElementById('preview');
        document.querySelector('form').addEventListener('submit', () => {{
          frame.addEventListener('load', () => {{
            frame.hidden = false;
            document.getElementById('prompt').hidden = true;
          }}, {{once:true}});
        }});
      </script>
    """,
        nonce=nonce,
    )


def content_error(message, status):
    return HTMLResponse(
        f'<!doctype html><meta charset="utf-8"><style>{STYLE}</style><main><h1>{escape(message)}</h1></main>',
        status,
        headers={"Content-Security-Policy": CONTENT_CSP},
    )


def stream(file):
    with closing(file):
        while chunk := file.read(64 * 1024):
            yield chunk


@router.post("/p/{secret}")
def open_preview(
    secret: str, request: Request, challenge: Annotated[str, Form(max_length=512)]
):
    from cryptography.fernet import InvalidToken

    state = request.app.state
    settings = state.settings
    if request.headers.get("origin") != settings.preview_origin:
        return content_error("请通过预览入口打开。", 403)
    try:
        proof = state.cipher.decrypt(challenge.encode(), ttl=3600).decode()
    except InvalidToken:
        return content_error("请刷新链接后再试。", 403)
    address = peer_ip(request)
    visitor = request.cookies.get(state.visitor_cookie) or token()
    if not TOKEN_FORMAT.fullmatch(visitor):
        visitor = token()
    file = None
    try:
        with write_transaction(state.engine) as connection:
            row = lookup(connection, secret)
            if row is None or proof != f"preview:{row['id']}":
                return content_error("链接无效。", 404)
            publish_id = row["id"]
            path = settings.uploads / publish_id
            if publication_status(row, now_seconds(), path) != "active":
                return content_error("链接已失效。", 410)
            ip_key = fingerprint(settings.key, f"ip:{publish_id}", address)
            visitor_key = fingerprint(settings.key, f"visitor:{publish_id}", visitor)
            ip_seen = connection.scalar(
                select(ip_grants.c.fingerprint).where(
                    ip_grants.c.publish_id == publish_id,
                    ip_grants.c.fingerprint == ip_key,
                )
            )
            if not ip_seen and row["ip_count"] >= row["max_ips"]:
                return content_error("访问 IP 名额已满。", 403)
            try:
                file = path.open("rb")
            except FileNotFoundError:
                return content_error("预览文件不可用。", 410)
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
