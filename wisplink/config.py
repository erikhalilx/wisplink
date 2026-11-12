import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    key: bytes
    console_origin: str = "http://localhost:5173"
    preview_origin: str = "http://127.0.0.1:8000"
    max_upload_bytes: int = 10 * 1024 * 1024
    active_limit: int = 50
    storage_limit_bytes: int = 256 * 1024 * 1024
    hourly_limit: int = 30

    def __post_init__(self):
        Fernet(self.key)
        for origin in (self.console_origin, self.preview_origin):
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Origins must be HTTP(S) URLs without a path.")
            if parsed.scheme == "http" and parsed.hostname not in (
                "localhost",
                "127.0.0.1",
                "::1",
            ):
                raise ValueError("Public origins require HTTPS.")
        if (
            urlsplit(self.console_origin).hostname
            == urlsplit(self.preview_origin).hostname
        ):
            raise ValueError("Console and preview must use distinct hostnames.")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'wisplink.sqlite3'}"

    @property
    def uploads(self) -> Path:
        return self.data_dir / "uploads"

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("WISPLINK_DATA_DIR", "data")).resolve(),
            key=os.environ["WISPLINK_KEY"].encode(),
            console_origin=os.getenv("WISPLINK_CONSOLE_ORIGIN", cls.console_origin),
            preview_origin=os.getenv("WISPLINK_PREVIEW_ORIGIN", cls.preview_origin),
        )
