from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import case, delete, func, insert, select, update

from .db import audit, devices, preferences, publishes, users, write_transaction
from .expiry import PRESETS, ExpiryChoice, timestamp
from .security import device_label, digest, token
from .service import (
    actor,
    inspect_html,
    logged,
    max_days,
    now_seconds,
    owned,
    publication_status,
    require_admin,
    store_file,
)

router = APIRouter(prefix="/api/v1")


class PublishPolicy(BaseModel):
    max_days: int | None = Field(default=None, ge=1, le=36500)
    max_upload_mb: int | None = Field(default=None, ge=1, le=50)
    active_limit: int | None = Field(default=None, ge=1, le=10000)
    storage_limit_mb: int | None = Field(default=None, ge=1, le=100000)
    hourly_limit: int | None = Field(default=None, ge=1, le=1000)
    default_ips: int | None = Field(default=None, ge=1, le=10000)
    default_preset: str | None = Field(default=None, max_length=8)


def publish_policy(connection, settings):
    stored = {
        name: value
        for name, value in connection.execute(
            select(preferences.c.name, preferences.c.value)
        )
    }
    preset_by_seconds = {seconds: preset for preset, seconds in PRESETS.items()}
    preset_by_seconds[0] = "forever"
    return {
        "max_days": stored.get("max_days"),
        "max_upload_mb": stored.get(
            "max_upload_mb", settings.max_upload_bytes // 1048576
        ),
        "active_limit": stored.get("active_limit", settings.active_limit),
        "storage_limit_mb": stored.get(
            "storage_limit_mb", settings.storage_limit_bytes // 1048576
        ),
        "hourly_limit": stored.get("hourly_limit", settings.hourly_limit),
        "default_ips": stored.get("default_ips", 10),
        "default_preset": preset_by_seconds.get(stored.get("default_preset"), "24h"),
    }


def resolve_expiry(choice, now, created_at, limit):
    try:
        return choice.resolve(now, created_at, limit)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def public_record(row, state, now):
    result = {
        key: row[key]
        for key in (
            "id",
            "owner_id",
            "filename",
            "device_name",
            "agent_name",
            "path_note",
            "size",
            "max_ips",
            "ip_count",
            "pv",
            "uv",
        )
    }
    result["created_at"] = timestamp(row["created_at"])
    result["expires_at"] = timestamp(row["expires_at"])
    result["remaining_seconds"] = (
        max(0, row["expires_at"] - now) if row["expires_at"] is not None else None
    )
    result["status"] = publication_status(row, now, state.settings.uploads / row["id"])
    result["source"] = "cli" if row.get("source_cli") else "web" if row.get("source_cli") is False else "unknown"
    result["purged"] = row["purged_at"] is not None
    if "username" in row:
        result["owner"] = (
            row["username"] if not row["username"].startswith("~") else "已删除账号"
        )
    return result


@router.get("/settings")
def read_settings(request: Request):
    with request.app.state.engine.connect() as connection:
        actor(connection, request)
        return publish_policy(connection, request.app.state.settings)


@router.put("/settings")
def save_settings(request: Request, form: PublishPolicy):
    state = request.app.state
    with write_transaction(state.engine) as connection:
        user = actor(connection, request)
        require_admin(user)
        values = form.model_dump(exclude_unset=True)
        if values.get("default_preset") is not None:
            preset = values["default_preset"]
            if preset != "forever" and preset not in PRESETS:
                raise HTTPException(422, "无效的默认时长。")
            values["default_preset"] = PRESETS.get(preset, 0)
        for key, value in values.items():
            connection.execute(delete(preferences).where(preferences.c.name == key))
            if value is not None:
                connection.execute(insert(preferences).values(name=key, value=value))
        policy = publish_policy(connection, state.settings)
        if policy["max_days"] is not None and (
            policy["default_preset"] == "forever"
            or PRESETS[policy["default_preset"]] > policy["max_days"] * 86400
        ):
            raise HTTPException(422, "默认时长超出累计有效期上限。")
        logged(connection, user["id"], "settings.update", None, now_seconds())
    return policy


