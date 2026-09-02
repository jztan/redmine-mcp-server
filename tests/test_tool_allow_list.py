"""Only allow-listed tools are exposed, and the list cannot widen."""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client, FastMCP

from redmine_mcp_server import server as _server
from redmine_mcp_server import tools  # noqa: F401  -- triggers @mcp.tool
from redmine_mcp_server._env import get_allowed_tools
from redmine_mcp_server._plugin_visibility import (
    apply_plugin_visibility,
    enable_all_plugin_tools,
)
from redmine_mcp_server._tool_allow_list import (
    CONDITIONALLY_REGISTERED,
    ToolAllowListMiddleware,
    build_tool_allow_list,
    registered_tool_names,
    warn_about_unknown_names,
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
    """Detach whatever a test attached and unhide what it hid."""
    before = list(_server.mcp.middleware)
    yield
    _server.mcp.middleware[:] = before
    enable_all_plugin_tools(_server.mcp)


@pytest.fixture(autouse=True)
def _no_ambient_allow_list(monkeypatch):
    monkeypatch.delenv("REDMINE_MCP_ALLOW_TOOLS", raising=False)
    monkeypatch.delenv("REDMINE_MCP_ALLOW_TOOLS_FILE", raising=False)


def _attach(allowed) -> None:
    _server.mcp.add_middleware(ToolAllowListMiddleware(frozenset(allowed)))


async def _listed(mcp=None) -> set:
    async with Client(mcp or _server.mcp) as client:
        return {t.name for t in await client.list_tools()}


def _warnings(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelno >= 30)


def _isolated(allowed) -> FastMCP:
    """A server of stand-in tools, so calls stay off the network."""
    mcp = FastMCP("allow-list-test")
    mcp.add_middleware(ToolAllowListMiddleware(frozenset(allowed)))

    @mcp.tool()
    async def get_redmine_issue(issue_id: int) -> dict:
        return {"issue": issue_id}

    @mcp.tool()
    async def list_time_entries() -> dict:
        return {"entries": []}

    return mcp


# --- env parsing -------------------------------------------------------


def test_unset_means_no_allow_list():
    assert get_allowed_tools() is None


def test_comma_separated_names_are_trimmed(monkeypatch):
    monkeypatch.setenv(
        "REDMINE_MCP_ALLOW_TOOLS", " get_redmine_issue , list_redmine_issues ,"
    )
    assert get_allowed_tools() == {"get_redmine_issue", "list_redmine_issues"}


def test_a_variable_of_only_separators_is_configured_but_empty(monkeypatch):
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


def test_an_empty_variable_does_not_shadow_the_file(monkeypatch, tmp_path):
    """docker-compose renders an unset ${VAR} as the empty string."""
    listing = tmp_path / "allow.txt"
    listing.write_text("list_redmine_issues\n", encoding="utf-8")
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS_FILE", str(listing))
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS", "")
    assert get_allowed_tools() == {"list_redmine_issues"}


def test_an_empty_variable_with_no_file_means_unset(monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS", "")
    assert get_allowed_tools() is None


def test_unreadable_file_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "REDMINE_MCP_ALLOW_TOOLS_FILE", str(tmp_path / "does-not-exist.txt")
    )
    with pytest.raises(RuntimeError, match="REDMINE_MCP_ALLOW_TOOLS_FILE"):
        get_allowed_tools()


# --- construction ------------------------------------------------------


def test_no_allow_list_builds_no_middleware():
    assert build_tool_allow_list(_server.mcp) is None


def test_a_configured_but_empty_list_refuses_to_start(monkeypatch):
    """Starting wide open is the one outcome the operator did not ask for."""
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS", "  ,  ")
    with pytest.raises(RuntimeError, match="names no tools"):
        build_tool_allow_list(_server.mcp)


def test_build_returns_middleware_holding_the_names(monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_ALLOW_TOOLS", ",".join(sorted(ALLOWED)))
    middleware = build_tool_allow_list(_server.mcp)
    assert isinstance(middleware, ToolAllowListMiddleware)
    assert middleware.allowed == frozenset(ALLOWED)


# --- enforcement -------------------------------------------------------


@pytest.mark.asyncio
async def test_only_listed_tools_are_exposed():
    _attach(ALLOWED)
    assert await _listed() == ALLOWED


@pytest.mark.asyncio
async def test_without_the_middleware_the_surface_is_untouched():
    assert "list_time_entries" in await _listed()


@pytest.mark.asyncio
async def test_a_listed_tool_is_callable():
    async with Client(_isolated({"get_redmine_issue"})) as client:
        result = await client.call_tool("get_redmine_issue", {"issue_id": 7})
    assert result.structured_content == {"issue": 7}


@pytest.mark.asyncio
async def test_an_unlisted_tool_is_refused_even_though_it_exists():
    async with Client(_isolated({"get_redmine_issue"})) as client:
        result = await client.call_tool("list_time_entries", {})
    payload = json.loads(result.content[0].text)
    assert payload["code"] == "TOOL_NOT_ALLOWED"
    assert "list_time_entries" in payload["error"]
    assert "REDMINE_MCP_ALLOW_TOOLS" in payload["hint"]


@pytest.mark.asyncio
async def test_a_hidden_tool_cannot_be_reached_by_name():
    """tools/list is cosmetic; call_tool is the boundary."""
    mcp = _isolated({"get_redmine_issue"})
    assert await _listed(mcp) == {"get_redmine_issue"}
    async with Client(mcp) as client:
        result = await client.call_tool("list_time_entries", {})
    assert json.loads(result.content[0].text)["code"] == "TOOL_NOT_ALLOWED"


# --- the property the review asked for ---------------------------------


@pytest.mark.asyncio
async def test_enforcement_does_not_read_the_component_registry():
    """The registry is private API; if it moves, the list must still hold.

    Computing the complement and disabling it meant an unreadable registry
    exposed every tool. Filtering the list the framework hands over has no
    such failure mode, and this pins that down.
    """
    _attach(ALLOWED)
    with patch(
        "redmine_mcp_server._tool_allow_list.registered_tool_names", return_value=set()
    ):
        assert await _listed() == ALLOWED


@pytest.mark.asyncio
async def test_an_all_unknown_list_exposes_nothing_rather_than_everything():
    _attach({"nope", "nope2"})
    assert await _listed() == set()


def test_registered_tool_names_covers_the_known_surface():
    names = registered_tool_names(_server.mcp)
    assert {"get_redmine_issue", "list_redmine_issues", "manage_deal"} <= names
    assert all("@" not in n and not n.startswith("tool:") for n in names)


def test_registered_tool_names_survives_a_missing_registry():
    class Bare:
        pass

    assert registered_tool_names(Bare()) == set()


# --- intersection with plugin flags ------------------------------------


@pytest.mark.asyncio
async def test_allow_list_cannot_re_enable_a_plugin_gated_tool():
    with patch.dict(os.environ, ALL_OFF):
        apply_plugin_visibility(_server.mcp)
    _attach({"get_redmine_issue", "manage_deal"})
    listed = await _listed()
    assert "get_redmine_issue" in listed
    assert "manage_deal" not in listed  # the plugin flag still wins


@pytest.mark.asyncio
async def test_plugin_flag_on_plus_allow_list_exposes_the_plugin_tool():
    with patch.dict(os.environ, ALL_ON):
        apply_plugin_visibility(_server.mcp)
    _attach({"get_redmine_issue", "manage_deal"})
    assert await _listed() == {"get_redmine_issue", "manage_deal"}


@pytest.mark.asyncio
async def test_a_later_flag_flip_does_not_widen_the_list():
    """Middleware needs no re-application: it is not a visibility transform."""
    _attach({"get_redmine_issue"})
    with patch.dict(os.environ, ALL_OFF):
        apply_plugin_visibility(_server.mcp)
    assert await _listed() == {"get_redmine_issue"}
    with patch.dict(os.environ, ALL_ON):
        apply_plugin_visibility(_server.mcp)
    assert await _listed() == {"get_redmine_issue"}


# --- unknown names -----------------------------------------------------


def test_unknown_name_warns(caplog):
    with caplog.at_level("WARNING"):
        warn_about_unknown_names(
            _server.mcp, {"get_redmine_issue", "get_redmine_issues"}
        )
    text = _warnings(caplog)
    assert "get_redmine_issues" in text
    assert "does not" in text


def test_a_correct_name_does_not_warn(caplog):
    with caplog.at_level("WARNING"):
        warn_about_unknown_names(_server.mcp, {"get_redmine_issue"})
    assert _warnings(caplog) == ""


def test_a_flag_gated_tool_is_not_reported_as_a_typo(caplog):
    """cleanup_attachment_files registers only under its own flag."""
    assert "cleanup_attachment_files" in CONDITIONALLY_REGISTERED
    with caplog.at_level("WARNING"):
        warn_about_unknown_names(_server.mcp, {"cleanup_attachment_files"})
    assert _warnings(caplog) == ""


def test_no_warning_when_the_registry_cannot_be_read(caplog):
    class Bare:
        pass

    with caplog.at_level("WARNING"):
        warn_about_unknown_names(Bare(), {"whatever"})
    assert _warnings(caplog) == ""
