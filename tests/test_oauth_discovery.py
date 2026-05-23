"""Tests for OAuth discovery endpoints after the FastMCP v3 auth migration.

These build a parallel FastMCP instance in OAuth mode and exercise its HTTP
surface so the global `mcp` singleton (legacy mode in the test process) is
not disturbed.
"""

import importlib

import httpx
import pytest
from fastmcp import FastMCP


@pytest.fixture
def oauth_app(monkeypatch):
    """Construct a fresh OAuth-mode FastMCP app for discovery tests.

    Returns the Starlette ASGI app. The fixture mirrors the production
    wiring in ``main.py`` and ``server.py`` but uses a local FastMCP
    instance so the global ``mcp`` singleton (carrying tool registrations)
    is not perturbed.
    """
    monkeypatch.setenv("REDMINE_URL", "https://r.example.com")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
    monkeypatch.setenv("REDMINE_MCP_MIRROR_REDMINE_AS_METADATA", "true")
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)

    from redmine_mcp_server import _auth, oauth_scopes
    from redmine_mcp_server import main as main_mod

    importlib.reload(oauth_scopes)
    importlib.reload(_auth)

    async def mock_as_metadata(redmine_url):
        return {
            "issuer": redmine_url,
            "authorization_endpoint": f"{redmine_url}/oauth/authorize",
            "token_endpoint": f"{redmine_url}/oauth/token",
            "registration_endpoint": f"{redmine_url}/oauth/registration",
            "revocation_endpoint": f"{redmine_url}/oauth/revoke",
            "jwks_uri": f"{redmine_url}/oauth/discovery/keys",
            "subject_types_supported": ["public"],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
        }

    monkeypatch.setattr(
        main_mod, "fetch_authorization_server_metadata", mock_as_metadata
    )

    auth_provider = _auth.build_remote_auth()
    local_mcp = FastMCP("redmine_mcp_tools_test", auth=auth_provider)

    # Mirror main.py: register kept custom_routes
    local_mcp.custom_route(
        "/.well-known/oauth-authorization-server/mcp", methods=["GET"]
    )(main_mod.oauth_authorization_server)
    local_mcp.custom_route("/revoke", methods=["POST"])(main_mod.revoke_token)

    return local_mcp.http_app(stateless_http=True)


@pytest.mark.asyncio
async def test_protected_resource_suffix_path_returns_200(oauth_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        r = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert "authorization_servers" in body
    assert any("r.example.com" in str(u) for u in body["authorization_servers"])
    assert "scopes_supported" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource",
        "/mcp/.well-known/oauth-protected-resource",
        "/mcp/.well-known/oauth-authorization-server",
    ],
)
async def test_dropped_discovery_paths_return_404(oauth_app, path):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        r = await client.get(path)
    assert (
        r.status_code == 404
    ), f"Expected 404 for dropped path {path}, got {r.status_code}"


@pytest.mark.asyncio
async def test_authorization_server_suffix_path_returns_200(oauth_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        r = await client.get("/.well-known/oauth-authorization-server/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["authorization_endpoint"] == "https://r.example.com/oauth/authorize"
    assert body["token_endpoint"] == "https://r.example.com/oauth/token"
    assert body["revocation_endpoint"] == "https://r.example.com/oauth/revoke"


@pytest.mark.asyncio
async def test_authorization_server_does_not_fetch_redmine_discovery_by_default(
    monkeypatch,
):
    monkeypatch.setenv("REDMINE_URL", "https://r.example.com")
    monkeypatch.delenv("REDMINE_MCP_MIRROR_REDMINE_AS_METADATA", raising=False)

    from redmine_mcp_server import main as main_mod

    async def fail_fetch(redmine_url):
        raise AssertionError("Redmine discovery should be opt-in")

    monkeypatch.setattr(main_mod, "fetch_authorization_server_metadata", fail_fetch)

    body = (await main_mod.oauth_authorization_server(None)).body

    assert b"registration_endpoint" not in body


@pytest.mark.asyncio
async def test_authorization_server_mirrors_redmine_discovery_when_enabled(oauth_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        r = await client.get("/.well-known/oauth-authorization-server/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["registration_endpoint"] == "https://r.example.com/oauth/registration"
    assert body["jwks_uri"] == "https://r.example.com/oauth/discovery/keys"
    assert body["subject_types_supported"] == ["public"]


@pytest.mark.asyncio
async def test_registration_endpoint_is_omitted_when_falling_back():
    from redmine_mcp_server import main as main_mod

    metadata = main_mod.fallback_authorization_server_metadata("https://r.example.com")

    assert "registration_endpoint" not in metadata


@pytest.mark.asyncio
async def test_scope_sources_match(oauth_app):
    """Both discovery endpoints must return identical scopes_supported."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        pr = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
        asm = (await client.get("/.well-known/oauth-authorization-server/mcp")).json()
    assert pr["scopes_supported"] == asm["scopes_supported"]


@pytest.mark.asyncio
async def test_scope_sources_filtered_consistently_in_read_only_mode(monkeypatch):
    """Read-only mode must filter write scopes from BOTH discovery endpoints."""
    monkeypatch.setenv("REDMINE_URL", "https://r.example.com")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
    monkeypatch.setenv("REDMINE_MCP_MIRROR_REDMINE_AS_METADATA", "true")
    monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")

    from redmine_mcp_server import _auth, oauth_scopes
    from redmine_mcp_server import main as main_mod

    importlib.reload(oauth_scopes)
    importlib.reload(_auth)

    auth_provider = _auth.build_remote_auth()
    local_mcp = FastMCP("ro_test", auth=auth_provider)

    async def mock_as_metadata(redmine_url):
        return main_mod.fallback_authorization_server_metadata(redmine_url)

    monkeypatch.setattr(
        main_mod, "fetch_authorization_server_metadata", mock_as_metadata
    )
    local_mcp.custom_route(
        "/.well-known/oauth-authorization-server/mcp", methods=["GET"]
    )(main_mod.oauth_authorization_server)
    app = local_mcp.http_app(stateless_http=True)

    from redmine_mcp_server.oauth_scopes import WRITE_SCOPES

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        pr = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
        asm = (await client.get("/.well-known/oauth-authorization-server/mcp")).json()

    for write_scope in WRITE_SCOPES:
        assert write_scope not in pr["scopes_supported"]
        assert write_scope not in asm["scopes_supported"]
