"""Schema regression tests for the manage_* tool family (#112).

Each manage_* tool advertises its action set via a ``Literal[...]``
annotation, which FastMCP must surface as a JSON-schema ``enum`` on
the ``action`` property. Without this, strict MCP clients lose
validation and permissive ones lose autocomplete.
"""

import pytest
from fastmcp import Client

from redmine_mcp_server import server as _server  # noqa: F401  -- register tools
from redmine_mcp_server import tools  # noqa: F401  -- triggers @mcp.tool

# Source-of-truth for what each manage_X tool MUST expose. Adding a new
# action requires updating both the tool spec AND this map so the
# schema cannot silently drift back to a plain string.
EXPECTED_ACTIONS = {
    "manage_contact": {
        "list",
        "get",
        "create",
        "update",
        "delete",
        "assign_to_project",
        "remove_from_project",
    },
    "manage_issue_relation": {"list", "create", "delete"},
    "manage_issue_watcher": {"add", "remove"},
    "manage_issue_note": {"edit", "set_private"},
    "manage_issue_category": {"list", "create", "update", "delete"},
    "manage_product": {"list", "get", "create", "update"},
    "manage_redmine_version": {"create", "update", "delete"},
    "manage_project_member": {"add", "update", "remove"},
    "manage_time_entry": {"create", "update"},
    "manage_redmine_wiki_page": {
        "list",
        "get",
        "create",
        "update",
        "delete",
        "rename",
    },
    "manage_document": {"list", "get", "create", "update"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,expected", sorted(EXPECTED_ACTIONS.items()))
async def test_manage_tool_action_is_json_schema_enum(tool_name, expected):
    async with Client(_server.mcp) as client:
        listed = {t.name: t for t in await client.list_tools()}
    assert tool_name in listed, f"Tool {tool_name} not registered"

    schema = listed[tool_name].inputSchema or {}
    action_prop = schema.get("properties", {}).get("action", {})

    # Pydantic renders Literal["x", "y"] as `enum: [...]` but a
    # single-value Literal["only"] as `const: "only"`. Accept either
    # shape and reduce to a set of allowed values for the comparison.
    if "enum" in action_prop:
        allowed = set(action_prop["enum"])
    elif "const" in action_prop:
        allowed = {action_prop["const"]}
    else:
        raise AssertionError(
            f"{tool_name}.action must surface as a JSON-schema enum or "
            "const (declare it as Literal[...] on the function "
            f"signature). Got: {action_prop}"
        )

    assert allowed == expected, (
        f"{tool_name}.action allowed values drifted from the dispatch "
        f"spec. Expected {expected}, got {allowed}."
    )
