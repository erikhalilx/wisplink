import json
import re
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749 import ClientMixin, OAuth2Error, grants
from authlib.oauth2.rfc7009 import RevocationEndpoint
from authlib.oauth2.rfc7636 import CodeChallenge
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, abort, g, redirect, render_template_string, request
from sqlalchemy import delete, insert, or_, select, update
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Settings
from .db import database, devices, oauth_codes, oauth_tokens, users, write_transaction
from .security import digest
from .service import logged, now_seconds, session_user

CLIENT_ID = "wisplink-cli"
SCOPES = ("publish:read", "publish:write")
REDIRECT_PATTERN = re.compile(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})/callback\Z")
IDLE_SECONDS = 30 * 86400
AUTH_PARAMS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "scope",
    "state",
    "code_challenge",
    "code_challenge_method",
)


class Client(ClientMixin):
    def get_client_id(self):
        return CLIENT_ID

    def get_default_redirect_uri(self):
        return None

    def get_allowed_scope(self, scope):
        return scope or ""

    def check_redirect_uri(self, redirect_uri):
        match = REDIRECT_PATTERN.fullmatch(redirect_uri)
        return bool(match and int(match[1]) <= 65535)

    def check_client_secret(self, _secret):
        return False

    def check_endpoint_auth_method(self, method, _endpoint):
        return method == "none"

    def check_response_type(self, response_type):
        return response_type == "code"

    def check_grant_type(self, grant_type):
        return grant_type in ("authorization_code", "refresh_token")


class StoredCode(SimpleNamespace):
    def get_redirect_uri(self):
        return self.redirect_uri

    def get_scope(self):
        return self.scope


class StoredToken(SimpleNamespace):
    def check_client(self, client):
        return client.get_client_id() == CLIENT_ID

    def get_scope(self):
        return self.scope


def account(user_id):
    return (
        g.connection.execute(
            select(users).where(users.c.id == user_id, users.c.disabled.is_(False))
        )
        .mappings()
        .first()
    )


def revoke(device_id):
    g.connection.execute(
        update(devices).where(devices.c.id == device_id).values(revoked=True)
    )


def stored_token(predicate):
    row = (
        g.connection.execute(
            select(
                oauth_tokens, devices.c.user_id, devices.c.revoked, devices.c.expires_at
            )
            .join(devices, devices.c.id == oauth_tokens.c.device_id)
            .where(predicate)
        )
        .mappings()
        .first()
    )
    return StoredToken(**row) if row else None


