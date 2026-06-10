import httpx
import pytest
from fastmcp import FastMCP, settings
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier

from redmine_mcp_server._oauth_proxy import build_oauth_proxy


def test_build_oauth_proxy_uses_introspection_verifier(monkeypatch, tmp_path):
    monkeypatch.setenv("REDMINE_URL", "https://redmine.example")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "https://mcp.example")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "introspect-client")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "introspect-secret")
    monkeypatch.setenv("REDMINE_MCP_JWT_SIGNING_KEY", "stable-test-signing-key")
    monkeypatch.setattr(settings, "home", tmp_path)

    proxy = build_oauth_proxy()

    assert isinstance(proxy, OAuthProxy)
    assert isinstance(proxy._token_validator, IntrospectionTokenVerifier)
    assert proxy._require_authorization_consent == "external"
    assert proxy._token_validator.introspection_url == (
        "https://redmine.example/oauth/introspect"
    )


def test_build_oauth_proxy_restricts_redirect_uris_to_loopback_by_default(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("REDMINE_URL", "https://redmine.example")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "https://mcp.example")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "introspect-client")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "introspect-secret")
    monkeypatch.setenv("REDMINE_MCP_JWT_SIGNING_KEY", "stable-test-signing-key")
    monkeypatch.delenv("REDMINE_MCP_ALLOWED_CLIENT_REDIRECT_URIS", raising=False)
    monkeypatch.setattr(settings, "home", tmp_path)

    proxy = build_oauth_proxy()

    assert proxy._allowed_client_redirect_uris == [
        "http://localhost:*",
        "http://127.0.0.1:*",
    ]


@pytest.mark.asyncio
async def test_authenticated_app_mounts_oauth_proxy_under_mcp(monkeypatch, tmp_path):
    monkeypatch.setenv("REDMINE_URL", "https://redmine.example")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "https://mcp.example")
    monkeypatch.setenv("FASTMCP_STREAMABLE_HTTP_PATH", "/mcp")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "introspect-client")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "introspect-secret")
    monkeypatch.setenv("REDMINE_MCP_JWT_SIGNING_KEY", "stable-test-signing-key")
    monkeypatch.setattr(settings, "home", tmp_path)

    from redmine_mcp_server.main import build_authenticated_app

    auth = build_oauth_proxy()
    app = build_authenticated_app(FastMCP("oauth_proxy_test", auth=auth), auth)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example"
    ) as client:
        root_as = await client.get("/.well-known/oauth-authorization-server")
        resource_as = await client.get("/.well-known/oauth-authorization-server/mcp")
        prm = await client.get("/.well-known/oauth-protected-resource/mcp")
        mounted_prm = await client.get("/mcp/.well-known/oauth-protected-resource")
        authorize = await client.get("/authorize")
        register = await client.post("/register", json={})
        mcp_get = await client.get("/mcp")
        mcp_post = await client.post("/mcp", json={})

    assert root_as.status_code == 200
    assert resource_as.status_code == 404
    assert prm.status_code == 200
    assert mounted_prm.status_code == 404
    assert authorize.status_code != 404
    assert register.status_code != 404
    assert mcp_get.status_code == 405
    assert mcp_post.status_code == 401

    as_body = root_as.json()
    prm_body = prm.json()
    assert as_body["issuer"] == "https://mcp.example/"
    assert as_body["authorization_endpoint"] == "https://mcp.example/authorize"
    assert as_body["token_endpoint"] == "https://mcp.example/token"
    assert as_body["registration_endpoint"] == "https://mcp.example/register"
    assert prm_body["authorization_servers"] == ["https://mcp.example/"]
    assert (
        'resource_metadata="https://mcp.example'
        "/.well-known/oauth-protected-resource/mcp"
        in mcp_post.headers["www-authenticate"]
    )


@pytest.mark.asyncio
async def test_authenticated_app_derives_mount_prefix_from_base_url(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("REDMINE_URL", "https://redmine.example")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "https://mcp.example/api")
    monkeypatch.setenv("FASTMCP_STREAMABLE_HTTP_PATH", "/mcp")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "introspect-client")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "introspect-secret")
    monkeypatch.setenv("REDMINE_MCP_JWT_SIGNING_KEY", "stable-test-signing-key")
    monkeypatch.setattr(settings, "home", tmp_path)

    from redmine_mcp_server.main import build_authenticated_app

    auth = build_oauth_proxy()
    app = build_authenticated_app(FastMCP("oauth_proxy_test", auth=auth), auth)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example"
    ) as client:
        root_as = await client.get("/.well-known/oauth-authorization-server")
        scoped_as = await client.get("/.well-known/oauth-authorization-server/api")
        resource_scoped_as = await client.get(
            "/.well-known/oauth-authorization-server/api/mcp"
        )
        prm = await client.get("/.well-known/oauth-protected-resource/api/mcp")
        authorize = await client.get("/api/authorize")
        register = await client.post("/api/register", json={})
        mcp_post = await client.post("/api/mcp", json={})

    assert root_as.status_code == 404
    assert scoped_as.status_code == 200
    assert resource_scoped_as.status_code == 404
    assert prm.status_code == 200
    assert authorize.status_code != 404
    assert register.status_code != 404
    assert mcp_post.status_code == 401
    assert scoped_as.json()["issuer"] == "https://mcp.example/api"
    assert (
        'resource_metadata="https://mcp.example'
        "/.well-known/oauth-protected-resource/api/mcp"
        in mcp_post.headers["www-authenticate"]
    )
