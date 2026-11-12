from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update

from .db import devices, login_attempts, oauth_codes, sessions, users, write_transaction
from .security import digest, dummy_hash, fingerprint, passwords, token, valid_password
from .service import (
    SESSION_SECONDS,
    USERNAME,
    actor,
    logged,
    now_seconds,
    peer_ip,
    require_admin,
)

router = APIRouter(prefix="/api/v1")


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class NewUser(Login):
    admin: bool = False


class ChangeUser(BaseModel):
    username: str | None = Field(default=None, max_length=80)
    disabled: bool | None = None
    admin: bool | None = None
    password: str | None = Field(default=None, max_length=256)


def public_user(user):
    return {key: user[key] for key in ("id", "username", "role", "disabled")}


def validate_username(username):
    if not USERNAME.fullmatch(username):
        raise HTTPException(
            422, "用户名只能使用字母、数字、点、下划线和连字符，且以字母或数字开头。"
        )


def validate_password(password):
    if len(password) < 12:
        raise HTTPException(422, "密码至少需要 12 个字符。")


@router.post("/session")
def login(request: Request, response: Response, form: Login):
    state = request.app.state
    now = now_seconds()
    identity = fingerprint(state.settings.key, "login", peer_ip(request))
    bucket = now // 300
    with write_transaction(state.engine) as connection:
        count = connection.scalar(
            select(login_attempts.c.attempts).where(
                login_attempts.c.fingerprint == identity,
                login_attempts.c.bucket == bucket,
            )
        )
        if (count or 0) >= 8:
            raise HTTPException(429, "登录请求过多，请稍后重试。")
        if count is None:
            connection.execute(
                insert(login_attempts).values(
                    fingerprint=identity, bucket=bucket, attempts=1
                )
            )
        else:
            connection.execute(
                update(login_attempts)
                .where(
                    login_attempts.c.fingerprint == identity,
                    login_attempts.c.bucket == bucket,
                )
                .values(attempts=count + 1)
            )
        user = (
            connection.execute(select(users).where(users.c.username == form.username))
            .mappings()
            .first()
        )
    good_password = valid_password(
        user["password_hash"] if user else dummy_hash, form.password
    )
    if not user or not good_password or user["disabled"]:
        raise HTTPException(401, "用户名或密码有误。")

    secret = token()
    with write_transaction(state.engine) as connection:
        current = (
            connection.execute(select(users).where(users.c.id == user["id"]))
            .mappings()
            .first()
        )
        if (
            current is None
            or current["disabled"]
            or current["password_hash"] != user["password_hash"]
        ):
            raise HTTPException(401, "用户名或密码有误。")
        previous = request.cookies.get(state.session_cookie)
        if previous:
            connection.execute(
                delete(sessions).where(sessions.c.digest == digest(previous))
            )
        connection.execute(
            insert(sessions).values(
                digest=digest(secret),
                user_id=user["id"],
                expires_at=now + SESSION_SECONDS,
            )
        )
    response.set_cookie(
        state.session_cookie,
        secret,
        max_age=SESSION_SECONDS,
        secure=state.settings.console_origin.startswith("https:"),
        httponly=True,
        samesite="strict",
    )
    return public_user(current)


@router.get("/session")
def session(request: Request):
    with request.app.state.engine.connect() as connection:
        return public_user(actor(connection, request))


@router.delete("/session", status_code=204)
def logout(request: Request, response: Response):
    state = request.app.state
    secret = request.cookies.get(state.session_cookie)
    if secret:
        with write_transaction(state.engine) as connection:
            connection.execute(
                delete(sessions).where(sessions.c.digest == digest(secret))
            )
    response.delete_cookie(
        state.session_cookie,
        secure=state.settings.console_origin.startswith("https:"),
        httponly=True,
        samesite="strict",
    )


@router.get("/admin/users")
def accounts(request: Request):
    with request.app.state.engine.connect() as connection:
        require_admin(actor(connection, request))
        return [
            public_user(row)
            for row in connection.execute(
                select(users)
                .where(users.c.deleted_at.is_(None))
                .order_by(users.c.username)
            ).mappings()
        ]


@router.post("/admin/users", status_code=201)
def add_account(request: Request, form: NewUser):
    engine = request.app.state.engine
    with engine.connect() as connection:
        require_admin(actor(connection, request))
    validate_username(form.username)
    validate_password(form.password)
    user = dict(
        id=uuid4().hex,
        username=form.username,
        password_hash=passwords.hash(form.password),
        role="admin" if form.admin else "publisher",
        disabled=False,
    )
    with write_transaction(engine) as connection:
        admin = actor(connection, request)
        require_admin(admin)
        if connection.scalar(
            select(users.c.id).where(users.c.username == form.username)
        ):
            raise HTTPException(409, "用户名已存在。")
        connection.execute(insert(users).values(**user))
        logged(connection, admin["id"], "user.create", user["id"], now_seconds())
    return public_user(user)


