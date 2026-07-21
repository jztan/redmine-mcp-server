"""Unit tests for REDMINE_MCP_SCOPES advertised-scope subsetting (#189)."""

import importlib

import pytest


def _reload_scopes(monkeypatch, **env):
    for key in (
        "REDMINE_MCP_SCOPES",
        "REDMINE_MCP_READ_ONLY",
        "REDMINE_AGILE_ENABLED",
        "REDMINE_TAGS_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from redmine_mcp_server import oauth_scopes

    importlib.reload(oauth_scopes)
    return oauth_scopes


def test_unset_returns_full_catalogue(monkeypatch):
    mod = _reload_scopes(monkeypatch)
    assert mod.configured_advertised_scopes() == mod.advertised_scopes()


def test_blank_returns_full_catalogue(monkeypatch):
    mod = _reload_scopes(monkeypatch, REDMINE_MCP_SCOPES="   ")
    assert mod.configured_advertised_scopes() == mod.advertised_scopes()


def test_valid_subset_narrows_in_advertised_order(monkeypatch):
    mod = _reload_scopes(
        monkeypatch,
        REDMINE_MCP_SCOPES="view_issues view_project add_issue_notes",
    )
    result = mod.configured_advertised_scopes()
    assert result == ["view_project", "view_issues", "add_issue_notes"]


def test_duplicate_requests_deduped(monkeypatch):
    mod = _reload_scopes(monkeypatch, REDMINE_MCP_SCOPES="view_issues view_issues")
    assert mod.configured_advertised_scopes() == ["view_issues"]


def test_unknown_scope_raises(monkeypatch):
    mod = _reload_scopes(monkeypatch, REDMINE_MCP_SCOPES="view_issues not_a_scope")
    with pytest.raises(RuntimeError, match="not_a_scope"):
        mod.configured_advertised_scopes()


def test_write_scope_rejected_in_read_only_mode(monkeypatch):
    mod = _reload_scopes(
        monkeypatch,
        REDMINE_MCP_READ_ONLY="true",
        REDMINE_MCP_SCOPES="view_issues edit_issues",
    )
    with pytest.raises(RuntimeError, match="edit_issues"):
        mod.configured_advertised_scopes()


def test_duplicate_invalid_scope_not_repeated_in_error(monkeypatch):
    mod = _reload_scopes(monkeypatch, REDMINE_MCP_SCOPES="nope nope")
    with pytest.raises(RuntimeError) as exc:
        mod.configured_advertised_scopes()
    # "nope" appears once in the invalid-scopes portion, not twice
    msg = str(exc.value)
    invalid_part = msg.split("Allowed:")[0]
    assert invalid_part.count("nope") == 1