@router.post("/publishes", status_code=201)
def publish(
    request: Request,
    file: Annotated[UploadFile, File()],
    expiry: Annotated[str, Form(max_length=256)],
    max_ips: Annotated[int, Form(ge=1, le=10000)] = 10,
    path_note: Annotated[str | None, Form(max_length=4096)] = None,
    device_name: Annotated[str | None, Form(max_length=120)] = None,
    device_model: Annotated[str | None, Form(max_length=120)] = None,
    agent_name: Annotated[str | None, Form(max_length=120)] = None,
):
    state = request.app.state
    settings = state.settings
    with state.engine.connect() as connection:
        actor(connection, request)
        size_limit = publish_policy(connection, settings)["max_upload_mb"] * 1048576
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
    if len(filename) > 255:
        raise HTTPException(422, "文件名过长。")
    data = file.file.read(size_limit + 1)
    warnings = inspect_html(filename, file.content_type, data, size_limit)
    try:
        choice = ExpiryChoice.model_validate_json(expiry)
    except ValidationError as error:
        raise HTTPException(422, "请选择有效期，或填写带时区的到期时间。") from error
    publish_id = uuid4().hex
    secret = token()
    path = settings.uploads / publish_id
    stored = False
    try:
        with write_transaction(state.engine) as connection:
            user = actor(connection, request)
            now = now_seconds()
            policy = publish_policy(connection, settings)
            expiry_at = resolve_expiry(choice, now, now, policy["max_days"])
            if len(data) > policy["max_upload_mb"] * 1048576:
                raise HTTPException(413, "HTML 文件超出大小限制。")
            same_owner = publishes.c.owner_id == user["id"]
            hour_count = connection.scalar(
                select(func.count())
                .select_from(audit)
                .where(
                    audit.c.actor_id == user["id"],
                    audit.c.action == "publish.create",
                    audit.c.created_at > now - 3600,
                )
            )
            if hour_count >= policy["hourly_limit"]:
                raise HTTPException(429, "达到每小时发布上限。")
            active_count = count_active(connection, user["id"], now)
            size = connection.scalar(
                select(func.coalesce(func.sum(publishes.c.size), 0)).where(
                    same_owner,
                    publishes.c.purged_at.is_(None),
                    publishes.c.missing.is_(False),
                )
            )
            if (
                active_count >= policy["active_limit"]
                or size + len(data) > policy["storage_limit_mb"] * 1048576
            ):
                raise HTTPException(409, "达到账号的发布数量或空间上限。")
            device_id = user.get("device_id")
            identity = {}
            if device_id:
                identity = {
                    key: device_label(value)
                    for key, value in (
                        ("device_name", device_name), ("device_model", device_model), ("agent_name", agent_name)
                    )
                }
                connection.execute(
                    update(devices).where(devices.c.id == device_id).values(
                        last_used_at=now, **{key: value for key, value in identity.items() if value}
                    )
                )
            row = dict(
                id=publish_id,
                owner_id=user["id"],
                filename=filename,
                path_note=path_note,
                source_cli=bool(device_id),
                device_name=identity.get("device_name") or user.get("device_name"),
                agent_name=identity.get("agent_name"),
                paused_at=None,
                token_digest=digest(secret),
                encrypted_token=state.cipher.encrypt(secret.encode()),
                created_at=now,
                expires_at=expiry_at,
                closed_at=None,
                purged_at=None,
                missing=False,
                size=len(data),
                max_ips=max_ips,
                pv=0,
                uv=0,
                ip_count=0,
            )
            store_file(path, data)
            stored = True
            connection.execute(insert(publishes).values(**row))
            logged(connection, user["id"], "publish.create", publish_id, now)
    except BaseException:
        if stored:
            path.unlink(missing_ok=True)
        raise
    return {
        **public_record(row, state, now),
        "url": f"{settings.preview_origin}/p/{secret}",
        "warnings": warnings,
    }


