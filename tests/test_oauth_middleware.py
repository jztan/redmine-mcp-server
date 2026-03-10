"""
Tests for OAuth2 middleware and related functionality.

Tests cover:
- RedmineOAuthMiddleware: token validation, skip paths, error responses
- get_current_token(): ContextVar access
- _get_redmine_client(): OAuth vs legacy auth selection
"""

import os

# Set required env vars before any project module is imported, because
# oauth_middleware.py reads REDMINE_URL at module level.
os.environ.setdefault("REDMINE_URL", "https://test-redmine.example.com")
os.environ.setdefault("REDMINE_MCP_BASE_URL", "http://localhost:3040")

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Return a minimal Starlette app with the OAuth middleware attached."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from redmine_mcp_server.oauth_middleware import RedmineOAuthMiddleware

    async def protected(request: Request):
        from redmine_mcp_server.oauth_middleware import current_redmine_token
        token = current_redmine_token.get()
        return JSONResponse({"token": token})

    app = Starlette(routes=[Route("/protected", protected)])
    app.add_middleware(RedmineOAuthMiddleware)
    return app


# ---------------------------------------------------------------------------
# get_current_token()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetCurrentToken:
    """Tests for the get_current_token() helper."""

    def test_raises_when_no_token_in_context(self):
        """Raises RuntimeError when called outside middleware context."""
        from redmine_mcp_server.oauth_middleware import (
            get_current_token,
            current_redmine_token,
        )
        # Make sure ContextVar is empty
        token_var = current_redmine_token.set(None)
        try:
            with pytest.raises(RuntimeError, match="No Redmine token in context"):
                get_current_token()
        finally:
            current_redmine_token.reset(token_var)

    def test_returns_token_when_set(self):
        """Returns the token stored in the ContextVar."""
        from redmine_mcp_server.oauth_middleware import (
            get_current_token,
            current_redmine_token,
        )
        token_var = current_redmine_token.set("my-test-token")
        try:
            assert get_current_token() == "my-test-token"
        finally:
            current_redmine_token.reset(token_var)


# ---------------------------------------------------------------------------
# RedmineOAuthMiddleware — skip paths
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOAuthMiddlewareSkipPaths:
    """Requests to skip-listed paths must pass through without auth."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", [
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
        "/health",
        "/revoke",
    ])
    async def test_skip_path_passes_without_auth(self, path):
        """Skip-listed paths are not blocked by the middleware."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from redmine_mcp_server.oauth_middleware import RedmineOAuthMiddleware

        async def handler(request: Request):
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route(path, handler)])
        app.add_middleware(RedmineOAuthMiddleware)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(path)

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# RedmineOAuthMiddleware — missing / malformed Authorization header
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOAuthMiddlewareMissingHeader:
    """Requests without a valid Bearer token must be rejected with 401."""

    @pytest.mark.asyncio
    async def test_no_auth_header_returns_401(self):
        app = _make_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/protected")

        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_no_auth_header_includes_www_authenticate(self):
        app = _make_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/protected")

        www_auth = response.headers.get("www-authenticate", "")
        assert "Bearer" in www_auth
        assert "resource_metadata" in www_auth
        # No error= hint when the header is absent entirely
        assert 'error=' not in www_auth

    @pytest.mark.asyncio
    async def test_non_bearer_scheme_returns_401(self):
        app = _make_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"}
            )

        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"


