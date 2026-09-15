"""The wiring itself: does the mode hang together in the real application?

Everything else in the suite mocks the seams. This imports the package the way
a deployment does, in ``api-key-login`` mode, and drives ``main.app`` once from
registration to a revoked session -- so that removing the middleware
registration in ``server.py`` or the ``/login`` import in ``main.py`` fails a
test instead of passing quietly.
"""

import base64
import hashlib
import re
import secrets
import sys
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

REDMINE = "https://redmine.example.com"
BASE = "http://localhost:8000"
REDIRECT = "http://127.0.0.1:41999/callback"
KEY = "b" * 40

_PACKAGE = "redmine_mcp_server"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _package_modules():
    return [
        name
        for name in sys.modules
        if name == _PACKAGE or name.startswith(f"{_PACKAGE}.")
    ]


@pytest.fixture
def isolated_server(monkeypatch, tmp_path):
    """Import the package fresh in this mode, then put the old one back.

    A ``sys.modules`` snapshot rather than ``importlib.reload``: the package
    builds its FastMCP instance, registers every tool on it and mounts the
    routes at import time, so only a clean import yields a server genuinely
    wired for this mode. Restoring the snapshot puts the original module
    objects back untouched, which matters because the rest of the suite holds
    references to them -- reloading in place would leave that shared instance
    stripped of its tools.
    """
    monkeypatch.setenv("REDMINE_AUTH_MODE", "api-key-login")
    monkeypatch.setenv("REDMINE_URL", REDMINE)
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", BASE)
    monkeypatch.setenv("REDMINE_MCP_JWT_SIGNING_KEY", "wiring-test-signing-key")
    monkeypatch.setenv("REDMINE_API_KEY_LOGIN_ALLOW_HTTP", "true")
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))

    snapshot = {name: sys.modules[name] for name in _package_modules()}
    for name in snapshot:
        del sys.modules[name]

    try:
        import redmine_mcp_server.main as fresh

        yield fresh
    finally:
        for name in _package_modules():
            del sys.modules[name]
        sys.modules.update(snapshot)


async def _register_and_login(provider, http, identity_module):
    """Walk a client through registration, the browser step and the token."""
    registration = await http.post(
        "/register",
        json={
            "client_name": "wiring probe",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    client_id = registration.json()["client_id"]
    verifier = _b64(secrets.token_bytes(32))

    authorize = await http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "state": "s",
        },
    )
    assert authorize.status_code == 302, authorize.text[:200]
    txn = authorize.headers["location"].split("txn=", 1)[1]

    # The binding cookie rides on that redirect; httpx keeps it in the jar.
    page = await http.get(f"/login?txn={txn}")
    assert page.status_code == 200, page.text[:200]
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)

    identity = {"id": 12, "login": "wired", "admin": False}
    with patch.object(
        identity_module, "fetch_redmine_identity", AsyncMock(return_value=identity)
    ):
        submitted = await http.post(
            "/login", data={"txn": txn, "csrf": csrf, "api_key": KEY}
        )
    assert submitted.status_code == 302, submitted.text[:200]
    code = re.search(r"[?&]code=([^&]+)", submitted.headers["location"]).group(1)

    token = await http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text[:200]
    return token.json()


async def test_a_401_from_redmine_ends_the_session_through_the_real_app(
    isolated_server,
):
    """The guarantee, end to end: reset your key and the next call signs you out."""
    from redminelib.exceptions import AuthError

    client_module = sys.modules[f"{_PACKAGE}._client"]
    provider_module = sys.modules[f"{_PACKAGE}._api_key_login"]
    provider = sys.modules[f"{_PACKAGE}.server"].AUTH_PROVIDER
    app = isolated_server.app

    # /mcp needs the lifespan: the streamable-HTTP manager starts its task
    # group there.
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=BASE, follow_redirects=False
        ) as http:
            token = await _register_and_login(provider, http, provider_module)
            access = token["access_token"]

            bound = await provider.load_access_token(access)
            assert bound.claims["redmine_api_key"] == KEY
            binding_id = bound.claims["binding_id"]

            def mcp(method, params=None):
                return http.post(
                    "/mcp",
                    headers={
                        "Authorization": f"Bearer {access}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": params or {},
                    },
                )

            await mcp(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "wiring", "version": "0"},
                },
            )

            # Redmine rejects the bound key, as it does after a reset on any
            # endpoint that requires a login.
            with patch.object(client_module, "_new_client") as new_client:
                new_client.return_value.user.get.side_effect = AuthError()
                called = await mcp(
                    "tools/call", {"name": "get_current_user", "arguments": {}}
                )

            assert called.status_code == 200
            assert "AUTH_FAILED" in called.text

    # The middleware revoked on the event loop, after the result went out.
    assert await provider._store.get(binding_id, collection="bindings") is None
    assert await provider.load_access_token(access) is None


def test_the_login_route_is_mounted_in_the_real_app(isolated_server):
    paths = []

    def walk(routes, prefix=""):
        for route in routes:
            path = prefix + getattr(route, "path", "")
            if getattr(route, "routes", None):
                walk(route.routes, path)
            elif getattr(route, "path", None):
                paths.append(path)

    walk(isolated_server.app.routes)
    assert any(p.endswith("/login") for p in paths), paths


def test_the_revocation_middleware_is_registered(isolated_server):
    server = sys.modules[f"{_PACKAGE}.server"]
    provider_module = sys.modules[f"{_PACKAGE}._api_key_login"]

    names = [type(mw).__name__ for mw in server.mcp.middleware]
    expected = provider_module.BindingRevocationMiddleware.__name__
    assert expected in names
    # After the scope check, so a scope denial never looks like a rejected key.
    assert names.index("ScopeEnforcementMiddleware") < names.index(expected)


# --- the warning the middleware block used to swallow ---------------------


def _fresh_mcp():
    from fastmcp import FastMCP

    return FastMCP("warning-test")


@pytest.mark.parametrize("mode", ["oauth", "api-key-login"])
def test_scope_enforcement_off_warns_in_every_mode(monkeypatch, caplog, mode):
    """The warning is about enforcement, not about which mode is running."""
    from redmine_mcp_server import server

    monkeypatch.setenv("REDMINE_OAUTH_SCOPE_ENFORCEMENT", "off")
    monkeypatch.setattr(server, "REDMINE_AUTH_MODE", mode)
    with caplog.at_level("WARNING"):
        server._register_middlewares(_fresh_mcp(), object())

    assert any(
        "scope enforcement is DISABLED" in r.getMessage() for r in caplog.records
    )


@pytest.mark.parametrize("mode", ["oauth", "api-key-login"])
def test_scope_enforcement_on_stays_quiet_in_every_mode(monkeypatch, caplog, mode):
    from redmine_mcp_server import server

    monkeypatch.setenv("REDMINE_OAUTH_SCOPE_ENFORCEMENT", "on")
    monkeypatch.setattr(server, "REDMINE_AUTH_MODE", mode)
    with caplog.at_level("WARNING"):
        server._register_middlewares(_fresh_mcp(), object())

    assert not any(
        "scope enforcement is DISABLED" in r.getMessage() for r in caplog.records
    )
