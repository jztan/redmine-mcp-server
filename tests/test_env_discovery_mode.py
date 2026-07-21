"""Unit tests for REDMINE_OAUTH_DISCOVERY_AS parsing (#188)."""

import pytest

from redmine_mcp_server._env import _oauth_discovery_as


def test_default_is_redmine(monkeypatch):
    monkeypatch.delenv("REDMINE_OAUTH_DISCOVERY_AS", raising=False)
    assert _oauth_discovery_as() == "redmine"


def test_self_selected(monkeypatch):
    monkeypatch.setenv("REDMINE_OAUTH_DISCOVERY_AS", "self")
    assert _oauth_discovery_as() == "self"


def test_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("REDMINE_OAUTH_DISCOVERY_AS", "  SELF ")
    assert _oauth_discovery_as() == "self"


def test_invalid_value_raises(monkeypatch):
    monkeypatch.setenv("REDMINE_OAUTH_DISCOVERY_AS", "proxy")
    with pytest.raises(RuntimeError, match="REDMINE_OAUTH_DISCOVERY_AS"):
        _oauth_discovery_as()
