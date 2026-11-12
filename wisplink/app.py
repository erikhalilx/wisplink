from importlib.metadata import version
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import account, preview, publication
from .config import Settings
from .db import database
from .service import cli_route


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.cipher = Fernet(settings.key)
    app.state.engine = database(settings)
    app.state.session_cookie = (
        "__Host-wisplink_session"
        if settings.console_origin.startswith("https:")
        else "wisplink_session"
    )
    app.state.visitor_cookie = (
        "__Host-wisplink_visitor"
        if settings.preview_origin.startswith("https:")
        else "wisplink_visitor"
    )
    console_host = urlsplit(settings.console_origin).netloc
    preview_host = urlsplit(settings.preview_origin).netloc

    @app.middleware("http")
    async def enforce_hosts(request: Request, call_next):
        host = request.headers.get("host")
        path = request.url.path
        console_request = host == console_host and path.startswith("/api/v1/")
        preview_request = host == preview_host and path.startswith("/p/")
        if not (console_request or preview_request):
            response = JSONResponse({"detail": "找不到页面。"}, status_code=404)
        elif (
            console_request
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and (
                request.headers.get("origin") != settings.console_origin
                and not (
                    cli_route(request)
                    and request.headers.get("authorization", "").startswith("Bearer ")
                )
            )
        ):
            response = JSONResponse({"detail": "请求来源无效。"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers["X-Content-Type-Options"] = "nosniff"
        if preview_request:
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        else:
            response.headers["X-Frame-Options"] = "DENY"
        return response

    app.include_router(account.router)
    app.include_router(publication.router)
    app.include_router(preview.router)

    @app.get("/api/v1/instance")
    def instance():
        return {
            "product": "wisplink",
            "version": version("wisplink"),
            "api_version": 1,
            "console_origin": settings.console_origin,
        }

    return app
