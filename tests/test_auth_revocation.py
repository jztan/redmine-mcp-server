"""Tests for RedmineAuthProvider.revoke_token (RFC 7009 proxy).

The provider proxies revocation to Redmine's Doorkeeper `/oauth/revoke`
endpoint. These tests call the handler directly with hand-built Starlette
requests so no real network client is involved, and stub `httpx.AsyncClient`
inside the `_auth` module to capture what would be sent upstream.
"""

import json

import httpx
import pytest
from pydantic import AnyHttpUrl
from starlette.requests import Request

from redmine_mcp_server import _auth


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _Recorder:
    """Captures the upstream POST made by revoke_token."""

    def __init__(self, response=None, error=None):
        self.response = response or _FakeResponse()
        self.error = error
        self.client_kwargs = None
        self.post_args = None

    def client_factory(self, **kwargs):
        self.client_kwargs = kwargs
        return _FakeAsyncClient(self)


class _FakeAsyncClient:
    def __init__(self, recorder):
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, data=None, timeout=None):
        self._recorder.post_args = {"url": url, "data": data, "timeout": timeout}
        if self._recorder.error is not None:
            raise self._recorder.error
        return self._recorder.response


@pytest.fixture
def provider():
    return _auth.RedmineAuthProvider(
        redmine_url=AnyHttpUrl("https://r.example.com"),
        base_url="http://localhost:3040",
        introspect_client_id="cid",
        introspect_client_secret="csec",
        scopes_supported=["redmine:read"],
    )


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(_auth.httpx, "AsyncClient", rec.client_factory)
    return rec


def make_request(headers=None, body=b"") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/revoke",
        "raw_path": b"/revoke",
        "query_string": b"",
        "root_path": "",
        "server": ("test", 80),
        "client": ("test", 1234),
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


