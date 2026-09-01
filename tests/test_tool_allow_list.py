"""Only allow-listed tools are exposed, and the list can never widen."""

import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from redmine_mcp_server import server as _server
from redmine_mcp_server import tools  # noqa: F401  -- triggers @mcp.tool
from redmine_mcp_server._env import get_allowed_tools
from redmine_mcp_server._plugin_visibility import (
    apply_plugin_visibility,
    enable_all_plugin_tools,
)
from redmine_mcp_server._tool_allow_list import (
    apply_tool_allow_list,
    registered_tool_names,
)

ALLOWED = {"get_redmine_issue", "list_redmine_issues", "get_current_user"}
ALL_OFF = {
    var: "false"
    for var in (
        "REDMINE_CHECKLISTS_ENABLED",
        "REDMINE_CRM_ENABLED",
        "REDMINE_DEALS_ENABLED",
        "REDMINE_PRODUCTS_ENABLED",
        "REDMINE_DMSF_ENABLED",
    )
}
ALL_ON = {var: "true" for var in ALL_OFF}


@pytest.fixture(autouse=True)
def _restore_surface():
    """Undo whatever a test hid, so later tests see the full surface."""
    yield
    _server.mcp.enable(components={"tool"})
    enable_all_plugin_tools(_server.mcp)


@pytest.fixture(autouse=True)
def _no_ambient_allow_list(monkeypatch):
    monkeypatch.delenv("REDMINE_MCP_ALLOW_TOOLS", raising=False)
    monkeypatch.delenv("REDMINE_MCP_ALLOW_TOOLS_FILE", raising=False)


async def _listed() -> set:
    async with Client(_server.mcp) as client:
        return {t.name for t in await client.list_tools()}


# --- env parsing -------------------------------------------------------


def test_unset_means_no_allow_list():
    assert get_allowed_tools() is None


def test_comma_separated_names_are_trimmed(monkeypatch):
    monkeypatch.setenv(
        "REDMINE_MCP_ALLOW_TOOLS", " get_redmine_issue , list_redmine_issues ,"
    )
    assert get_allowed_tools() == {"get_redmine_issue", "list_redmine_issues"}


def test_configured_but_empty_is_an_empty_set(monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS", "  ,  ")
    assert get_allowed_tools() == set()


def test_file_is_read_one_name_per_line_with_comments(monkeypatch, tmp_path):
    listing = tmp_path / "allow.txt"
    listing.write_text(
        "# issue reading\nget_redmine_issue\n\nlist_redmine_issues  # inline\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS_FILE", str(listing))
    assert get_allowed_tools() == {"get_redmine_issue", "list_redmine_issues"}


def test_env_var_wins_over_file(monkeypatch, tmp_path):
    listing = tmp_path / "allow.txt"
    listing.write_text("list_redmine_issues\n", encoding="utf-8")
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS_FILE", str(listing))
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS", "get_redmine_issue")
    assert get_allowed_tools() == {"get_redmine_issue"}


def test_unreadable_file_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "REDMINE_MCP_ALLOW_TOOLS_FILE", str(tmp_path / "does-not-exist.txt")
    )
    with pytest.raises(RuntimeError, match="REDMINE_MCP_ALLOW_TOOLS_FILE"):
        get_allowed_tools()


# --- enumeration -------------------------------------------------------


def test_registered_tool_names_covers_the_known_surface():
    names = registered_tool_names(_server.mcp)
    assert {"get_redmine_issue", "list_redmine_issues", "manage_deal"} <= names
    assert all("@" not in n and not n.startswith("tool:") for n in names)


def test_registered_tool_names_survives_a_missing_registry():
    class Bare:
        pass

    assert registered_tool_names(Bare()) == set()


# --- applying ----------------------------------------------------------


@pytest.mark.asyncio
async def test_only_listed_tools_are_exposed():
    with patch.dict(
        os.environ, {**ALL_OFF, "REDMINE_MCP_ALLOW_TOOLS": ",".join(ALLOWED)}
    ):
        apply_plugin_visibility(_server.mcp)
        applied = apply_tool_allow_list(_server.mcp)
    assert applied == ALLOWED
    assert await _listed() == ALLOWED


