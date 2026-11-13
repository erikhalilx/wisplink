from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from conftest import CONSOLE, PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import select

from wisplink.db import publishes
from wisplink.manage import backup, cleanup

HTML = b"<!doctype html><h1>Preview fixture</h1><script>document.body.dataset.ready = 'yes'</script>"


def publish(console, expiry='{"preset":"24h"}', max_ips=1):
    response = console.post(
        "/api/v1/publishes",
        files={"file": ("fixture.html", HTML, "text/html")},
        data={"expiry": expiry, "max_ips": str(max_ips)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_direct_preview_atomic_quota_and_close(setup):
    app, console, _ = setup
    row = publish(console, max_ips=2)
    endpoint = "/api/v1/publishes/" + row["id"]
    with TestClient(app, client=("192.0.2.99", 1234)) as visitor:
        head = visitor.head(row["url"])
        assert head.status_code == 200
        assert head.content == b""
        assert "Set-Cookie" not in head.headers
    summary = console.get(endpoint).json()
    assert (summary["ip_count"], summary["pv"], summary["uv"]) == (0, 0, 0)

    def visit(number):
        with TestClient(app, client=(f"192.0.2.{number}", 1234)) as visitor:
            return visitor.get(row["url"])

    with ThreadPoolExecutor(8) as workers:
        responses = list(workers.map(visit, range(1, 9)))
    assert (
        sorted(response.status_code for response in responses) == [200, 200] + [403] * 6
    )
    for response in responses:
        assert response.headers["Cache-Control"] == "no-store"
        csp = response.headers["Content-Security-Policy"]
        assert "sandbox allow-scripts;" in csp
        assert "frame-ancestors 'none'" in csp
        if response.is_success:
            assert response.content == HTML
        else:
            assert "访问 IP 名额已满" in response.text

    summary = console.get(endpoint).json()
    assert (summary["ip_count"], summary["pv"], summary["uv"]) == (2, 2, 2)
    allowed_ip = next(i for i, response in enumerate(responses, 1) if response.is_success)
    with TestClient(app, client=(f"192.0.2.{allowed_ip}", 1234)) as returning:
        returning.cookies.update(responses[allowed_ip - 1].cookies)
        assert returning.get(row["url"]).content == HTML
    summary = console.get(endpoint).json()
    assert (summary["ip_count"], summary["pv"], summary["uv"]) == (2, 3, 2)

    assert console.post(endpoint + "/close").json()["status"] == "closed"
    assert visit(allowed_ip).status_code == 410
    assert console.head(row["url"]).status_code == 410
    assert console.get(row["url"] + "x").status_code == 404


def test_active_expiry_can_shorten_and_switch_from_permanent(setup):
    _, console, _ = setup
    row = publish(console, '{"preset":"forever"}')
    endpoint = "/api/v1/publishes/" + row["id"]
    changed = console.put(endpoint + "/expiry", json={"preset": "90d"})
    assert changed.status_code == 200
    sooner = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    shortened = console.put(endpoint + "/expiry", json={"at": sooner})
    assert shortened.status_code == 200
    assert shortened.json()["expires_at"] < changed.json()["expires_at"]
    assert (
        console.put(endpoint + "/expiry", json={"preset": "forever"}).json()[
            "expires_at"
        ]
        is None
    )
    assert console.put("/api/v1/settings", json={"max_days": 7}).status_code == 200
    assert console.get(endpoint).json()["expires_at"] is None
    assert (
        console.put(endpoint + "/expiry", json={"preset": "forever"}).status_code == 422
    )
    assert (
        console.put(
            endpoint + "/expiry", json={"preset": "30m", "at": sooner}
        ).status_code
        == 422
    )
    assert console.put(endpoint + "/expiry", json={"preset": "30m"}).status_code == 200


def test_super_admin_and_disabled_publisher_links(setup):
    app, console, _ = setup
    user = console.post(
        "/api/v1/admin/users", json={"username": "publisher", "password": PASSWORD}
    ).json()
    admin_row = publish(console)
    with TestClient(
        app, base_url=CONSOLE, client=("192.0.2.100", 1234), headers={"Origin": CONSOLE}
    ) as publisher:
        assert publisher.post(
            "/api/v1/session", json={"username": "publisher", "password": PASSWORD}
        ).is_success
        row = publish(publisher)
        endpoint = "/api/v1/publishes/" + row["id"]
        assert (
            publisher.get("/api/v1/publishes/" + admin_row["id"] + "/link").status_code
            == 404
        )
        assert console.get(endpoint + "/link").json()["url"] == row["url"]
        assert console.patch(
            "/api/v1/admin/users/" + user["id"], json={"disabled": True}
        ).is_success
        assert publisher.get(endpoint).status_code == 401
        assert console.get(row["url"]).is_success


def test_restore_marks_missing_without_removing_history(setup):
    app, console, settings = setup
    row = publish(console)
    (settings.uploads / row["id"]).unlink()
    cleanup(settings)
    assert console.get(row["url"]).status_code == 410
    with app.state.engine.connect() as connection:
        stored = (
            connection.execute(select(publishes).where(publishes.c.id == row["id"]))
            .mappings()
            .one()
        )
        assert stored["missing"] and stored["purged_at"]
        assert row["url"].split("/")[-1].encode() not in stored["encrypted_token"]


def test_backup_includes_wal_without_html(setup, tmp_path):
    import sqlite3
    from contextlib import closing

    _, console, settings = setup
    row = publish(console)
    snapshot = tmp_path / "backup.sqlite3"
    backup(settings, snapshot)
    with closing(sqlite3.connect(snapshot)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute("SELECT id FROM publishes").fetchone() == (row["id"],)
    assert HTML not in snapshot.read_bytes()
    assert snapshot.stat().st_mode & 0o777 == 0o600
