"""Tests for the Redmine request timeout (issue #214).

redminelib never passes a timeout to requests, so before this change a Redmine
that accepted a connection and never answered hung the call forever. These
tests lock in that every client carries a timeout and that the resulting
errors are distinguishable.
"""

from unittest.mock import MagicMock, patch

from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    ConnectTimeout,
    ReadTimeout,
)

from redmine_mcp_server import _client
from redmine_mcp_server._client import TimeoutSyncEngine
from redmine_mcp_server._env import get_redmine_timeout
from redmine_mcp_server._errors import _handle_redmine_error


class TestGetRedmineTimeout:
    def test_default_is_10_connect_30_read(self, monkeypatch):
        monkeypatch.delenv("REDMINE_TIMEOUT", raising=False)
        assert get_redmine_timeout() == (10.0, 30.0)

    def test_connect_never_exceeds_read(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "5")
        assert get_redmine_timeout() == (5.0, 5.0)

    def test_large_value_keeps_connect_at_10(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "300")
        assert get_redmine_timeout() == (10.0, 300.0)

    def test_zero_disables(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "0")
        assert get_redmine_timeout() is None

    def test_negative_disables(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "-1")
        assert get_redmine_timeout() is None

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "soon")
        assert get_redmine_timeout() == (10.0, 30.0)


class TestTimeoutSyncEngine:
    def test_injects_timeout_kwarg(self, monkeypatch):
        monkeypatch.delenv("REDMINE_TIMEOUT", raising=False)
        kwargs = TimeoutSyncEngine.construct_request_kwargs("get", {}, {}, None)
        assert kwargs["timeout"] == (10.0, 30.0)

    def test_keeps_base_kwargs(self, monkeypatch):
        monkeypatch.delenv("REDMINE_TIMEOUT", raising=False)
        kwargs = TimeoutSyncEngine.construct_request_kwargs(
            "get", {"X-Test": "1"}, {"limit": 5}, None
        )
        assert kwargs["headers"] == {"X-Test": "1"}
        assert kwargs["params"] == {"limit": 5}

    def test_omits_timeout_when_disabled(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "0")
        kwargs = TimeoutSyncEngine.construct_request_kwargs("get", {}, {}, None)
        assert "timeout" not in kwargs

    def test_read_at_request_time_not_build_time(self, monkeypatch):
        """The cached legacy client must see an env change without a rebuild."""
        monkeypatch.setenv("REDMINE_TIMEOUT", "7")
        assert TimeoutSyncEngine.construct_request_kwargs("get", {}, {}, None)[
            "timeout"
        ] == (7.0, 7.0)
        monkeypatch.setenv("REDMINE_TIMEOUT", "99")
        assert TimeoutSyncEngine.construct_request_kwargs("get", {}, {}, None)[
            "timeout"
        ] == (10.0, 99.0)


class TestEveryBuildPathIsTimed:
    """Every construction path must pass engine=TimeoutSyncEngine.

    Before this change the four branches were eight literal Redmine() calls,
    so it was possible to time half of them.
    """

    def _fake_redmine(self):
        return MagicMock(name="Redmine")

    def test_legacy_api_key_path(self, monkeypatch):
        fake = self._fake_redmine()
        monkeypatch.setattr(_client, "Redmine", fake)
        monkeypatch.setattr(_client, "REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setattr(_client, "REDMINE_API_KEY", "k")
        _client._build_legacy_client()
        assert fake.call_args.kwargs["engine"] is TimeoutSyncEngine

    def test_legacy_username_password_path(self, monkeypatch):
        fake = self._fake_redmine()
        monkeypatch.setattr(_client, "Redmine", fake)
        monkeypatch.setattr(_client, "REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setattr(_client, "REDMINE_API_KEY", "")
        monkeypatch.setattr(_client, "REDMINE_USERNAME", "u")
        monkeypatch.setattr(_client, "REDMINE_PASSWORD", "p")
        _client._build_legacy_client()
        assert fake.call_args.kwargs["engine"] is TimeoutSyncEngine

    def test_oauth_bearer_path(self, monkeypatch):
        fake = self._fake_redmine()
        monkeypatch.setattr(_client, "Redmine", fake)
        monkeypatch.setattr(_client, "redmine", None)
        monkeypatch.setattr(_client, "REDMINE_URL", "https://redmine.example.com")
        token = MagicMock()
        token.token = "bearer-token"
        with patch.object(_client, "get_access_token", return_value=token):
            _client._get_redmine_client()
        assert fake.call_args.kwargs["engine"] is TimeoutSyncEngine
        assert (
            fake.call_args.kwargs["requests"]["headers"]["Authorization"]
            == "Bearer bearer-token"
        )

    def test_legacy_per_user_path(self, monkeypatch):
        fake = self._fake_redmine()
        monkeypatch.setattr(_client, "Redmine", fake)
        monkeypatch.setattr(_client, "redmine", None)
        monkeypatch.setattr(_client, "REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setattr(_client, "REDMINE_AUTH_MODE", "legacy-per-user")
        with (
            patch.object(_client, "get_access_token", return_value=None),
            patch(
                "redmine_mcp_server._per_user.resolve_per_user_key", return_value="k"
            ),
            patch("redmine_mcp_server._per_user.maybe_log_identity"),
        ):
            _client._get_redmine_client()
        assert fake.call_args.kwargs["engine"] is TimeoutSyncEngine

    def test_ssl_config_still_reaches_the_client(self, monkeypatch):
        """engine= must compose with the existing requests= config."""
        fake = self._fake_redmine()
        monkeypatch.setattr(_client, "Redmine", fake)
        monkeypatch.setattr(_client, "REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setattr(_client, "REDMINE_API_KEY", "k")
        monkeypatch.setattr(_client, "REDMINE_SSL_VERIFY", False)
        _client._build_legacy_client()
        assert fake.call_args.kwargs["requests"]["verify"] is False
        assert fake.call_args.kwargs["engine"] is TimeoutSyncEngine


class TestTimeoutErrorMessages:
    def test_read_timeout_says_the_server_did_not_respond(self, monkeypatch):
        monkeypatch.delenv("REDMINE_TIMEOUT", raising=False)
        result = _handle_redmine_error(ReadTimeout("read timed out"), "get_issue")
        assert "did not respond in time" in result["error"]
        assert "REDMINE_TIMEOUT" in result["error"]

    def test_connect_timeout_is_not_reported_as_a_connection_error(self):
        """ConnectTimeout subclasses ConnectionError, so branch order matters."""
        result = _handle_redmine_error(ConnectTimeout("timed out"), "get_issue")
        assert "Timed out connecting" in result["error"]
        assert "URL is correct" not in result["error"]

    def test_plain_connection_error_still_reported_as_such(self):
        result = _handle_redmine_error(RequestsConnectionError("refused"), "get_issue")
        assert "Cannot connect to Redmine" in result["error"]

    def test_message_reports_the_configured_budget(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "45")
        result = _handle_redmine_error(ReadTimeout("read timed out"), "get_issue")
        assert "45" in result["error"]