class TestTokenExtraction:
    """The token may arrive in a Bearer header, a JSON body, or a form body."""

    @pytest.mark.asyncio
    async def test_bearer_header_token_is_proxied(self, provider, recorder):
        request = make_request(headers={"Authorization": "Bearer abc123"})

        response = await provider.revoke_token(request)

        assert response.status_code == 200
        assert json.loads(response.body) == {"success": True}
        assert recorder.post_args["url"] == "https://r.example.com/oauth/revoke"
        assert recorder.post_args["data"] == {"token": "abc123"}
        assert recorder.post_args["timeout"] == 10

    @pytest.mark.asyncio
    async def test_json_body_token_is_proxied(self, provider, recorder):
        request = make_request(
            headers={"Content-Type": "application/json"},
            body=b'{"token": "json-token"}',
        )

        response = await provider.revoke_token(request)

        assert response.status_code == 200
        assert recorder.post_args["data"] == {"token": "json-token"}

    @pytest.mark.asyncio
    async def test_form_body_token_is_proxied(self, provider, recorder):
        request = make_request(
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=b"token=form-token",
        )

        response = await provider.revoke_token(request)

        assert response.status_code == 200
        assert recorder.post_args["data"] == {"token": "form-token"}

    @pytest.mark.asyncio
    async def test_empty_bearer_header_falls_back_to_body(self, provider, recorder):
        request = make_request(
            headers={
                "Authorization": "Bearer ",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=b"token=body-token",
        )

        response = await provider.revoke_token(request)

        assert response.status_code == 200
        assert recorder.post_args["data"] == {"token": "body-token"}

    @pytest.mark.asyncio
    async def test_non_bearer_authorization_header_is_ignored(self, provider, recorder):
        request = make_request(
            headers={
                "Authorization": "Basic dXNlcjpwYXNz",
                "Content-Type": "application/json",
            },
            body=b'{"token": "json-token"}',
        )

        response = await provider.revoke_token(request)

        assert response.status_code == 200
        assert recorder.post_args["data"] == {"token": "json-token"}


class TestMissingToken:
    """No token means a 400 and no upstream call."""

    @pytest.mark.asyncio
    async def test_no_token_anywhere_returns_400(self, provider, recorder):
        response = await provider.revoke_token(make_request())

        assert response.status_code == 400
        assert json.loads(response.body) == {
            "error": "invalid_request",
            "error_description": "No token provided",
        }
        assert recorder.post_args is None

    @pytest.mark.asyncio
    async def test_malformed_json_body_returns_400(self, provider, recorder):
        request = make_request(
            headers={"Content-Type": "application/json"},
            body=b"{not json",
        )

        response = await provider.revoke_token(request)

        assert response.status_code == 400
        assert recorder.post_args is None

    @pytest.mark.asyncio
    async def test_unparseable_form_body_returns_400(self, provider, recorder):
        request = make_request(
            headers={"Content-Type": "multipart/form-data; boundary=xyz"},
            body=b"not a valid multipart body",
        )

        response = await provider.revoke_token(request)

        assert response.status_code == 400
        assert recorder.post_args is None

    @pytest.mark.asyncio
    async def test_json_body_without_token_key_returns_400(self, provider, recorder):
        request = make_request(
            headers={"Content-Type": "application/json"},
            body=b'{"other": "value"}',
        )

        response = await provider.revoke_token(request)

        assert response.status_code == 400
        assert recorder.post_args is None


class TestUpstreamBehaviour:
    """How the proxy reacts to Redmine's answer (or lack of one)."""

    @pytest.mark.asyncio
    async def test_unreachable_redmine_returns_502(self, provider, monkeypatch):
        rec = _Recorder(error=httpx.ConnectError("connection refused"))
        monkeypatch.setattr(_auth.httpx, "AsyncClient", rec.client_factory)

        response = await provider.revoke_token(
            make_request(headers={"Authorization": "Bearer abc123"})
        )

        assert response.status_code == 502
        assert json.loads(response.body) == {"error": "upstream_unavailable"}

    @pytest.mark.asyncio
    async def test_upstream_error_status_still_returns_success(
        self, provider, monkeypatch, caplog
    ):
        """RFC 7009: the client must not learn whether the token existed."""
        rec = _Recorder(response=_FakeResponse(status_code=503, text="down"))
        monkeypatch.setattr(_auth.httpx, "AsyncClient", rec.client_factory)

        with caplog.at_level("WARNING", logger=_auth.logger.name):
            response = await provider.revoke_token(
                make_request(headers={"Authorization": "Bearer abc123"})
            )

        assert response.status_code == 200
        assert json.loads(response.body) == {"success": True}
        assert "503" in caplog.text

    @pytest.mark.asyncio
    async def test_204_upstream_is_not_logged_as_warning(
        self, provider, monkeypatch, caplog
    ):
        rec = _Recorder(response=_FakeResponse(status_code=204))
        monkeypatch.setattr(_auth.httpx, "AsyncClient", rec.client_factory)

        with caplog.at_level("WARNING", logger=_auth.logger.name):
            response = await provider.revoke_token(
                make_request(headers={"Authorization": "Bearer abc123"})
            )

        assert response.status_code == 200
        assert caplog.text == ""

    @pytest.mark.asyncio
    async def test_ssl_settings_are_applied_to_the_upstream_client(
        self, provider, recorder, monkeypatch
    ):
        """REDMINE_SSL_VERIFY must reach the revocation client too.

        The setting is read into a module constant at import time, so the
        constant is what gets patched here.
        """
        from redmine_mcp_server import _client

        monkeypatch.setattr(_client, "REDMINE_SSL_VERIFY", False)

        await provider.revoke_token(
            make_request(headers={"Authorization": "Bearer abc123"})
        )

        assert recorder.client_kwargs.get("verify") is False


class TestRouteWiring:
    """The /revoke route is exposed by get_routes."""

    def test_revoke_route_registered(self, provider):
        routes = provider.get_routes(mcp_path="/mcp")
        revoke = [r for r in routes if r.path == "/revoke"]
        assert len(revoke) == 1
        assert "POST" in revoke[0].methods
