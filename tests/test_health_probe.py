"""Tests for /health Doorkeeper introspection probe."""

import importlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("REDMINE_URL", "https://r.example.com")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
    monkeypatch.setenv("HEALTH_INTROSPECTION_TTL_SECONDS", "30")


def _reset_probe_cache():
    """Wipe the module-level probe cache so each test starts clean."""
    from redmine_mcp_server import _http_routes

    _http_routes._probe_cache = {"ts": 0.0, "result": None}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_mode_healthy_probe_returns_ok(oauth_env):
    monkeypatch_set = pytest.MonkeyPatch()
    monkeypatch_set.setenv("REDMINE_AUTH_MODE", "oauth")
    try:
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)
        _reset_probe_cache()
        with (
            patch.object(
                _http_routes,
                "_probe_introspection",
                AsyncMock(return_value=("ok", None)),
            ),
            patch(
                "redmine_mcp_server._cleanup._ensure_cleanup_started",
                new_callable=AsyncMock,
            ),
        ):
            from starlette.applications import Starlette
            from starlette.routing import Route

            app = Starlette(routes=[Route("/health", _http_routes.health_check)])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as client:
                r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["checks"]["introspection"] == "ok"
    finally:
        monkeypatch_set.undo()
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_mode_unreachable_probe_returns_degraded(oauth_env):
    monkeypatch_set = pytest.MonkeyPatch()
    monkeypatch_set.setenv("REDMINE_AUTH_MODE", "oauth")
    try:
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)
        _reset_probe_cache()
        with (
            patch.object(
                _http_routes,
                "_probe_introspection",
                AsyncMock(return_value=("unreachable", "ConnectError")),
            ),
            patch(
                "redmine_mcp_server._cleanup._ensure_cleanup_started",
                new_callable=AsyncMock,
            ),
        ):
            from starlette.applications import Starlette
            from starlette.routing import Route

            app = Starlette(routes=[Route("/health", _http_routes.health_check)])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as client:
                r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["introspection"] == "unreachable"
        assert "ConnectError" in body["checks"]["introspection_detail"]
    finally:
        monkeypatch_set.undo()
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_proxy_mode_uses_introspection_probe(oauth_env):
    """OAuth proxy mode validates Redmine reachability through introspection."""
    monkeypatch_set = pytest.MonkeyPatch()
    monkeypatch_set.setenv("REDMINE_AUTH_MODE", "oauth-proxy")
    try:
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)
        _reset_probe_cache()
        with (
            patch.object(
                _http_routes,
                "_probe_introspection",
                AsyncMock(return_value=("ok", None)),
            ) as introspection_probe,
            patch.object(
                _http_routes,
                "_probe_redmine_legacy",
                AsyncMock(return_value=("unreachable", "AuthError")),
            ) as legacy_probe,
            patch(
                "redmine_mcp_server._cleanup._ensure_cleanup_started",
                new_callable=AsyncMock,
            ),
        ):
            from starlette.applications import Starlette
            from starlette.routing import Route

            app = Starlette(routes=[Route("/health", _http_routes.health_check)])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as client:
                r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["auth_mode"] == "oauth-proxy"
        assert body["checks"]["introspection"] == "ok"
        introspection_probe.assert_awaited_once()
        legacy_probe.assert_not_awaited()
    finally:
        monkeypatch_set.undo()
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_legacy_mode_probes_redmine_not_introspection():
    """Legacy mode runs a Redmine connectivity probe instead of OAuth introspection.

    When no credentials are configured the probe returns "unconfigured"
    and the overall status stays "ok" (server hasn't been set up yet, not
    a runtime failure).
    """
    monkeypatch_set = pytest.MonkeyPatch()
    monkeypatch_set.setenv("REDMINE_AUTH_MODE", "legacy")
    monkeypatch_set.setenv("REDMINE_URL", "https://r.example.com")
    try:
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)
        _reset_probe_cache()
        with patch(
            "redmine_mcp_server._cleanup._ensure_cleanup_started",
            new_callable=AsyncMock,
        ):
            from starlette.applications import Starlette
            from starlette.routing import Route

            app = Starlette(routes=[Route("/health", _http_routes.health_check)])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as client:
                r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        # No credentials configured → "unconfigured", not degraded.
        assert body["status"] == "ok"
        assert "introspection" not in body.get("checks", {})
        assert body["checks"]["redmine"] == "unconfigured"
    finally:
        monkeypatch_set.undo()
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_legacy_mode_degraded_when_redmine_unreachable():
    """When credentials are configured but Redmine rejects them, status is degraded."""
    monkeypatch_set = pytest.MonkeyPatch()
    monkeypatch_set.setenv("REDMINE_AUTH_MODE", "legacy")
    monkeypatch_set.setenv("REDMINE_URL", "https://r.example.com")
    monkeypatch_set.setenv("REDMINE_API_KEY", "test-key")
    try:
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)
        _reset_probe_cache()
        with (
            patch.object(
                _http_routes,
                "_probe_redmine_legacy",
                AsyncMock(return_value=("unreachable", "AuthError")),
            ),
            patch(
                "redmine_mcp_server._cleanup._ensure_cleanup_started",
                new_callable=AsyncMock,
            ),
        ):
            from starlette.applications import Starlette
            from starlette.routing import Route

            app = Starlette(routes=[Route("/health", _http_routes.health_check)])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as client:
                r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["redmine"] == "unreachable"
        assert "AuthError" in body["checks"]["redmine_detail"]
    finally:
        monkeypatch_set.undo()
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_result_is_cached(oauth_env):
    """Two /health calls within TTL hit the introspection endpoint once."""
    monkeypatch_set = pytest.MonkeyPatch()
    monkeypatch_set.setenv("REDMINE_AUTH_MODE", "oauth")
    try:
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)
        _reset_probe_cache()
        mock_probe = AsyncMock(return_value=("ok", None))
        with (
            patch.object(_http_routes, "_probe_introspection_uncached", mock_probe),
            patch(
                "redmine_mcp_server._cleanup._ensure_cleanup_started",
                new_callable=AsyncMock,
            ),
        ):
            from starlette.applications import Starlette
            from starlette.routing import Route

            app = Starlette(routes=[Route("/health", _http_routes.health_check)])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as client:
                await client.get("/health")
                await client.get("/health")
        assert mock_probe.call_count == 1
    finally:
        monkeypatch_set.undo()
        from redmine_mcp_server import _client, _http_routes

        importlib.reload(_client)
        importlib.reload(_http_routes)
