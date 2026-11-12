from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from wisplink.app import create_app
from wisplink.config import Settings
from wisplink.db import users, write_transaction
from wisplink.security import passwords

CONSOLE = "https://console.test"
PREVIEW = "https://preview.test"
PASSWORD = "test-password-only"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = Settings(tmp_path, Fernet.generate_key(), CONSOLE, PREVIEW)
    monkeypatch.setenv("WISPLINK_KEY", settings.key.decode())
    monkeypatch.setenv("WISPLINK_DATA_DIR", str(tmp_path))
    settings.uploads.mkdir()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    app = create_app(settings)
    with write_transaction(app.state.engine) as connection:
        connection.execute(
            users.insert().values(
                id="admin",
                username="admin",
                password_hash=passwords.hash(PASSWORD),
                role="admin",
                disabled=False,
            )
        )
    with TestClient(
        app, base_url=CONSOLE, client=("192.0.2.100", 1234), headers={"Origin": CONSOLE}
    ) as console:
        assert (
            console.post(
                "/api/v1/session", json={"username": "admin", "password": PASSWORD}
            ).status_code
            == 200
        )
        yield app, console, settings
