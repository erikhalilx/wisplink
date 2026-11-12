from contextlib import contextmanager

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
)

metadata = MetaData()
users = Table(
    "users",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("username", String(80), unique=True, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", String(20), nullable=False),
    Column("disabled", Boolean, nullable=False),
    Column("deleted_at", Integer),
)
sessions = Table(
    "web_sessions",
    metadata,
    Column("digest", String(64), primary_key=True),
    Column(
        "user_id",
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("expires_at", Integer, nullable=False),
)
publishes = Table(
    "publishes",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("filename", Text, nullable=False),
    Column("path_note", Text),
    Column("token_digest", String(64), unique=True, nullable=False),
    Column("encrypted_token", LargeBinary, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer),
    Column("closed_at", Integer),
    Column("purged_at", Integer),
    Column("missing", Boolean, nullable=False),
    Column("size", Integer, nullable=False),
    Column("max_ips", Integer, nullable=False),
    Column("pv", Integer, nullable=False),
    Column("uv", Integer, nullable=False),
    Column("ip_count", Integer, nullable=False),
)
Index("ix_publishes_expiry", publishes.c.expires_at)
ip_grants = Table(
    "publish_ip_grants",
    metadata,
    Column(
        "publish_id", ForeignKey("publishes.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("fingerprint", String(64), primary_key=True),
)
visitors = Table(
    "publish_visitors",
    metadata,
    Column(
        "publish_id", ForeignKey("publishes.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("fingerprint", String(64), primary_key=True),
)
audit = Table(
    "audit_logs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("actor_id", String(32)),
    Column("action", String(40), nullable=False),
    Column("target_id", String(32)),
    Column("created_at", Integer, nullable=False),
)
preferences = Table(
    "preferences",
    metadata,
    Column("name", String(60), primary_key=True),
    Column("value", Integer, nullable=False),
)
login_attempts = Table(
    "login_attempts",
    metadata,
    Column("fingerprint", String(64), primary_key=True),
    Column("bucket", Integer, primary_key=True),
    Column("attempts", Integer, nullable=False),
)


def database(settings):
    engine = create_engine(settings.database_url)

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    return engine


@contextmanager
def write_transaction(engine):
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        yield connection
        connection.commit()


oauth_codes = Table(
    "oauth_codes",
    metadata,
    Column("digest", String(64), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("redirect_uri", Text, nullable=False),
    Column("scope", Text, nullable=False),
    Column("code_challenge", String(128), nullable=False),
    Column("expires_at", Integer, nullable=False),
)
devices = Table(
    "oauth_devices",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("scope", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("last_used_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=False),
    Column("revoked", Boolean, nullable=False),
)
oauth_tokens = Table(
    "oauth_tokens",
    metadata,
    Column("access_digest", String(64), primary_key=True),
    Column("refresh_digest", String(64), unique=True, nullable=False),
    Column(
        "device_id",
        ForeignKey("oauth_devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("scope", Text, nullable=False),
    Column("access_expires_at", Integer, nullable=False),
    Column("rotated", Boolean, nullable=False),
)