@pytest.mark.asyncio
async def test_unlisted_tool_is_not_callable():
    with patch.dict(
        os.environ, {**ALL_OFF, "REDMINE_MCP_ALLOW_TOOLS": ",".join(ALLOWED)}
    ):
        apply_plugin_visibility(_server.mcp)
        apply_tool_allow_list(_server.mcp)
    async with Client(_server.mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("list_time_entries", {})


@pytest.mark.asyncio
async def test_no_allow_list_leaves_the_surface_alone():
    with patch.dict(os.environ, ALL_OFF):
        apply_plugin_visibility(_server.mcp)
        assert apply_tool_allow_list(_server.mcp) is None
    listed = await _listed()
    assert "list_time_entries" in listed
    assert "manage_deal" not in listed  # plugin visibility still applies


@pytest.mark.asyncio
async def test_empty_allow_list_is_ignored_rather_than_hiding_everything(caplog):
    with patch.dict(os.environ, {**ALL_OFF, "REDMINE_MCP_ALLOW_TOOLS": "  "}):
        apply_plugin_visibility(_server.mcp)
        with caplog.at_level("WARNING"):
            assert apply_tool_allow_list(_server.mcp) is None
    assert "names no tools" in caplog.text
    assert "list_redmine_issues" in await _listed()


# --- intersection with plugin flags ------------------------------------


@pytest.mark.asyncio
async def test_allow_list_cannot_re_enable_a_plugin_gated_tool():
    """A listed tool whose plugin flag is off stays hidden."""
    with patch.dict(
        os.environ,
        {**ALL_OFF, "REDMINE_MCP_ALLOW_TOOLS": "get_redmine_issue,manage_deal"},
    ):
        apply_plugin_visibility(_server.mcp)
        applied = apply_tool_allow_list(_server.mcp)
    assert "manage_deal" in applied  # it is registered, so it is "applied"
    listed = await _listed()
    assert "get_redmine_issue" in listed
    assert "manage_deal" not in listed  # but the plugin flag still wins


@pytest.mark.asyncio
async def test_plugin_flag_on_plus_allow_list_exposes_the_plugin_tool():
    with patch.dict(
        os.environ,
        {**ALL_ON, "REDMINE_MCP_ALLOW_TOOLS": "get_redmine_issue,manage_deal"},
    ):
        apply_plugin_visibility(_server.mcp)
        apply_tool_allow_list(_server.mcp)
    assert await _listed() == {"get_redmine_issue", "manage_deal"}


@pytest.mark.asyncio
async def test_reapplying_after_a_flag_flip_keeps_the_list_narrow():
    """Plugin visibility enables by tag, so the list must be re-applied."""
    env = {"REDMINE_MCP_ALLOW_TOOLS": "get_redmine_issue"}
    with patch.dict(os.environ, {**ALL_OFF, **env}):
        apply_plugin_visibility(_server.mcp)
        apply_tool_allow_list(_server.mcp)
    assert await _listed() == {"get_redmine_issue"}
    with patch.dict(os.environ, {**ALL_ON, **env}):
        apply_plugin_visibility(_server.mcp)
        apply_tool_allow_list(_server.mcp)
    assert await _listed() == {"get_redmine_issue"}


# --- unknown names -----------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_name_warns_and_is_ignored(caplog):
    with patch.dict(
        os.environ,
        {**ALL_OFF, "REDMINE_MCP_ALLOW_TOOLS": "get_redmine_issue,get_redmine_issues"},
    ):
        apply_plugin_visibility(_server.mcp)
        with caplog.at_level("WARNING"):
            applied = apply_tool_allow_list(_server.mcp)
    assert applied == {"get_redmine_issue"}
    assert "get_redmine_issues" in caplog.text
    assert "unknown tool" in caplog.text
    assert await _listed() == {"get_redmine_issue"}


@pytest.mark.asyncio
async def test_all_names_unknown_hides_every_tool(caplog):
    """A wholly misspelled list is honoured, not silently ignored."""
    with patch.dict(os.environ, {**ALL_OFF, "REDMINE_MCP_ALLOW_TOOLS": "nope,nope2"}):
        apply_plugin_visibility(_server.mcp)
        with caplog.at_level("WARNING"):
            applied = apply_tool_allow_list(_server.mcp)
    assert applied == set()
    assert "unknown tool" in caplog.text
    assert await _listed() == set()
