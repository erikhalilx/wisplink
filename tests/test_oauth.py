import base64
import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from conftest import CONSOLE
from fastapi.testclient import TestClient

from wisplink.oauth import CLIENT_ID, create_auth_app
from wisplink.security import token


def test_pkce_rotation_reuse_and_revoke(setup):
    app, console, settings = setup
    auth = create_auth_app(settings)
    auth.testing = True
    with auth.test_client() as client:
        host = urlsplit(CONSOLE).hostname
        name = app.state.session_cookie
        client.set_cookie(name, console.cookies.get(name), domain=host)
        verifier = token()
        state = token()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        callback = "http://127.0.0.1:56789/callback"
        args = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": callback,
            "state": state,
            "scope": "publish:read publish:write",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        def authorize(**overrides):
            return "/oauth/authorize?" + urlencode({**args, **overrides})

        def post(path, **data):
            return client.post(
                path, data={"client_id": CLIENT_ID, **data}, base_url=CONSOLE
            )

        assert (
            client.get(
                authorize(code_challenge_method="plain"), base_url=CONSOLE
            ).status_code
            == 400
        )
        assert (
            client.get(
                authorize(redirect_uri="http://127.0.0.1:56789/wrong"), base_url=CONSOLE
            ).status_code
            == 400
        )
        consent = client.get(authorize(), base_url=CONSOLE)
        assert consent.status_code == 200, consent.text
        proof = re.search(r'name="proof" value="([^"]+)"', consent.text)[1]
        granted = client.post(
            authorize(),
            base_url=CONSOLE,
            data={"proof": proof, "decision": "allow"},
            headers={"Origin": CONSOLE},
        )
        assert granted.status_code == 302, granted.text
        location = parse_qs(urlsplit(granted.location).query)
        assert location["state"] == [state] and location["iss"] == [CONSOLE]
        request = {
            "grant_type": "authorization_code",
            "code": location["code"][0],
            "redirect_uri": callback,
        }
        assert post("/oauth/token", **request, code_verifier=token()).status_code == 400
        response = post("/oauth/token", **request, code_verifier=verifier)
        assert response.status_code == 200, response.text
        old = response.json
        assert (
            post("/oauth/token", **request, code_verifier=verifier).status_code == 400
        )
        with TestClient(app, base_url=CONSOLE, client=("192.0.2.100", 1234)) as cli:

            def list_with(secret):
                return cli.get(
                    "/api/v1/publishes", headers={"Authorization": "Bearer " + secret}
                )

            assert list_with(old["access_token"]).status_code == 200
            response = post(
                "/oauth/token",
                grant_type="refresh_token",
                refresh_token=old["refresh_token"],
            )
            assert response.status_code == 200, response.text
            new = response.json
            assert new["refresh_token"] != old["refresh_token"]
            assert list_with(old["access_token"]).status_code == 401
            assert list_with(new["access_token"]).status_code == 200
            assert (
                post(
                    "/oauth/token",
                    grant_type="refresh_token",
                    refresh_token=old["refresh_token"],
                ).status_code
                == 400
            )
            assert list_with(new["access_token"]).status_code == 401
            assert not console.get("/api/v1/authorizations").json()
            assert post("/oauth/revoke", token=new["refresh_token"]).status_code == 200