# ---------------------------------------------------------------------------
# RedmineOAuthMiddleware — Redmine token validation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOAuthMiddlewareTokenValidation:
    """Middleware must validate the token against Redmine /users/current.json."""

    @pytest.mark.asyncio
    async def test_valid_token_passes_request(self):
        """A token accepted by Redmine lets the request through."""
        app = _make_app()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.oauth_middleware.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/protected", headers={"Authorization": "Bearer valid-token"}
                )

        assert response.status_code == 200
        assert response.json()["token"] == "valid-token"

    @pytest.mark.asyncio
    async def test_valid_token_forwarded_to_redmine_with_bearer(self):
        """Middleware calls Redmine with the same Bearer token."""
        app = _make_app()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.oauth_middleware.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get(
                    "/protected", headers={"Authorization": "Bearer my-token-123"}
                )

            call_kwargs = mock_client.get.call_args
            assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer my-token-123"

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        """A token rejected by Redmine (non-200) returns 401."""
        app = _make_app()

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("redmine_mcp_server.oauth_middleware.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/protected", headers={"Authorization": "Bearer bad-token"}
                )

        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"

    @pytest.mark.asyncio
    async def test_invalid_token_includes_error_in_www_authenticate(self):
        """WWW-Authenticate header includes error= hint for rejected tokens."""
        app = _make_app()

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("redmine_mcp_server.oauth_middleware.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/protected", headers={"Authorization": "Bearer bad-token"}
                )

        www_auth = response.headers.get("www-authenticate", "")
        assert 'error="invalid_token"' in www_auth

    @pytest.mark.asyncio
    async def test_redmine_unreachable_returns_503(self):
        """503 when Redmine cannot be reached."""
        import httpx

        app = _make_app()

        with patch("redmine_mcp_server.oauth_middleware.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(
                side_effect=httpx.RequestError("connection refused")
            )
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/protected", headers={"Authorization": "Bearer any-token"}
                )

        assert response.status_code == 503
        assert response.json()["error"] == "upstream_unavailable"

    @pytest.mark.asyncio
    async def test_context_var_reset_after_request(self):
        """ContextVar is reset to None after the request completes."""
        from redmine_mcp_server.oauth_middleware import current_redmine_token

        app = _make_app()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.oauth_middleware.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get(
                    "/protected", headers={"Authorization": "Bearer some-token"}
                )

        assert current_redmine_token.get() is None


# ---------------------------------------------------------------------------
# /.well-known endpoints via the real app
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWellKnownEndpoints:
    """Tests for the OAuth2 discovery endpoints served by main.py."""

    @pytest.fixture
    def app(self):
        from redmine_mcp_server.main import app, register_oauth_routes
        register_oauth_routes(app)
        return app

    @pytest.mark.asyncio
    async def test_protected_resource_metadata_shape(self, app):
        """/.well-known/oauth-protected-resource returns required fields."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/oauth-protected-resource")

        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
        assert "authorization_servers" in data
        assert isinstance(data["authorization_servers"], list)
        assert len(data["authorization_servers"]) > 0
        assert data["bearer_methods_supported"] == ["header"]
        assert "resource_name" in data

    @pytest.mark.asyncio
    async def test_protected_resource_contains_mcp_path(self, app):
        """resource field must end with /mcp."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/oauth-protected-resource")

        assert response.json()["resource"].endswith("/mcp")

    @pytest.mark.asyncio
    async def test_authorization_server_metadata_shape(self, app):
        """/.well-known/oauth-authorization-server returns required RFC 8414 fields."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        data = response.json()
        for field in (
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "response_types_supported",
            "grant_types_supported",
        ):
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_authorization_server_endpoints_point_to_redmine(self, app):
        """authorization_endpoint and token_endpoint must use REDMINE_URL."""
        from redmine_mcp_server.main import REDMINE_URL

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/oauth-authorization-server")

        data = response.json()
        assert data["authorization_endpoint"].startswith(REDMINE_URL)
        assert data["token_endpoint"].startswith(REDMINE_URL)

    @pytest.mark.asyncio
    async def test_authorization_server_supports_pkce(self, app):
        """Must advertise S256 PKCE support."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/oauth-authorization-server")

        assert "S256" in response.json()["code_challenge_methods_supported"]

    @pytest.mark.asyncio
    async def test_well_known_accessible_without_auth_in_oauth_mode(self):
        """Discovery endpoints must be reachable without a Bearer token even in oauth mode."""
        import os
        from starlette.testclient import TestClient

        with patch.dict(os.environ, {"REDMINE_AUTH_MODE": "oauth"}):
            # Import fresh app state isn't possible after module load, so test
            # the middleware skip-path logic directly via _make_app equivalent.
            from starlette.applications import Starlette
            from starlette.requests import Request
            from starlette.responses import JSONResponse
            from starlette.routing import Route
            from redmine_mcp_server.oauth_middleware import RedmineOAuthMiddleware

            async def discovery(request: Request):
                return JSONResponse({"issuer": "http://test"})

            app = Starlette(routes=[
                Route("/.well-known/oauth-authorization-server", discovery),
                Route("/.well-known/oauth-protected-resource", discovery),
            ])
            app.add_middleware(RedmineOAuthMiddleware)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                r1 = await client.get("/.well-known/oauth-authorization-server")
                r2 = await client.get("/.well-known/oauth-protected-resource")

        assert r1.status_code == 200
        assert r2.status_code == 200


