"""Plugin-gated tools are listed only when their plugin flag is on."""

import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from redmine_mcp_server import server as _server
from redmine_mcp_server import tools  # noqa: F401  -- triggers @mcp.tool
from redmine_mcp_server._plugin_visibility import (
    PLUGIN_FLAGS,
    apply_plugin_visibility,
    enable_all_plugin_tools,
    plugin_tag,
)

PLUGIN_TOOLS = {
    "checklists": {"get_checklist", "create_checklist_item", "update_checklist_item"},
    "crm": {"manage_contact", "list_contact_tags"},
    "deals": {"manage_deal", "list_deal_statuses", "manage_deal_category"},
    "products": {"manage_product"},
    "dmsf": {"manage_document"},
    "crm-shared": {"manage_crm_note", "list_crm_queries"},
    "deal-products": {"add_deal_product"},
}
ALL_PLUGIN_TOOLS = set().union(*PLUGIN_TOOLS.values())
FLAG_ENV = {
    "checklists": "REDMINE_CHECKLISTS_ENABLED",
    "crm": "REDMINE_CRM_ENABLED",
    "deals": "REDMINE_DEALS_ENABLED",
    "products": "REDMINE_PRODUCTS_ENABLED",
    "dmsf": "REDMINE_DMSF_ENABLED",
}
ALL_OFF = {var: "false" for var in FLAG_ENV.values()}


@pytest.fixture(autouse=True)
def _restore_visibility():
    yield
    enable_all_plugin_tools(_server.mcp)


async def _listed() -> set:
    async with Client(_server.mcp) as client:
        return {t.name for t in await client.list_tools()}


def test_plugin_tag_shape():
    assert plugin_tag("crm") == "plugin:crm"


def test_flag_table_covers_every_family():
    assert set(PLUGIN_FLAGS) >= set(PLUGIN_TOOLS)


@pytest.mark.asyncio
async def test_all_flags_off_hides_every_plugin_tool():
    with patch.dict(os.environ, ALL_OFF):
        state = apply_plugin_visibility(_server.mcp)
    listed = await _listed()
    assert not (ALL_PLUGIN_TOOLS & listed)
    assert "list_redmine_issues" in listed  # core untouched
    assert all(v is False for k, v in state.items() if k in PLUGIN_TOOLS)


@pytest.mark.asyncio
async def test_hidden_tool_is_not_callable():
    with patch.dict(os.environ, ALL_OFF):
        apply_plugin_visibility(_server.mcp)
    async with Client(_server.mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("manage_deal", {"action": "list"})


@pytest.mark.asyncio
@pytest.mark.parametrize("family", sorted(FLAG_ENV))
async def test_single_flag_exposes_exactly_its_tools(family):
    env = dict(ALL_OFF)
    env[FLAG_ENV[family]] = "true"
    with patch.dict(os.environ, env):
        apply_plugin_visibility(_server.mcp)
    listed = await _listed()
    expected = set(PLUGIN_TOOLS[family])
    if family in ("crm", "deals"):
        expected |= PLUGIN_TOOLS["crm-shared"]
    assert expected <= listed
    assert not ((ALL_PLUGIN_TOOLS - expected) & listed)


@pytest.mark.asyncio
async def test_reapplying_after_flag_flip_changes_surface():
    with patch.dict(os.environ, ALL_OFF):
        apply_plugin_visibility(_server.mcp)
    assert "manage_deal" not in await _listed()
    with patch.dict(os.environ, {**ALL_OFF, "REDMINE_DEALS_ENABLED": "true"}):
        apply_plugin_visibility(_server.mcp)
    assert "manage_deal" in await _listed()
    with patch.dict(os.environ, ALL_OFF):
        apply_plugin_visibility(_server.mcp)
    assert "manage_deal" not in await _listed()


@pytest.mark.asyncio
async def test_enable_all_restores_full_surface():
    with patch.dict(os.environ, ALL_OFF):
        apply_plugin_visibility(_server.mcp)
    enable_all_plugin_tools(_server.mcp)
    assert ALL_PLUGIN_TOOLS <= await _listed()


@pytest.mark.asyncio
async def test_deal_products_needs_both_flags():
    with patch.dict(
        os.environ,
        {
            **ALL_OFF,
            "REDMINE_DEALS_ENABLED": "true",
            "REDMINE_PRODUCTS_ENABLED": "true",
        },
    ):
        apply_plugin_visibility(_server.mcp)
    assert "add_deal_product" in await _listed()
    with patch.dict(os.environ, {**ALL_OFF, "REDMINE_PRODUCTS_ENABLED": "true"}):
        apply_plugin_visibility(_server.mcp)
    assert "add_deal_product" not in await _listed()
