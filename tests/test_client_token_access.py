"""Tests for _get_redmine_client() OAuth-mode token access via get_access_token()."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestOAuthClientBuilding:
    """_get_redmine_client builds an OAuth Redmine when AccessToken is present."""

    def test_uses_token_from_get_access_token(self):
        from redmine_mcp_server import _client

        with (
            patch.object(_client, "REDMINE_URL", "https://r.example.com"),
            patch.object(_client, "redmine", None),
            patch.object(_client, "_legacy_client", None),
            patch.object(_client, "Redmine") as mock_redmine,
            patch("redmine_mcp_server._client.get_access_token") as mock_get_token,
        ):
            access = MagicMock()
            access.token = "bearer-abc"
            mock_get_token.return_value = access
            _client._get_redmine_client()
            mock_redmine.assert_called_once()
            kwargs = mock_redmine.call_args.kwargs
            assert kwargs["requests"]["headers"] == {
                "Authorization": "Bearer bearer-abc"
            }

    def test_falls_through_to_legacy_when_no_access_token(self):
        from redmine_mcp_server import _client

        with (
            patch.object(_client, "REDMINE_URL", "https://r.example.com"),
            patch.object(_client, "REDMINE_API_KEY", "legacy-key"),
            patch.object(_client, "redmine", None),
            patch.object(_client, "_legacy_client", None),
            patch.object(_client, "Redmine") as mock_redmine,
            patch("redmine_mcp_server._client.get_access_token", return_value=None),
        ):
            _client._get_redmine_client()
            mock_redmine.assert_called_once_with(
                "https://r.example.com", key="legacy-key"
            )

    def test_no_circular_oauth_middleware_import(self):
        """oauth_middleware no longer exists; _client must not import from it."""
        import inspect

        from redmine_mcp_server import _client

        source = inspect.getsource(_client)
        assert "oauth_middleware" not in source
        assert "current_redmine_token" not in source
