"""Tests for OAuth per-tool scope enforcement (#185)."""

import pytest

from redmine_mcp_server._env import _is_scope_enforcement_enabled


class TestScopeEnforcementFlag:
    def test_default_is_enabled(self, monkeypatch):
        monkeypatch.delenv("REDMINE_OAUTH_SCOPE_ENFORCEMENT", raising=False)
        assert _is_scope_enforcement_enabled() is True

    @pytest.mark.parametrize("value", ["off", "false", "0", "no", "OFF"])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("REDMINE_OAUTH_SCOPE_ENFORCEMENT", value)
        assert _is_scope_enforcement_enabled() is False

    @pytest.mark.parametrize("value", ["on", "true", "1", "yes", "ON"])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("REDMINE_OAUTH_SCOPE_ENFORCEMENT", value)
        assert _is_scope_enforcement_enabled() is True
