"""Unit tests for src/redmine_mcp_server/oauth_scopes.py."""

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScopeConstants:
    def test_read_scopes_contains_view_issues(self):
        from redmine_mcp_server.oauth_scopes import READ_SCOPES

        assert "view_issues" in READ_SCOPES

    def test_read_scopes_contains_project_basics(self):
        from redmine_mcp_server.oauth_scopes import READ_SCOPES

        for s in ("view_project", "search_project", "view_members"):
            assert s in READ_SCOPES, f"missing {s}"

    def test_write_scopes_contains_issue_writes(self):
        from redmine_mcp_server.oauth_scopes import WRITE_SCOPES

        for s in ("add_issues", "edit_issues", "delete_issues"):
            assert s in WRITE_SCOPES, f"missing {s}"

    def test_write_scopes_contains_relation_and_watcher_scopes(self):
        """Regression pin for the fact-check finding (issue #130 review)."""
        from redmine_mcp_server.oauth_scopes import WRITE_SCOPES

        for s in (
            "manage_issue_relations",
            "add_issue_watchers",
            "delete_issue_watchers",
        ):
            assert s in WRITE_SCOPES, f"missing {s}"

    def test_read_scopes_does_not_contain_admin(self):
        from redmine_mcp_server.oauth_scopes import READ_SCOPES

        assert "admin" not in READ_SCOPES

    def test_write_scopes_does_not_contain_admin(self):
        from redmine_mcp_server.oauth_scopes import WRITE_SCOPES

        assert "admin" not in WRITE_SCOPES

    def test_no_vendor_specific_scopes_leak_in(self):
        """Plugin-specific scopes must not appear in the advertised list."""
        from redmine_mcp_server.oauth_scopes import READ_SCOPES, WRITE_SCOPES

        vendor_scopes = {
            "view_easy_calendar",
            "view_easy_gantt",
            "view_redmineup_agile",
            "edit_redmineup_agile",
            "view_redmineup_checklists",
            "edit_redmineup_checklists",
            "view_contacts",
            "edit_contacts",
            "view_products",
            "edit_products",
        }
        combined = set(READ_SCOPES) | set(WRITE_SCOPES)
        leaked = combined & vendor_scopes
        assert not leaked, f"vendor scopes leaked: {leaked}"

    def test_view_private_notes_is_a_read_scope(self):
        """Regression pin: view_private_notes was once miscategorized as write."""
        from redmine_mcp_server.oauth_scopes import READ_SCOPES, WRITE_SCOPES

        assert "view_private_notes" in READ_SCOPES
        assert "view_private_notes" not in WRITE_SCOPES


# ---------------------------------------------------------------------------
# advertised_scopes()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdvertisedScopes:
    def test_includes_read_scopes_by_default(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        from redmine_mcp_server.oauth_scopes import READ_SCOPES, advertised_scopes

        result = advertised_scopes()
        for s in READ_SCOPES:
            assert s in result, f"missing read scope {s}"

    def test_includes_write_scopes_by_default(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        from redmine_mcp_server.oauth_scopes import WRITE_SCOPES, advertised_scopes

        result = advertised_scopes()
        for s in WRITE_SCOPES:
            assert s in result, f"missing write scope {s}"

    @pytest.mark.parametrize(
        "value",
        ["true", "TRUE", "True", "1", "yes", "YES", "Yes", "on", "ON"],
    )
    def test_excludes_write_scopes_when_read_only(self, monkeypatch, value):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", value)
        from redmine_mcp_server.oauth_scopes import WRITE_SCOPES, advertised_scopes

        result = advertised_scopes()
        for s in WRITE_SCOPES:
            assert (
                s not in result
            ), f"write scope {s} leaked when REDMINE_MCP_READ_ONLY={value!r}"

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "anything-else"])
    def test_includes_write_scopes_when_env_is_falsy(self, monkeypatch, value):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", value)
        from redmine_mcp_server.oauth_scopes import WRITE_SCOPES, advertised_scopes

        result = advertised_scopes()
        for s in WRITE_SCOPES:
            assert (
                s in result
            ), f"write scope {s} missing when REDMINE_MCP_READ_ONLY={value!r}"

    def test_returns_fresh_list_each_call(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        from redmine_mcp_server.oauth_scopes import READ_SCOPES, advertised_scopes

        first = advertised_scopes()
        first.append("MUTATED")
        second = advertised_scopes()
        assert "MUTATED" not in second
        # Module-level constant is also intact
        assert "MUTATED" not in READ_SCOPES
