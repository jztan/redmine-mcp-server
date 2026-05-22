"""Tests for the RemoteAuthProvider factory."""

import importlib

import pytest


class TestBuildRemoteAuth:
    """Construction of RemoteAuthProvider + IntrospectionTokenVerifier."""

    def test_returns_remote_auth_provider(self, monkeypatch):
        from fastmcp.server.auth import RemoteAuthProvider

        monkeypatch.setenv("REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
        from redmine_mcp_server import _auth

        importlib.reload(_auth)
        provider = _auth.build_remote_auth()
        assert isinstance(provider, RemoteAuthProvider)

    def test_wires_introspection_url_from_redmine_url(self, monkeypatch):
        from fastmcp.server.auth.providers.introspection import (
            IntrospectionTokenVerifier,
        )

        monkeypatch.setenv("REDMINE_URL", "https://redmine.example.com/")
        monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
        from redmine_mcp_server import _auth

        importlib.reload(_auth)
        provider = _auth.build_remote_auth()
        assert isinstance(provider.token_verifier, IntrospectionTokenVerifier)
        assert provider.token_verifier.introspection_url == (
            "https://redmine.example.com/oauth/introspect"
        )

    def test_scopes_supported_uses_advertised_scopes(self, monkeypatch):
        monkeypatch.setenv("REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        from redmine_mcp_server import _auth, oauth_scopes

        importlib.reload(oauth_scopes)
        importlib.reload(_auth)
        from redmine_mcp_server.oauth_scopes import advertised_scopes

        provider = _auth.build_remote_auth()
        assert provider._scopes_supported == advertised_scopes()

    def test_scopes_supported_filtered_in_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        from redmine_mcp_server import _auth, oauth_scopes

        importlib.reload(oauth_scopes)
        importlib.reload(_auth)
        from redmine_mcp_server.oauth_scopes import WRITE_SCOPES

        provider = _auth.build_remote_auth()
        for write_scope in WRITE_SCOPES:
            assert write_scope not in provider._scopes_supported

    def test_raises_when_creds_missing(self, monkeypatch):
        monkeypatch.setenv("REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
        monkeypatch.delenv("REDMINE_INTROSPECT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDMINE_INTROSPECT_CLIENT_SECRET", raising=False)
        from redmine_mcp_server import _auth

        importlib.reload(_auth)
        with pytest.raises(RuntimeError, match="REDMINE_INTROSPECT_CLIENT_ID"):
            _auth.build_remote_auth()

    def test_required_scopes_unset_on_verifier(self, monkeypatch):
        """required_scopes intentionally unset — we advertise but don't enforce."""
        monkeypatch.setenv("REDMINE_URL", "https://redmine.example.com")
        monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
        monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
        from redmine_mcp_server import _auth

        importlib.reload(_auth)
        provider = _auth.build_remote_auth()
        assert provider.token_verifier.required_scopes in (None, [])
