"""Schema regression tests for limit/offset typing (#111).

Each list/search tool surfaces ``limit`` and ``offset`` in its JSON
input schema with explicit ``minimum`` and ``maximum`` bounds so that
strict MCP clients can validate them up front, and the
``CleanValidationErrorMiddleware`` (#108) can produce the
standardized ``INVALID_ARGUMENTS`` envelope for out-of-range values
before the tool body runs.

This is a pinning test: changing a tool's bound requires updating
the expectations here. That is intentional -- the previous behavior
silently clamped over-range values, which made it impossible for
clients to know when their pagination was being changed beneath
them.
"""

import pytest
from fastmcp import Client

from redmine_mcp_server import server as _server  # noqa: F401
from redmine_mcp_server import tools  # noqa: F401

# (tool_name, param, expected_min, expected_max-or-None, default)
EXPECTED_BOUNDS = [
    ("get_gantt_chart", "limit", 1, 500, 250),
    ("get_redmine_issue", "journal_offset", 0, None, 0),
    ("list_redmine_issues", "limit", 1, 1000, 25),
    ("list_redmine_issues", "offset", 0, None, 0),
    ("list_redmine_users", "limit", 1, 100, 25),
    ("list_redmine_users", "offset", 0, None, 0),
    ("list_time_entries", "limit", 1, 100, 25),
    ("list_time_entries", "offset", 0, None, 0),
    ("manage_contact", "limit", 1, 100, 100),
    ("manage_product", "limit", 1, 100, 100),
    ("search_entire_redmine", "limit", 1, 100, 100),
    ("search_entire_redmine", "offset", 0, None, 0),
    ("search_redmine_issues", "limit", 1, 1000, 25),
    ("search_redmine_issues", "offset", 0, None, 0),
]


@pytest.fixture(scope="module")
async def all_tools():
    async with Client(_server.mcp) as client:
        listed = await client.list_tools()
    return {t.name: t for t in listed}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name,param,expected_min,expected_max,default",
    EXPECTED_BOUNDS,
)
async def test_limit_offset_carry_explicit_bounds(
    tool_name, param, expected_min, expected_max, default
):
    async with Client(_server.mcp) as client:
        listed = {t.name: t for t in await client.list_tools()}

    assert tool_name in listed, f"Tool {tool_name} not registered"
    schema = listed[tool_name].inputSchema or {}
    prop = schema.get("properties", {}).get(param)
    assert prop is not None, (
        f"{tool_name}.{param} is missing from the input schema. "
        "Did the signature drop the parameter?"
    )

    # Pydantic v2 renders bounds as top-level keys on integer schemas.
    assert prop.get("minimum") == expected_min, (
        f"{tool_name}.{param}: expected minimum={expected_min}, "
        f"got {prop.get('minimum')}"
    )
    if expected_max is not None:
        assert prop.get("maximum") == expected_max, (
            f"{tool_name}.{param}: expected maximum={expected_max}, "
            f"got {prop.get('maximum')}"
        )
    assert prop.get("default") == default, (
        f"{tool_name}.{param}: expected default={default}, "
        f"got {prop.get('default')}"
    )


@pytest.mark.asyncio
async def test_journal_limit_is_bounded_optional_int():
    """journal_limit is genuinely optional: None means "no pagination,
    return all journals". Keep the Optional, but the integer branch
    must carry bounds."""
    async with Client(_server.mcp) as client:
        listed = {t.name: t for t in await client.list_tools()}

    schema = listed["get_redmine_issue"].inputSchema
    prop = schema["properties"]["journal_limit"]

    # Pydantic emits Optional[int] as anyOf with the int branch first.
    any_of = prop.get("anyOf")
    assert any_of, f"journal_limit must remain Optional (anyOf with null); got {prop}"
    int_branch = next((b for b in any_of if b.get("type") == "integer"), None)
    assert int_branch is not None
    assert int_branch.get("minimum") == 1
    assert int_branch.get("maximum") == 1000

    null_branch = next((b for b in any_of if b.get("type") == "null"), None)
    assert null_branch is not None
    assert prop.get("default") is None
