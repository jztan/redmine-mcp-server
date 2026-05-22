"""End-to-end OAuth auth tests against FastMCP's native auth + RemoteAuthProvider.

The introspection HTTP call is mocked via httpx.MockTransport injected through
``IntrospectionTokenVerifier(http_client=...)`` — see build_remote_auth's
test seam in ``_auth.py`` (the verifier accepts an optional http_client).
"""

import base64
import importlib

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier
from pydantic import AnyHttpUrl


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("REDMINE_URL", "https://r.example.com")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "test-cid")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "test-sec")
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)


def _build_test_app(introspect_handler):
    """Build a FastMCP test app with a mocked introspection transport.

    ``introspect_handler`` is a callable taking an ``httpx.Request`` and
    returning an ``httpx.Response`` that simulates Doorkeeper's /oauth/introspect.
    """
    from redmine_mcp_server import _auth, oauth_scopes
    from redmine_mcp_server import main as main_mod

    importlib.reload(oauth_scopes)
    importlib.reload(_auth)

    mock_transport = httpx.MockTransport(introspect_handler)
    mock_client = httpx.AsyncClient(transport=mock_transport)

    verifier = IntrospectionTokenVerifier(
        introspection_url="https://r.example.com/oauth/introspect",
        client_id="test-cid",
        client_secret="test-sec",
        http_client=mock_client,
    )
    provider = RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl("https://r.example.com")],
        base_url="http://localhost:3040",
        scopes_supported=oauth_scopes.advertised_scopes(),
        resource_name="Redmine MCP Server",
    )
    local_mcp = FastMCP("oauth_auth_test", auth=provider)
    local_mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])(
        main_mod.oauth_authorization_server
    )
    return local_mcp.http_app(stateless_http=True)


def _introspect_response(active: bool, scope: str = "view_issues view_project"):
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"active": active}
        if active:
            body["scope"] = scope
            body["client_id"] = "user-flow-app"
            body["exp"] = 9999999999
        return httpx.Response(200, json=body)

    return handler


@pytest.mark.asyncio
async def test_no_bearer_returns_401(oauth_env):
    app = _build_test_app(_introspect_response(active=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        r = await client.post("/mcp", json={})
    assert r.status_code == 401
    assert "Bearer" in r.headers.get("WWW-Authenticate", "")


@pytest.mark.asyncio
async def test_inactive_token_returns_401(oauth_env):
    app = _build_test_app(_introspect_response(active=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        r = await client.post(
            "/mcp",
            json={},
            headers={"Authorization": "Bearer some-revoked-token"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_introspection_receives_basic_auth(oauth_env):
    """Verify the introspection request carries the configured client creds."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization", "")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"active": False})

    app = _build_test_app(handler)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        await client.post("/mcp", json={}, headers={"Authorization": "Bearer any"})

    expected = "Basic " + base64.b64encode(b"test-cid:test-sec").decode()
    assert captured["auth"] == expected
    assert "token=any" in captured["body"]
    assert "token_type_hint=access_token" in captured["body"]


@pytest.mark.asyncio
async def test_www_authenticate_points_to_live_path(oauth_env):
    """WWW-Authenticate's resource_metadata URL must resolve to a live endpoint."""
    import re

    app = _build_test_app(_introspect_response(active=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:3040"
    ) as client:
        r = await client.post("/mcp", json={})
        assert r.status_code == 401
        www_auth = r.headers.get("WWW-Authenticate", "")
        m = re.search(r'resource_metadata="([^"]+)"', www_auth)
        assert m is not None, f"No resource_metadata in {www_auth!r}"
        metadata_url = m.group(1)
        # Strip scheme+host to get the path we can hit on the test client
        from urllib.parse import urlparse

        parsed = urlparse(metadata_url)
        r2 = await client.get(parsed.path)
        assert r2.status_code == 200, (
            f"WWW-Authenticate points to {metadata_url} which returns "
            f"{r2.status_code}. Discovery flow would be broken."
        )
