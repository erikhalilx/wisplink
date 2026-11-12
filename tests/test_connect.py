from unittest.mock import Mock

import httpx
import pytest
from conftest import CONSOLE, PREVIEW
from typer.testing import CliRunner

from wisplink import cli


@pytest.fixture
def connect_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG", tmp_path)
    login = Mock()
    list_publishes = Mock(return_value={"items": []})
    monkeypatch.setattr(cli, "login_to", login)
    monkeypatch.setattr(cli, "call", list_publishes)
    return CliRunner(), login, list_publishes


def serve(monkeypatch, responses):
    client = httpx.Client

    def respond(request):
        status, payload = responses[request.url.path]
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(
        cli.httpx,
        "Client",
        lambda **options: client(transport=httpx.MockTransport(respond), **options),
    )


def test_instance_metadata_is_public_on_console_only(setup):
    _, console, _ = setup
    payload = console.get("/api/v1/instance").json()
    assert payload["product"] == "wisplink"
    assert payload["api_version"] == 1
    assert payload["console_origin"] == CONSOLE
    assert console.get(f"{PREVIEW}/api/v1/instance").status_code == 404


def test_connect_saves_address_after_verifying_authorization(
    connect_runner, monkeypatch
):
    runner, login, listing = connect_runner
    serve(
        monkeypatch,
        {
            "/api/v1/instance": (
                200,
                {
                    "product": "wisplink",
                    "api_version": 1,
                    "console_origin": CONSOLE,
                },
            )
        },
    )
    result = runner.invoke(cli.app, ["connect", "console.test"])
    assert result.exit_code == 0, result.output
    login.assert_called_once_with(CONSOLE)
    listing.assert_called_once_with({"server": CONSOLE}, "GET", "")
    with cli.profile() as config:
        assert config["server"] == CONSOLE


def test_connect_requires_explicit_legacy_confirmation(connect_runner, monkeypatch):
    runner, login, _ = connect_runner
    serve(
        monkeypatch,
        {
            "/api/v1/instance": (404, {"detail": "Not Found"}),
            "/api/v1/session": (401, {"detail": "会话已失效，请重新登录。"}),
        },
    )
    assert runner.invoke(cli.app, ["connect", CONSOLE]).exit_code == 1
    login.assert_not_called()
    result = runner.invoke(cli.app, ["connect", CONSOLE, "--legacy"])
    assert result.exit_code == 0, result.output
    login.assert_called_once_with(CONSOLE)


def test_connect_keeps_previous_server_when_list_fails(connect_runner, monkeypatch):
    runner, _, listing = connect_runner
    serve(
        monkeypatch,
        {
            "/api/v1/instance": (
                200,
                {
                    "product": "wisplink",
                    "api_version": 1,
                    "console_origin": CONSOLE,
                },
            )
        },
    )
    listing.side_effect = cli.typer.Exit(1)
    assert (
        runner.invoke(cli.app, ["config", "set-server", "https://other.test"]).exit_code
        == 0
    )
    assert runner.invoke(cli.app, ["connect", CONSOLE]).exit_code == 1
    with cli.profile() as config:
        assert config["server"] == "https://other.test"
