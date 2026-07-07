"""Unit tests for src/redmine_mcp_server/oauth_scopes.py."""

from pathlib import Path

import pytest

_PERMS_FIXTURE = Path(__file__).parent / "fixtures" / "redmine_6_permissions.txt"


def _load_redmine_permissions() -> set[str]:
    return {
        line.strip()
        for line in _PERMS_FIXTURE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


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

    def test_advertised_scopes_are_real_redmine_permissions(self):
        """Every advertised scope must be a real Redmine permission.

        Regression guard for issue #130 follow-up: the original fix shipped
        ``manage_documents`` (inferred from the ``manage_X`` pattern), but
        Redmine's document permissions are actually
        ``add_documents`` / ``edit_documents`` / ``delete_documents``.
        Doorkeeper's ``enforce_configured_scopes`` rejects unknown scopes
        with ``invalid_scope`` at the ``/oauth/authorize`` step, breaking
        the entire consent flow.

        The fixture is a snapshot of ``Redmine::AccessControl.permissions``
        from a stock Redmine 6.x install (plus whatever plugin permissions
        the snapshot host happens to load -- treated as a superset).
        """
        from redmine_mcp_server.oauth_scopes import READ_SCOPES, WRITE_SCOPES

        valid = _load_redmine_permissions()
        invalid = [s for s in (*READ_SCOPES, *WRITE_SCOPES) if s not in valid]
        assert not invalid, (
            "advertised scope(s) not present in Redmine::AccessControl.permissions; "
            "Doorkeeper will reject them with invalid_scope at /oauth/authorize: "
            f"{invalid}"
        )

    def test_view_private_notes_is_a_read_scope(self):
        """Regression pin: view_private_notes was once miscategorized as write."""
        from redmine_mcp_server.oauth_scopes import READ_SCOPES, WRITE_SCOPES

        assert "view_private_notes" in READ_SCOPES
        assert "view_private_notes" not in WRITE_SCOPES

    def test_agile_read_scopes_contains_view_agile_queries(self):
        """Issue #173: agile_data endpoint is gated on view_agile_queries."""
        from redmine_mcp_server.oauth_scopes import AGILE_READ_SCOPES

        assert "view_agile_queries" in AGILE_READ_SCOPES

    def test_agile_scope_not_in_core_scope_lists(self):
        """The agile scope is opt-in only; core lists stay plugin-free."""
        from redmine_mcp_server.oauth_scopes import READ_SCOPES, WRITE_SCOPES

        assert "view_agile_queries" not in READ_SCOPES
        assert "view_agile_queries" not in WRITE_SCOPES


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

    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE"])
    def test_includes_agile_scope_when_agile_enabled(self, monkeypatch, value):
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        monkeypatch.setenv("REDMINE_AGILE_ENABLED", value)
        from redmine_mcp_server.oauth_scopes import advertised_scopes

        assert "view_agile_queries" in advertised_scopes()

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
    def test_excludes_agile_scope_when_agile_disabled(self, monkeypatch, value):
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        monkeypatch.setenv("REDMINE_AGILE_ENABLED", value)
        from redmine_mcp_server.oauth_scopes import advertised_scopes

        assert "view_agile_queries" not in advertised_scopes()

    def test_excludes_agile_scope_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        monkeypatch.delenv("REDMINE_AGILE_ENABLED", raising=False)
        from redmine_mcp_server.oauth_scopes import advertised_scopes

        assert "view_agile_queries" not in advertised_scopes()

    def test_agile_scope_present_in_read_only_mode(self, monkeypatch):
        """view_agile_queries is a read permission, so read-only keeps it."""
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        monkeypatch.setenv("REDMINE_AGILE_ENABLED", "true")
        from redmine_mcp_server.oauth_scopes import advertised_scopes

        assert "view_agile_queries" in advertised_scopes()