# ---------------------------------------------------------------------------
# _get_redmine_client() — auth selection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetRedmineClient:
    """Tests for _get_redmine_client() auth mode selection."""

    @pytest.fixture(autouse=True)
    def _reset_legacy_cache(self):
        """Clear cached legacy client between tests."""
        import redmine_mcp_server.redmine_handler as rh
        rh._legacy_client = None
        yield
        rh._legacy_client = None

    def test_uses_oauth_token_when_context_var_is_set(self):
        """When a token is in the ContextVar, a Bearer-auth client is returned."""
        from redmine_mcp_server.oauth_middleware import current_redmine_token
        from redmine_mcp_server.redmine_handler import _get_redmine_client

        token_var = current_redmine_token.set("oauth-token-abc")
        try:
            with patch("redmine_mcp_server.redmine_handler.Redmine") as mock_redmine:
                _get_redmine_client()
                call_kwargs = mock_redmine.call_args.kwargs
                headers = call_kwargs["requests"]["headers"]
                assert headers["Authorization"] == "Bearer oauth-token-abc"
        finally:
            current_redmine_token.reset(token_var)

    def test_falls_back_to_api_key_when_no_context_token(self):
        """Without a ContextVar token, API key is used."""
        from redmine_mcp_server.oauth_middleware import current_redmine_token
        from redmine_mcp_server.redmine_handler import _get_redmine_client
        import redmine_mcp_server.redmine_handler as rh

        token_var = current_redmine_token.set(None)
        try:
            with patch.object(rh, "REDMINE_API_KEY", "test-api-key"), \
                 patch("redmine_mcp_server.redmine_handler.Redmine") as mock_redmine:
                _get_redmine_client()
                call_kwargs = mock_redmine.call_args
                assert call_kwargs.kwargs.get("key") == "test-api-key"
        finally:
            current_redmine_token.reset(token_var)

    def test_falls_back_to_username_password_when_no_api_key(self):
        """Without a ContextVar token or API key, username/password is used."""
        from redmine_mcp_server.oauth_middleware import current_redmine_token
        from redmine_mcp_server.redmine_handler import _get_redmine_client
        import redmine_mcp_server.redmine_handler as rh

        token_var = current_redmine_token.set(None)
        try:
            with patch.object(rh, "REDMINE_API_KEY", None), \
                 patch.object(rh, "REDMINE_USERNAME", "user"), \
                 patch.object(rh, "REDMINE_PASSWORD", "pass"), \
                 patch("redmine_mcp_server.redmine_handler.Redmine") as mock_redmine:
                _get_redmine_client()
                call_kwargs = mock_redmine.call_args
                assert call_kwargs.kwargs.get("username") == "user"
                assert call_kwargs.kwargs.get("password") == "pass"
        finally:
            current_redmine_token.reset(token_var)

    def test_raises_when_no_auth_configured(self):
        """Raises RuntimeError when no auth is available at all."""
        from redmine_mcp_server.oauth_middleware import current_redmine_token
        from redmine_mcp_server.redmine_handler import _get_redmine_client
        import redmine_mcp_server.redmine_handler as rh

        token_var = current_redmine_token.set(None)
        try:
            with patch.object(rh, "REDMINE_API_KEY", None), \
                 patch.object(rh, "REDMINE_USERNAME", None), \
                 patch.object(rh, "REDMINE_PASSWORD", None):
                with pytest.raises(RuntimeError, match="No Redmine authentication available"):
                    _get_redmine_client()
        finally:
            current_redmine_token.reset(token_var)

    def test_oauth_token_takes_priority_over_api_key(self):
        """OAuth ContextVar token wins even if REDMINE_API_KEY is also set."""
        from redmine_mcp_server.oauth_middleware import current_redmine_token
        from redmine_mcp_server.redmine_handler import _get_redmine_client
        import redmine_mcp_server.redmine_handler as rh

        token_var = current_redmine_token.set("oauth-wins")
        try:
            with patch.object(rh, "REDMINE_API_KEY", "should-not-be-used"), \
                 patch("redmine_mcp_server.redmine_handler.Redmine") as mock_redmine:
                _get_redmine_client()
                call_kwargs = mock_redmine.call_args.kwargs
                # Should use requests/headers, not key=
                assert "key" not in call_kwargs
                assert call_kwargs["requests"]["headers"]["Authorization"] == "Bearer oauth-wins"
        finally:
            current_redmine_token.reset(token_var)