@router.patch("/admin/users/{user_id}")
def edit_account(user_id: str, request: Request, form: ChangeUser):
    engine = request.app.state.engine
    with engine.connect() as connection:
        require_admin(actor(connection, request))
    changes = form.model_dump(exclude_none=True)
    if "username" in changes:
        validate_username(changes["username"])
    if "password" in changes:
        validate_password(changes["password"])
        changes["password_hash"] = passwords.hash(changes.pop("password"))
    if "admin" in changes:
        changes["role"] = "admin" if changes.pop("admin") else "publisher"
    with write_transaction(engine) as connection:
        admin = actor(connection, request)
        require_admin(admin)
        user = (
            connection.execute(select(users).where(users.c.id == user_id))
            .mappings()
            .first()
        )
        if user is None or user["deleted_at"] is not None:
            raise HTTPException(404, "找不到账号。")
        if "username" in changes and connection.scalar(
            select(users.c.id).where(
                users.c.username == changes["username"],
                users.c.id != user_id,
            )
        ):
            raise HTTPException(409, "用户名已存在。")
        if (
            user["role"] == "admin"
            and not user["disabled"]
            and (changes.get("disabled") or changes.get("role") == "publisher")
        ):
            remaining = connection.scalar(
                select(func.count())
                .select_from(users)
                .where(
                    users.c.role == "admin",
                    users.c.disabled.is_(False),
                    users.c.id != user_id,
                )
            )
            if not remaining:
                raise HTTPException(409, "必须保留至少一个启用的管理员。")
        if changes:
            connection.execute(
                update(users).where(users.c.id == user_id).values(**changes)
            )
            if changes.keys() & {"password_hash", "role", "disabled"}:
                connection.execute(
                    delete(sessions).where(sessions.c.user_id == user_id)
                )
                connection.execute(
                    delete(oauth_codes).where(oauth_codes.c.user_id == user_id)
                )
                connection.execute(
                    update(devices)
                    .where(devices.c.user_id == user_id)
                    .values(revoked=True)
                )
            logged(connection, admin["id"], "user.edit", user_id, now_seconds())
        return public_user({**user, **changes})


@router.get("/authorizations")
def authorizations(request: Request):
    with request.app.state.engine.connect() as connection:
        user = actor(connection, request)
        rows = connection.execute(
            select(devices, users.c.username)
            .join(users, users.c.id == devices.c.user_id)
            .where(devices.c.expires_at > now_seconds(), devices.c.revoked.is_(False))
            .order_by(devices.c.last_used_at.desc())
            .where(users.c.id == user["id"] if user["role"] != "admin" else True)
        ).mappings()
        return [dict(row) for row in rows]


@router.delete("/authorizations/{device_id}", status_code=204)
def revoke_device(device_id: str, request: Request):
    with write_transaction(request.app.state.engine) as connection:
        user = actor(connection, request)
        row = (
            connection.execute(select(devices).where(devices.c.id == device_id))
            .mappings()
            .first()
        )
        if row is None or (user["role"] != "admin" and row["user_id"] != user["id"]):
            raise HTTPException(404, "找不到授权设备。")
        connection.execute(
            update(devices).where(devices.c.id == device_id).values(revoked=True)
        )
        logged(connection, user["id"], "oauth.revoke", device_id, now_seconds())


@router.delete("/admin/users/{user_id}", status_code=204)
def delete_account(user_id: str, request: Request):
    with write_transaction(request.app.state.engine) as connection:
        admin = actor(connection, request)
        require_admin(admin)
        user = (
            connection.execute(select(users).where(users.c.id == user_id))
            .mappings()
            .first()
        )
        if user is None or user["deleted_at"] is not None:
            raise HTTPException(404, "找不到账号。")
        if not user["disabled"]:
            raise HTTPException(409, "请先停用账号。")
        now = now_seconds()
        connection.execute(delete(sessions).where(sessions.c.user_id == user_id))
        connection.execute(delete(oauth_codes).where(oauth_codes.c.user_id == user_id))
        connection.execute(delete(devices).where(devices.c.user_id == user_id))
        connection.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(
                username=f"~{user_id}",
                password_hash=dummy_hash,
                deleted_at=now,
            )
        )
        logged(connection, admin["id"], "user.delete", user_id, now)


class ChangePassword(BaseModel):
    current: str = Field(min_length=1, max_length=256)
    replacement: str = Field(min_length=12, max_length=256)


@router.put("/account/password", status_code=204)
def change_password(request: Request, form: ChangePassword):
    engine = request.app.state.engine
    with engine.connect() as connection:
        user = actor(connection, request)
    if not valid_password(user["password_hash"], form.current):
        raise HTTPException(403, "当前密码不正确。")
    replacement = passwords.hash(form.replacement)
    with write_transaction(engine) as connection:
        current = actor(connection, request)
        if current["password_hash"] != user["password_hash"]:
            raise HTTPException(409, "密码已变更，请重新登录。")
        user_id = current["id"]
        connection.execute(
            update(users).where(users.c.id == user_id).values(password_hash=replacement)
        )
        connection.execute(delete(sessions).where(sessions.c.user_id == user_id))
        connection.execute(delete(oauth_codes).where(oauth_codes.c.user_id == user_id))
        connection.execute(
            update(devices).where(devices.c.user_id == user_id).values(revoked=True)
        )
        logged(connection, user_id, "user.password", user_id, now_seconds())
