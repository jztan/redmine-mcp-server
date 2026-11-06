"""The syntax block appended to text-writing tools at tools/list (#440)."""

from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP

from redmine_mcp_server import _client
from redmine_mcp_server import server as _server
from redmine_mcp_server import tools  # noqa: F401
from redmine_mcp_server._text_formatting import (
    FORMATTED_TEXT_TOOLS,
    SERVER_INSTRUCTIONS,
    TEXT_BLOCKS,
)

MARKER = "Text formatting on this Redmine"


@pytest.fixture(autouse=True)
def _full_surface(all_plugin_tools_visible):
    yield


async def _listed():
    async with Client(_server.mcp) as client:
        return {t.name: t for t in await client.list_tools()}


@pytest.mark.parametrize("fmt", ["markdown", "common_mark", "textile", "none"])
async def test_block_on_text_tools(monkeypatch, fmt):
    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", fmt)
    listed = await _listed()
    for name in FORMATTED_TEXT_TOOLS:
        assert listed[name].description.endswith(TEXT_BLOCKS[fmt]), name
    assert MARKER not in (listed["list_redmine_issues"].description or "")
    assert TEXT_BLOCKS[fmt] not in (listed["list_redmine_issues"].description or "")


async def test_unknown_block_when_detection_fails():
    listed = await _listed()  # auto + the conftest detector that always fails
    for name in FORMATTED_TEXT_TOOLS:
        assert listed[name].description.endswith(TEXT_BLOCKS["unknown"]), name


async def test_registered_tools_not_mutated(monkeypatch):
    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", "markdown")
    await _listed()
    listed = await _listed()
    assert listed["manage_issue_note"].description.count(MARKER) == 1
    registered = await _server.mcp.get_tool("manage_issue_note")
    assert MARKER not in registered.description


async def test_list_tools_survives_missing_credentials(monkeypatch):
    monkeypatch.setattr(_client, "REDMINE_AUTH_MODE", "legacy-per-user")
    listed = await _listed()
    assert FORMATTED_TEXT_TOOLS <= set(listed)
    assert "list_redmine_issues" in listed
    assert listed["update_redmine_issue"].description.endswith(TEXT_BLOCKS["unknown"])


async def test_resolution_error_falls_back_to_unknown(monkeypatch):
    from redmine_mcp_server import _text_formatting_middleware as mw

    async def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(mw, "current_format", broken)
    listed = await _listed()
    assert listed["manage_issue_note"].description.endswith(TEXT_BLOCKS["unknown"])


async def test_annotations_preserved(monkeypatch):
    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", "textile")
    listed = await _listed()
    registered = await _server.mcp.get_tool("manage_issue_note")
    assert listed["manage_issue_note"].annotations == registered.annotations


def _probe_server():
    from redmine_mcp_server.server import _register_middlewares

    probe = FastMCP("text-formatting-probe")
    _register_middlewares(probe, auth_provider=object())

    @probe.tool()
    async def update_redmine_issue(issue_id: int) -> dict:
        """Update an issue."""
        return {}

    @probe.tool()
    async def create_redmine_issue(project_id: int) -> dict:
        return {}

    @probe.tool()
    async def list_redmine_issues(project_id: str) -> dict:
        """List issues."""
        return {}

    return probe


async def test_scope_filter_still_applies(monkeypatch):
    from redmine_mcp_server import _scope_middleware as scope_mw

    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", "markdown")
    monkeypatch.delenv("REDMINE_OAUTH_SCOPE_ENFORCEMENT", raising=False)
    monkeypatch.setattr(
        scope_mw,
        "get_access_token",
        lambda: SimpleNamespace(token="t", scopes=["view_issues"]),
    )
    async with Client(_probe_server()) as client:
        names = {t.name: t for t in await client.list_tools()}
    assert "update_redmine_issue" not in names  # filtered by scope
    assert "list_redmine_issues" in names
    assert MARKER not in (names["list_redmine_issues"].description or "")


async def test_tool_without_description(monkeypatch):
    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", "textile")
    monkeypatch.setenv("REDMINE_OAUTH_SCOPE_ENFORCEMENT", "off")
    async with Client(_probe_server()) as client:
        names = {t.name: t for t in await client.list_tools()}
    assert names["create_redmine_issue"].description == TEXT_BLOCKS["textile"]
    assert names["update_redmine_issue"].description.startswith("Update an issue.")


def test_server_instructions_set():
    assert _server.mcp.instructions == SERVER_INSTRUCTIONS


def test_middleware_registered_in_every_mode():
    from redmine_mcp_server.server import _register_middlewares

    for provider in (None, object()):
        instance = FastMCP("wiring")
        _register_middlewares(instance, auth_provider=provider)
        assert "TextFormattingMiddleware" in [type(m).__name__ for m in instance.middleware]


def test_invalid_setting_fails_registration(monkeypatch):
    from redmine_mcp_server.server import _register_middlewares

    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", "md")
    with pytest.raises(RuntimeError, match="REDMINE_TEXT_FORMATTING"):
        _register_middlewares(FastMCP("wiring"), auth_provider=None)