class AuthorizationCode(grants.AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["none"]

    def save_authorization_code(self, code, request):
        g.connection.execute(
            insert(oauth_codes).values(
                digest=digest(code),
                user_id=request.user["id"],
                redirect_uri=request.payload.redirect_uri,
                scope=request.payload.scope,
                code_challenge=request.payload.data["code_challenge"],
                expires_at=now_seconds() + 180,
            )
        )

    def query_authorization_code(self, code, _client):
        row = (
            g.connection.execute(
                select(oauth_codes).where(
                    oauth_codes.c.digest == digest(code),
                    oauth_codes.c.expires_at > now_seconds(),
                )
            )
            .mappings()
            .first()
        )
        return StoredCode(**row, code_challenge_method="S256") if row else None

    def delete_authorization_code(self, code):
        g.connection.execute(
            delete(oauth_codes).where(oauth_codes.c.digest == code.digest)
        )

    def authenticate_user(self, code):
        return account(code.user_id)


class RefreshToken(grants.RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["none"]
    INCLUDE_NEW_REFRESH_TOKEN = True

    def authenticate_refresh_token(self, secret):
        credential = stored_token(oauth_tokens.c.refresh_digest == digest(secret))
        if (
            credential is None
            or credential.revoked
            or credential.expires_at <= now_seconds()
        ):
            return None
        if credential.rotated:
            revoke(credential.device_id)
            logged(
                g.connection,
                credential.user_id,
                "oauth.reuse",
                credential.device_id,
                now_seconds(),
            )
            return None
        return credential

    def authenticate_user(self, credential):
        return account(credential.user_id)

    def revoke_old_credential(self, credential):
        g.connection.execute(
            update(oauth_tokens)
            .where(
                oauth_tokens.c.access_digest == credential.access_digest,
            )
            .values(rotated=True)
        )


class Revocation(RevocationEndpoint):
    CLIENT_AUTH_METHODS = ["none"]

    def query_token(self, secret, _hint):
        key = digest(secret)
        return stored_token(
            or_(
                oauth_tokens.c.access_digest == key,
                oauth_tokens.c.refresh_digest == key,
            )
        )

    def revoke_token(self, credential, _request):
        revoke(credential.device_id)
        logged(
            g.connection,
            credential.user_id,
            "oauth.revoke",
            credential.device_id,
            now_seconds(),
        )


def save_token(token, request):
    from uuid import uuid4

    now = now_seconds()
    user_id = request.user["id"]
    scope = token["scope"]
    if request.payload.grant_type == "refresh_token":
        device_id = request.refresh_token.device_id
        g.connection.execute(
            update(devices)
            .where(devices.c.id == device_id)
            .values(
                scope=scope,
                last_used_at=now,
                expires_at=now + IDLE_SECONDS,
            )
        )
    else:
        device_id = uuid4().hex
        g.connection.execute(
            insert(devices).values(
                id=device_id,
                user_id=user_id,
                scope=scope,
                created_at=now,
                last_used_at=now,
                expires_at=now + IDLE_SECONDS,
                revoked=False,
            )
        )
        logged(g.connection, user_id, "oauth.authorize", device_id, now)
    g.connection.execute(
        insert(oauth_tokens).values(
            access_digest=digest(token["access_token"]),
            refresh_digest=digest(token["refresh_token"]),
            device_id=device_id,
            scope=scope,
            access_expires_at=now + token["expires_in"],
            rotated=False,
        )
    )


CONSENT = """
<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>授权 WispLink CLI</title>
<link rel="icon" type="image/png" sizes="32x32" href="/wisplink-icon-32x32.png">
<style>body{font:16px system-ui;background:#eef5f1;color:#17392e;margin:0;display:grid;place-items:center;min-height:100vh}main{background:white;border:1px solid #d0e1d9;border-radius:14px;padding:2rem;max-width:32rem;margin:1rem}.brand{display:flex;align-items:center;gap:.55rem;font-weight:700}button{font:inherit;padding:.5rem .8rem;margin-right:.5rem;cursor:pointer}</style>
<main><div class="brand"><img src="/wisplink-icon-64x64.png" width="32" height="32" alt="">WispLink</div>
<h1>授权 WispLink CLI</h1><p>当前账号 {{ username }}</p>
<ul>{% if can_read %}<li>查看你的发布记录</li>{% endif %}{% if can_write %}<li>创建和管理你的预览链接</li>{% endif %}</ul>
<form method="post"><input type="hidden" name="proof" value="{{ proof }}">
<button name="decision" value="allow">授权</button><button name="decision" value="deny">拒绝</button></form>
</main></html>
"""


def create_auth_app(settings=None):
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
    app.config.update(
        MAX_CONTENT_LENGTH=8192,
        OAUTH2_SCOPES_SUPPORTED=SCOPES,
        OAUTH2_REFRESH_TOKEN_GENERATOR=True,
        OAUTH2_TOKEN_EXPIRES_IN={"authorization_code": 900, "refresh_token": 900},
    )
    engine = database(settings)
    cipher = Fernet(settings.key)
    cookie_name = (
        "__Host-wisplink_session"
        if settings.console_origin.startswith("https:")
        else "wisplink_session"
    )
    origin = urlsplit(settings.console_origin)
    server = AuthorizationServer(
        app, lambda client_id: Client() if client_id == CLIENT_ID else None, save_token
    )
    server.register_grant(AuthorizationCode, [CodeChallenge(required=True)])
    server.register_grant(RefreshToken)
    server.register_endpoint(Revocation)

    @app.before_request
    def verify_host():
        if request.host != origin.netloc or request.scheme != origin.scheme:
            abort(404)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "strict-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; "
            "form-action 'self' http://127.0.0.1:*; base-uri 'none'"
        )
        return response

    @app.route("/oauth/authorize", methods=["GET", "POST"])
    def authorize():
        if set(request.args) != set(AUTH_PARAMS) or any(
            len(request.args.getlist(k)) != 1 for k in AUTH_PARAMS
        ):
            abort(400)
        values = {key: request.args[key] for key in AUTH_PARAMS}
        if values["code_challenge_method"] != "S256" or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", values["code_challenge"]
        ):
            abort(400)
        scope = values["scope"].split()
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", values["state"])
            or not scope
            or not set(scope) <= set(SCOPES)
        ):
            abort(400)
        secret = request.cookies.get(cookie_name)
        proof_data = json.dumps([digest(secret or ""), values], sort_keys=True).encode()
        if request.method == "GET":
            try:
                server.get_consent_grant()
            except OAuth2Error:
                abort(400)
            with engine.connect() as connection:
                user = session_user(connection, secret)
            if user is None:
                return redirect(
                    "/?"
                    + urlencode({"authorize": "/oauth/authorize?" + urlencode(values)})
                )
            return render_template_string(
                CONSENT,
                username=user["username"],
                proof=cipher.encrypt(proof_data).decode(),
                can_read=SCOPES[0] in scope,
                can_write=SCOPES[1] in scope,
            )
        if request.headers.get("origin") != settings.console_origin:
            abort(403)
        try:
            verified = cipher.decrypt(request.form.get("proof", "").encode(), ttl=300)
        except InvalidToken:
            abort(403)
        if verified != proof_data or request.form.get("decision") not in (
            "allow",
            "deny",
        ):
            abort(403)
        with write_transaction(engine) as connection:
            g.connection = connection
            user = session_user(connection, secret)
            if user is None:
                abort(403)
            try:
                grant = server.get_consent_grant(end_user=user)
            except OAuth2Error:
                abort(400)
            response = server.create_authorization_response(
                grant=grant,
                grant_user=user if request.form["decision"] == "allow" else None,
            )
            if "Location" in response.headers:
                response.headers["Location"] += "&" + urlencode(
                    {"iss": settings.console_origin}
                )
            return response

    @app.post("/oauth/token")
    def exchange():
        if request.args or any(
            len(request.form.getlist(key)) != 1 for key in request.form
        ):
            abort(400)
        with write_transaction(engine) as connection:
            g.connection = connection
            return server.create_token_response()

    @app.post("/oauth/revoke")
    def revoke_token():
        if request.args or any(
            len(request.form.getlist(key)) != 1 for key in request.form
        ):
            abort(400)
        with write_transaction(engine) as connection:
            g.connection = connection
            return server.create_endpoint_response("revocation")

    return app
