"""Tests for OAuth per-tool scope enforcement (#185)."""

import json
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP

import redmine_mcp_server._scope_middleware as scope_mw
from redmine_mcp_server._env import _is_scope_enforcement_enabled
from redmine_mcp_server._scope_middleware import ScopeEnforcementMiddleware
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


def _make_server():
    mcp = FastMCP("scope-test")
    mcp.add_middleware(ScopeEnforcementMiddleware())

    @mcp.tool()
    async def update_redmine_issue(issue_id: int) -> dict:
        return {"updated": issue_id}

    @mcp.tool()
    async def list_redmine_issues(project_id: str) -> dict:
        return {"issues": []}

    @mcp.tool()
    async def manage_document(action: str, project_id: str = "") -> dict:
        return {"action": action}

    @mcp.tool()
    async def get_current_user() -> dict:
        return {"user": "me"}

    @mcp.tool()
    async def not_in_map_tool() -> dict:
        return {"ok": True}

    return mcp


def _fake_token(scopes):
    return SimpleNamespace(token="t", scopes=list(scopes))


@pytest.fixture
def scoped_token(monkeypatch):
    """Patch get_access_token as seen by the middleware module."""

    def _set(scopes):
        monkeypatch.setattr(scope_mw, "get_access_token", lambda: _fake_token(scopes))

    return _set


class TestCallToolGating:
    @pytest.mark.asyncio
    async def test_no_token_passes_through(self, monkeypatch):
        # Legacy / legacy-per-user / background: middleware is inert.
        monkeypatch.setattr(scope_mw, "get_access_token", lambda: None)
        async with Client(_make_server()) as client:
            result = await client.call_tool("update_redmine_issue", {"issue_id": 1})
        assert result.structured_content == {"updated": 1}

    @pytest.mark.asyncio
    async def test_token_with_scope_passes(self, scoped_token):
        scoped_token(["edit_issues"])
        async with Client(_make_server()) as client:
            result = await client.call_tool("update_redmine_issue", {"issue_id": 1})
        assert result.structured_content == {"updated": 1}

    @pytest.mark.asyncio
    async def test_token_without_scope_denied(self, scoped_token):
        # The exact #185 repro: view+notes token must not edit.
        scoped_token(["view_issues", "add_issue_notes"])
        async with Client(_make_server()) as client:
            result = await client.call_tool("update_redmine_issue", {"issue_id": 1})
        payload = json.loads(result.content[0].text)
        assert payload["code"] == "INSUFFICIENT_SCOPE"
        assert "edit_issues" in payload["error"]
        assert "edit_issues" in payload["hint"]

    @pytest.mark.asyncio
    async def test_admin_scope_bypasses(self, scoped_token):
        scoped_token(["admin"])
        async with Client(_make_server()) as client:
            result = await client.call_tool("update_redmine_issue", {"issue_id": 1})
        assert result.structured_content == {"updated": 1}

    @pytest.mark.asyncio
    async def test_empty_scope_token_denied(self, scoped_token):
        # Pre-#130 tokens introspect with scope: "" and must be denied.
        scoped_token([])
        async with Client(_make_server()) as client:
            result = await client.call_tool("update_redmine_issue", {"issue_id": 1})
        payload = json.loads(result.content[0].text)
        assert payload["code"] == "INSUFFICIENT_SCOPE"

    @pytest.mark.asyncio
    async def test_empty_requirement_allows_any_token(self, scoped_token):
        scoped_token([])
        async with Client(_make_server()) as client:
            result = await client.call_tool("get_current_user", {})
        assert result.structured_content == {"user": "me"}

    @pytest.mark.asyncio
    async def test_unmapped_tool_denied(self, scoped_token):
        scoped_token(["view_issues", "edit_issues"])
        async with Client(_make_server()) as client:
            result = await client.call_tool("not_in_map_tool", {})
        payload = json.loads(result.content[0].text)
        assert payload["code"] == "INSUFFICIENT_SCOPE"
        assert "not_in_map_tool" in payload["error"]

    @pytest.mark.asyncio
    async def test_action_aware_read_allowed_write_denied(self, scoped_token):
        scoped_token(["view_documents"])
        async with Client(_make_server()) as client:
            ok = await client.call_tool(
                "manage_document", {"action": "list", "project_id": "p"}
            )
            denied = await client.call_tool(
                "manage_document", {"action": "create", "project_id": "p"}
            )
        assert ok.structured_content == {"action": "list"}
        payload = json.loads(denied.content[0].text)
        assert payload["code"] == "INSUFFICIENT_SCOPE"
        assert "add_documents" in payload["error"]

    @pytest.mark.asyncio
    async def test_unknown_action_passes_to_tool(self, scoped_token):
        # Middleware must not mask the tool's own invalid-action error.
        scoped_token(["view_documents"])
        async with Client(_make_server()) as client:
            result = await client.call_tool(
                "manage_document", {"action": "explode", "project_id": "p"}
            )
        # Reaches the (test) tool body: no scope denial.
        assert result.structured_content == {"action": "explode"}


class TestListToolsFiltering:
    @pytest.mark.asyncio
    async def test_no_token_sees_all(self, monkeypatch):
        monkeypatch.setattr(scope_mw, "get_access_token", lambda: None)
        async with Client(_make_server()) as client:
            tools = {t.name for t in await client.list_tools()}
        assert "update_redmine_issue" in tools
        assert "not_in_map_tool" in tools

    @pytest.mark.asyncio
    async def test_scoped_token_sees_only_permitted(self, scoped_token):
        scoped_token(["view_documents"])
        async with Client(_make_server()) as client:
            tools = {t.name for t in await client.list_tools()}
        # Dict entry visible because ANY action (list/get) is permitted.
        assert "manage_document" in tools
        # frozenset() entry: always visible to authenticated tokens.
        assert "get_current_user" in tools
        # Missing scope: hidden.
        assert "update_redmine_issue" not in tools
        assert "list_redmine_issues" not in tools
        # Unmapped: hidden (deny-by-default).
        assert "not_in_map_tool" not in tools

    @pytest.mark.asyncio
    async def test_admin_sees_all(self, scoped_token):
        scoped_token(["admin"])
        async with Client(_make_server()) as client:
            tools = {t.name for t in await client.list_tools()}
        assert "not_in_map_tool" in tools
        assert "update_redmine_issue" in tools