@router.get("/publishes")
def list_publishes(
    request: Request,
    search: str = Query(default="", max_length=255),
    status: Literal["active", "paused", "expired", "closed", "missing"] | None = None,
    source: Literal["web", "cli", "unknown"] | None = None,
    agent_name: str = Query(default="", max_length=120),
    device_name: str = Query(default="", max_length=120),
    owner: str = Query(default="", max_length=80),
    sort: Literal["newest", "oldest", "expires", "views"] = "newest",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    state = request.app.state
    with state.engine.connect() as connection:
        user = actor(connection, request)
        statement = select(publishes, users.c.username).join(
            users, users.c.id == publishes.c.owner_id
        )
        if user["role"] != "admin":
            statement = statement.where(publishes.c.owner_id == user["id"])
        now = now_seconds()
        if status:
            statement = statement.where(status_expression(now) == status)
        if search:
            statement = statement.where(
                publishes.c.filename.contains(search, autoescape=True)
            )
        for term, column in (
            (agent_name, publishes.c.agent_name), (device_name, publishes.c.device_name),
            (owner, users.c.username),
        ):
            if term:
                statement = statement.where(column.contains(term, autoescape=True))
        if source:
            source_cli = {"cli": True, "web": False, "unknown": None}[source]
            statement = statement.where(publishes.c.source_cli.is_(source_cli))
        order = {
            "newest": publishes.c.created_at.desc(),
            "oldest": publishes.c.created_at.asc(),
            "expires": publishes.c.expires_at.asc().nulls_last(),
            "views": publishes.c.pv.desc(),
        }[sort]
        total = connection.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (
            connection.execute(
                statement.order_by(order, publishes.c.id)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return {
            "items": [public_record(row, state, now) for row in rows],
            "total": total,
            "has_more": offset + len(rows) < total,
        }


@router.get("/publishes/{publish_id}")
def detail(publish_id: str, request: Request):
    state = request.app.state
    with state.engine.connect() as connection:
        return public_record(
            owned(connection, publish_id, actor(connection, request)),
            state,
            now_seconds(),
        )


@router.get("/publishes/{publish_id}/link")
def copy_link(publish_id: str, request: Request):
    state = request.app.state
    with state.engine.connect() as connection:
        row = owned(connection, publish_id, actor(connection, request))
        secret = state.cipher.decrypt(row["encrypted_token"]).decode()
        return {"url": f"{state.settings.preview_origin}/p/{secret}"}


@router.put("/publishes/{publish_id}/expiry")
def edit_expiry(publish_id: str, request: Request, form: ExpiryChoice):
    state = request.app.state
    with write_transaction(state.engine) as connection:
        user = actor(connection, request)
        row = owned(connection, publish_id, user)
        now = now_seconds()
        if (
            publication_status(row, now, state.settings.uploads / publish_id)
            != "active"
        ):
            raise HTTPException(409, "只有有效链接可以修改到期时间。")
        expires_at = resolve_expiry(form, now, row["created_at"], max_days(connection))
        connection.execute(
            update(publishes)
            .where(publishes.c.id == publish_id)
            .values(expires_at=expires_at)
        )
        logged(connection, user["id"], "publish.expiry", publish_id, now)
        return public_record({**row, "expires_at": expires_at}, state, now)


class ResumeOptions(BaseModel):
    expiry: ExpiryChoice
    max_ips: int = Field(ge=1, le=10000)


class BatchOptions(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    action: Literal["pause", "resume", "close", "delete"]
    resume: ResumeOptions | None = None


def count_active(connection, owner_id, now):
    return connection.scalar(
        select(func.count()).select_from(publishes).where(
            publishes.c.owner_id == owner_id, status_expression(now) == "active"
        )
    )


def change_publication(connection, state, user, publish_id, action, now, options=None):
    row = owned(connection, publish_id, user)
    status = publication_status(row, now, state.settings.uploads / publish_id)
    if action == "pause" and status == "active":
        values = {"paused_at": now}
    elif action == "resume" and status == "paused" and options is not None:
        if options.max_ips < row["ip_count"]:
            raise HTTPException(422, "IP 名额不能低于已登记的 IP 数。")
        policy = publish_policy(connection, state.settings)
        if count_active(connection, row["owner_id"], now) >= policy["active_limit"]:
            raise HTTPException(409, "达到账号的有效发布上限。")
        values = {
            "paused_at": None,
            "max_ips": options.max_ips,
            "expires_at": resolve_expiry(options.expiry, now, row["created_at"], policy["max_days"]),
        }
    elif action == "close" and status in ("active", "paused"):
        values = {"closed_at": now, "paused_at": None}
    elif action == "close":
        return public_record(row, state, now)
    elif action == "delete" and status not in ("active", "paused"):
        connection.execute(delete(publishes).where(publishes.c.id == publish_id))
        logged(connection, user["id"], "publish.delete", publish_id, now)
        return None
    else:
        raise HTTPException(409, "发布状态已变化，或不支持此操作。")
    connection.execute(update(publishes).where(publishes.c.id == publish_id).values(**values))
    logged(connection, user["id"], f"publish.{action}", publish_id, now)
    return public_record({**row, **values}, state, now)


def apply_changes(request, ids, action, options=None):
    state = request.app.state
    ids = list(dict.fromkeys(ids))
    with write_transaction(state.engine) as connection:
        user = actor(connection, request)
        now = now_seconds()
        rows = [
            change_publication(connection, state, user, publish_id, action, now, options)
            for publish_id in ids
        ]
    if action == "delete":
        # Cleanup removes any orphaned file if unlinking fails after committing.
        for publish_id in ids:
            try:
                (state.settings.uploads / publish_id).unlink(missing_ok=True)
            except OSError:
                pass
    return rows


@router.post("/publishes/batch")
def batch(request: Request, form: BatchOptions):
    if form.action == "resume" and form.resume is None:
        raise HTTPException(422, "请为恢复发布设置有效期和 IP 名额。")
    rows = apply_changes(request, form.ids, form.action, form.resume)
    return {"updated": len(rows)}


@router.post("/publishes/{publish_id}/pause")
def pause(publish_id: str, request: Request):
    return apply_changes(request, [publish_id], "pause")[0]


@router.post("/publishes/{publish_id}/resume")
def resume(publish_id: str, request: Request, form: ResumeOptions):
    return apply_changes(request, [publish_id], "resume", form)[0]


@router.post("/publishes/{publish_id}/close")
def close(publish_id: str, request: Request):
    return apply_changes(request, [publish_id], "close")[0]


@router.delete("/publishes/{publish_id}", status_code=204)
def delete_record(publish_id: str, request: Request):
    apply_changes(request, [publish_id], "delete")


def status_expression(now):
    return case(
        (publishes.c.closed_at.is_not(None), "closed"),
        (
            publishes.c.paused_at.is_not(None),
            case((publishes.c.missing.is_(True), "missing"), else_="paused"),
        ),
        (publishes.c.expires_at <= now, "expired"),
        (publishes.c.missing.is_(True), "missing"),
        else_="active",
    )


@router.get("/overview")
def overview(request: Request):
    with request.app.state.engine.connect() as connection:
        user = actor(connection, request)
        now = now_seconds()
        allowed = (
            publishes.c.owner_id == user["id"] if user["role"] != "admin" else True
        )
        status = status_expression(now)
        totals = (
            connection.execute(
                select(
                    func.count().label("total"),
                    func.coalesce(
                        func.sum(case((status == "active", 1), else_=0)), 0
                    ).label("active"),
                    func.coalesce(func.sum(case((status == "paused", 1), else_=0)), 0).label("paused"),
                    func.coalesce(func.sum(publishes.c.pv), 0).label("pv"),
                    func.coalesce(func.sum(publishes.c.uv), 0).label("uv"),
                ).where(allowed)
            )
            .mappings()
            .one()
        )
        recent = (
            connection.execute(
                select(publishes)
                .where(allowed)
                .order_by(publishes.c.created_at.desc(), publishes.c.id)
                .limit(6)
            )
            .mappings()
            .all()
        )
    return {
        **totals,
        "recent": [public_record(row, request.app.state, now) for row in recent],
    }


@router.get("/publishes/{publish_id}/stats")
def stats(publish_id: str, request: Request):
    with request.app.state.engine.connect() as connection:
        row = owned(connection, publish_id, actor(connection, request))
        return {key: row[key] for key in ("pv", "uv", "ip_count", "max_ips")}
