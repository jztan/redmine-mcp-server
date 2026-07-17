"""Tests for OAuth per-tool scope enforcement (#185)."""

import pytest

from redmine_mcp_server._env import _is_scope_enforcement_enabled
from redmine_mcp_server.oauth_scopes import (
    TOOL_SCOPES,
    advertised_scopes,
    scopes_for_action,
    tool_visible,
)


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


class TestToolScopesMap:
    @pytest.mark.asyncio
    async def test_every_registered_tool_is_mapped(self):
        """Anti-drift guard: a new @mcp.tool() must get a TOOL_SCOPES entry."""
        from redmine_mcp_server.server import mcp
        import redmine_mcp_server.tools  # noqa: F401  triggers registration
        import redmine_mcp_server.apps  # noqa: F401  triggers registration

        tools = await mcp.list_tools()
        registered = {tool.name for tool in tools}
        mapped = set(TOOL_SCOPES)
        assert (
            registered <= mapped
        ), f"tools missing from TOOL_SCOPES: {registered - mapped}"
        # cleanup_attachment_files registers only when
        # REDMINE_ADMIN_TOOLS_ENABLED is truthy; it must still be mapped.
        conditional = {"cleanup_attachment_files"}
        stale = mapped - registered - conditional
        assert not stale, f"stale TOOL_SCOPES entries: {stale}"

    def test_every_enforced_scope_is_advertised(self):
        """Enforcement must never demand a scope the consent screen can't grant."""
        enforced: set = set()
        for entry in TOOL_SCOPES.values():
            if isinstance(entry, dict):
                for req in entry.values():
                    enforced |= req
            else:
                enforced |= entry
        # Baseline advertisement: read-only off, plugin flags off.
        advertised = set(advertised_scopes())
        assert (
            enforced <= advertised
        ), f"enforced but not advertised: {enforced - advertised}"

    def test_wiki_write_scopes_advertised(self):
        advertised = set(advertised_scopes())
        assert {"rename_wiki_pages", "delete_wiki_pages"} <= advertised


class TestScopeHelpers:
    def test_flat_entry_ignores_arguments(self):
        entry = frozenset({"edit_issues"})
        assert scopes_for_action(entry, {"anything": 1}) == entry
        assert scopes_for_action(entry, None) == entry

    def test_dict_entry_selects_action(self):
        entry = {
            "list": frozenset({"view_documents"}),
            "create": frozenset({"add_documents"}),
        }
        assert scopes_for_action(entry, {"action": "create"}) == frozenset(
            {"add_documents"}
        )

    def test_dict_entry_unknown_action_passes_through(self):
        entry = {"list": frozenset({"view_documents"})}
        assert scopes_for_action(entry, {"action": "explode"}) is None
        assert scopes_for_action(entry, {}) is None
        assert scopes_for_action(entry, None) is None

    def test_tool_visible_flat(self):
        assert tool_visible(frozenset({"view_issues"}), {"view_issues", "x"})
        assert not tool_visible(frozenset({"edit_issues"}), {"view_issues"})
        assert tool_visible(frozenset(), set())

    def test_tool_visible_dict_any_action(self):
        entry = {
            "list": frozenset({"view_documents"}),
            "create": frozenset({"add_documents"}),
        }
        assert tool_visible(entry, {"view_documents"})
        assert not tool_visible(entry, {"view_issues"})
