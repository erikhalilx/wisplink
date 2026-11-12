from io import BytesIO
from zipfile import ZipFile

from conftest import CONSOLE, PASSWORD
from fastapi.testclient import TestClient

ENDPOINT = "/api/v1/admin/agent-bundle"


def test_only_signed_in_super_administrators_can_download(setup):
    app, admin, _ = setup
    assert (
        admin.post(
            "/api/v1/admin/users", json={"username": "publisher", "password": PASSWORD}
        ).status_code
        == 201
    )
    with TestClient(
        app, base_url=CONSOLE, headers={"Origin": CONSOLE}, client=("192.0.2.2", 1234)
    ) as other:
        assert other.get(ENDPOINT).status_code == 401
        assert (
            other.post(
                "/api/v1/session", json={"username": "publisher", "password": PASSWORD}
            ).status_code
            == 200
        )
        assert other.get(ENDPOINT).status_code == 403
    assert admin.get(ENDPOINT).status_code == 200
    assert admin.delete("/api/v1/session").status_code == 204
    assert admin.get(ENDPOINT).status_code == 401


def test_bundle_uses_configured_origin_without_embedding_credentials(setup):
    app, console, settings = setup
    response = console.get(ENDPOINT, headers={"X-Forwarded-Host": "unrelated.test"})
    assert (
        response.headers["Content-Disposition"]
        == 'attachment; filename="wisplink-agent.zip"'
    )
    assert response.headers["Content-Type"] == "application/zip"
    assert response.headers["Cache-Control"] == "no-store"
    with ZipFile(BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {
            "README.md",
            "wisplink/SKILL.md",
            "wisplink/install.sh",
        }
        installer = bundle.read("wisplink/install.sh")
        assert f"origin={CONSOLE}\n".encode() in installer
        assert b'exec "$cli" connect "$origin"' in installer
        contents = b"".join(bundle.read(name) for name in bundle.namelist())
    assert b"unrelated.test" not in contents
    assert settings.key not in contents
    assert PASSWORD.encode() not in contents
    assert console.cookies[app.state.session_cookie].encode() not in contents