# ---------------------------------------------------------------------------
# /revoke endpoint (RFC 7009 — OAuth 2.0 Token Revocation)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRevokeEndpoint:
    """Tests for the /revoke token revocation endpoint."""

    @pytest.fixture
    def app(self):
        from redmine_mcp_server.main import app, register_oauth_routes
        register_oauth_routes(app)
        return app

    @pytest.mark.asyncio
    async def test_revoke_with_bearer_header_success(self, app):
        """Token in Authorization header is forwarded to Redmine and returns success."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.main.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/revoke", headers={"Authorization": "Bearer test-token-123"}
                )

        assert response.status_code == 200
        assert response.json()["success"] is True
        # Verify token was forwarded to Redmine
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["data"]["token"] == "test-token-123"

    @pytest.mark.asyncio
    async def test_revoke_with_json_body_success(self, app):
        """Token in JSON body is forwarded to Redmine and returns success."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.main.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/revoke",
                    json={"token": "json-body-token"},
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        assert response.json()["success"] is True
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["data"]["token"] == "json-body-token"

    @pytest.mark.asyncio
    async def test_revoke_with_form_body_success(self, app):
        """Token in form-encoded body is forwarded to Redmine."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.main.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/revoke", data={"token": "form-token"}
                )

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_revoke_no_token_returns_400(self, app):
        """Returns 400 when no token is provided."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/revoke")

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_revoke_redmine_unreachable_returns_502(self, app):
        """Returns 502 when Redmine cannot be reached."""
        import httpx

        with patch("redmine_mcp_server.main.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.RequestError("connection refused")
            )
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/revoke", headers={"Authorization": "Bearer any-token"}
                )

        assert response.status_code == 502
        assert response.json()["error"] == "upstream_unavailable"

    @pytest.mark.asyncio
    async def test_revoke_returns_success_even_for_invalid_token(self, app):
        """Per RFC 7009, returns 200 even if Redmine says token is invalid."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid token"

        with patch("redmine_mcp_server.main.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/revoke", headers={"Authorization": "Bearer invalid-token"}
                )

        # RFC 7009: always return success to prevent token scanning
        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_revoke_calls_correct_redmine_endpoint(self, app):
        """Verifies the call goes to /oauth/revoke on Redmine."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.main.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post(
                    "/revoke", headers={"Authorization": "Bearer token"}
                )

            call_args = mock_client.post.call_args
            assert "/oauth/revoke" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_revoke_bypasses_oauth_middleware(self, app):
        """/revoke is accessible without OAuth middleware blocking it."""
        # This test verifies the endpoint is in SKIP_AUTH_PATHS
        # We don't mock httpx here - just verify no 401 from middleware
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("redmine_mcp_server.main.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Send token in body (not header) - if middleware ran, it would reject
                response = await client.post("/revoke", json={"token": "test"})

        # If we get here without 401, the middleware was bypassed
        assert response.status_code == 200
