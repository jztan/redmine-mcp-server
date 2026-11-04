"""resolve_request_credential: one place that knows whose Redmine credential a
request carries (#440). _get_redmine_client builds its client from it, and the
text-formatting detector uses it to make its own httpx calls."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from redmine_mcp_server import _client
from redmine_mcp_server._per_user import PerUserAuthError

VALID_KEY = "a" * 40


def _token(**kw):
    return SimpleNamespace(token=kw.get("token", ""), claims=kw.get("claims"))


def test_api_key_login_uses_claim():
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"),
        patch.object(
            _client,
            "get_access_token",
            return_value=_token(token="jwt", claims={"redmine_api_key": "k"}),
        ),
    ):
        cred = _client.resolve_request_credential(strict=True)
    assert cred.kind == "api-key-login"
    assert cred.httpx_kwargs() == {"headers": {"X-Redmine-API-Key": "k"}}


def test_api_key_login_missing_claim():
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"),
        patch.object(_client, "get_access_token", return_value=_token(claims={})),
    ):
        with pytest.raises(PerUserAuthError):
            _client.resolve_request_credential(strict=True)
        assert _client.resolve_request_credential(strict=False) is None


def test_bearer():
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "oauth"),
        patch.object(_client, "get_access_token", return_value=_token(token="t")),
    ):
        cred = _client.resolve_request_credential(strict=True)
    assert cred.kind == "bearer"
    assert cred.httpx_kwargs() == {"headers": {"Authorization": "Bearer t"}}


def test_legacy_api_key():
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "legacy"),
        patch.object(_client, "get_access_token", return_value=None),
        patch.object(_client, "REDMINE_API_KEY", "lk"),
    ):
        cred = _client.resolve_request_credential(strict=True)
    assert cred.kind == "legacy"
    assert cred.httpx_kwargs() == {"headers": {"X-Redmine-API-Key": "lk"}}


def test_legacy_basic():
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "legacy"),
        patch.object(_client, "get_access_token", return_value=None),
        patch.object(_client, "REDMINE_API_KEY", ""),
        patch.object(_client, "REDMINE_USERNAME", "u"),
        patch.object(_client, "REDMINE_PASSWORD", "p"),
    ):
        cred = _client.resolve_request_credential(strict=True)
    assert cred.httpx_kwargs() == {"auth": ("u", "p")}


def test_legacy_none():
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "legacy"),
        patch.object(_client, "get_access_token", return_value=None),
        patch.object(_client, "REDMINE_API_KEY", ""),
        patch.object(_client, "REDMINE_USERNAME", ""),
        patch.object(_client, "REDMINE_PASSWORD", ""),
    ):
        assert _client.resolve_request_credential(strict=True) is None


def test_per_user_header():
    req = MagicMock()
    req.headers = {"X-Redmine-API-Key": VALID_KEY}
    req.url.scheme = "https"
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "legacy-per-user"),
        patch.object(_client, "get_access_token", return_value=None),
        patch.object(_client, "get_http_request", return_value=req),
        patch("redmine_mcp_server._per_user.resolve_per_user_key", return_value=VALID_KEY),
        patch("redmine_mcp_server._per_user.validate_key_with_redmine") as validate,
    ):
        cred = _client.resolve_request_credential(strict=True)
    assert cred.kind == "per-user"
    assert cred.api_key == VALID_KEY
    validate.assert_not_called()  # the resolver never touches the network


def test_per_user_missing_header():
    with (
        patch.object(_client, "REDMINE_AUTH_MODE", "legacy-per-user"),
        patch.object(_client, "get_access_token", return_value=None),
        patch.object(_client, "get_http_request", side_effect=RuntimeError("no request")),
    ):
        with pytest.raises(PerUserAuthError):
            _client.resolve_request_credential(strict=True)
        assert _client.resolve_request_credential(strict=False) is None


def test_cache_key_hides_secret():
    a = _client.RequestCredential(kind="legacy", api_key="secret-key")
    b = _client.RequestCredential(kind="legacy", api_key="secret-key")
    c = _client.RequestCredential(kind="legacy", basic=("u", "secret-pw"))
    assert "secret" not in a.cache_key()
    assert "secret" not in c.cache_key()
    assert a.cache_key() == b.cache_key()
    assert a.cache_key() != c.cache_key()
