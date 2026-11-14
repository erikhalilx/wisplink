import argparse
import getpass
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import delete, insert, select, update

from .config import Settings
from .db import (
    database,
    devices,
    ip_grants,
    login_attempts,
    oauth_codes,
    publishes,
    sessions,
    users,
    visitors,
    write_transaction,
)
from .security import passwords
from .service import USERNAME, logged, now_seconds, publication_status

FILE_ID = re.compile(r"[0-9a-f]{32}\Z")


def cleanup(settings):
    engine = database(settings)
    now = now_seconds()
    with engine.connect() as connection:
        ids = (
            connection.execute(
                select(publishes.c.id).where(publishes.c.purged_at.is_(None))
            )
            .scalars()
            .all()
        )
    for publish_id in ids:
        with write_transaction(engine) as connection:
            row = (
                connection.execute(
                    select(publishes).where(publishes.c.id == publish_id)
                )
                .mappings()
                .first()
            )
            if row is None or row["purged_at"] is not None:
                continue
            path = settings.uploads / publish_id
            status = publication_status(row, now, path)
            if status == "missing":
                connection.execute(
                    update(publishes)
                    .where(publishes.c.id == publish_id)
                    .values(missing=True)
                )
            if status not in ("active", "paused"):
                path.unlink(missing_ok=True)
                connection.execute(
                    delete(ip_grants).where(ip_grants.c.publish_id == publish_id)
                )
                connection.execute(
                    delete(visitors).where(visitors.c.publish_id == publish_id)
                )
                connection.execute(
                    update(publishes)
                    .where(publishes.c.id == publish_id)
                    .values(purged_at=now)
                )
    with write_transaction(engine) as connection:
        connection.execute(delete(sessions).where(sessions.c.expires_at <= now))
        connection.execute(delete(oauth_codes).where(oauth_codes.c.expires_at <= now))
        connection.execute(delete(devices).where(devices.c.expires_at <= now))
        connection.execute(
            delete(login_attempts).where(login_attempts.c.bucket < now // 300 - 1)
        )
        if settings.uploads.is_dir():
            for path in settings.uploads.iterdir():
                if FILE_ID.fullmatch(path.name) and not connection.scalar(
                    select(publishes.c.id).where(publishes.c.id == path.name)
                ):
                    path.unlink(missing_ok=True)


def backup(settings, destination):
    source = settings.data_dir / "wisplink.sqlite3"
    if not source.is_file():
        raise FileNotFoundError(source)
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with (
            closing(sqlite3.connect(source)) as primary,
            closing(sqlite3.connect(destination)) as copy,
        ):
            primary.backup(copy)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-key")
    sub.add_parser("migrate")
    sub.add_parser("cleanup")
    sub.add_parser("reconcile")
    snapshot = sub.add_parser("backup")
    snapshot.add_argument("destination", type=Path)
    init = sub.add_parser("create-admin")
    init.add_argument("username")
    args = parser.parse_args()
    if args.command == "generate-key":
        print(Fernet.generate_key().decode())
        return
    settings = Settings.from_env()
    if args.command == "migrate":
        from alembic import command
        from alembic.config import Config

        settings.uploads.mkdir(parents=True, mode=0o700, exist_ok=True)
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).with_name("migrations"))
        )
        command.upgrade(config, "head")
        return
    if args.command == "backup":
        backup(settings, args.destination)
        return
    if args.command == "reconcile":
        with write_transaction(database(settings)) as connection:
            connection.execute(delete(sessions))
            connection.execute(delete(oauth_codes))
            connection.execute(update(devices).values(revoked=True))
    if args.command in ("cleanup", "reconcile"):
        cleanup(settings)
        return
    if not USERNAME.fullmatch(args.username):
        parser.error("Invalid username.")
    password = getpass.getpass("Administrator password: ")
    if not 12 <= len(password) <= 256 or password != getpass.getpass(
        "Confirm password: "
    ):
        parser.error("Passwords must match and contain 12–256 characters.")
    encoded = passwords.hash(password)
    with write_transaction(database(settings)) as connection:
        if connection.scalar(
            select(users.c.id).where(users.c.username == args.username)
        ):
            parser.error("Username already exists.")
        user_id = uuid4().hex
        connection.execute(
            insert(users).values(
                id=user_id,
                username=args.username,
                password_hash=encoded,
                role="admin",
                disabled=False,
            )
        )
        logged(connection, None, "admin.bootstrap", user_id, now_seconds())


if __name__ == "__main__":
    main()
