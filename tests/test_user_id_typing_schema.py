"""Schema + boundary regression tests for user-ID-style filter params (#116).

Filter parameters that accept Redmine's ``"me"`` sentinel
(``list_redmine_issues.assigned_to_id``, ``list_time_entries.user_id``)
are typed as ``Optional[Union[int, Literal["me"]]]`` so the JSON
schema rejects arbitrary strings at the FastMCP boundary, surfacing
the standardized ``INVALID_ARGUMENTS`` envelope from #108 instead of
silently passing the garbage value through to Redmine (which would
return ``[]`` and lead a model to reason over the wrong count).
"""

import pytest
from fastmcp import Client

from redmine_mcp_server import server as _server  # noqa: F401
from redmine_mcp_server import tools  # noqa: F401

USER_ID_PARAMS = [
    ("list_redmine_issues", "assigned_to_id"),
    ("list_time_entries", "user_id"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,param", USER_ID_PARAMS)
async def test_user_id_param_has_me_literal_in_schema(tool_name, param):
    """The string branch of the union must be the literal ``"me"``,
    not a free-form ``str``. Drift here re-introduces the silent
    pass-through bug."""
    async with Client(_server.mcp) as client:
        listed = {t.name: t for t in await client.list_tools()}

    schema = listed[tool_name].inputSchema or {}
    prop = schema.get("properties", {}).get(param)
    assert prop is not None, f"{tool_name}.{param} missing from schema"

    any_of = prop.get("anyOf")
    assert any_of, f"{tool_name}.{param} should be Optional[Union[...]]"

    # Must have an integer branch.
    int_branch = next((b for b in any_of if b.get("type") == "integer"), None)
    assert int_branch is not None, f"{tool_name}.{param} must accept integer IDs"

    # Must have a 'me' literal branch (not a free-form string).
    me_branch = next(
        (b for b in any_of if b.get("const") == "me"),
        None,
    )
    assert me_branch is not None, (
        f"{tool_name}.{param} must accept Literal['me'] only as its "
        f"string sentinel. Got: {any_of}"
    )
    # Bare-string branch would mean the bug regressed.
    bare_str = [
        b
        for b in any_of
        if b.get("type") == "string" and "const" not in b and "enum" not in b
    ]
    assert not bare_str, (
        f"{tool_name}.{param} accepts arbitrary strings -- regression. "
        f"Got: {any_of}"
    )

    # Must remain Optional.
    null_branch = next((b for b in any_of if b.get("type") == "null"), None)
    assert null_branch is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,param", USER_ID_PARAMS)
async def test_invalid_string_rejected_at_boundary(tool_name, param):
    """Verify the runtime boundary actually rejects garbage strings
    with the INVALID_ARGUMENTS envelope from #108."""
    async with Client(_server.mcp) as client:
        result = await client.call_tool(tool_name, {param: "notmeortheid"})

    payload = result.structured_content
    if payload and "result" in payload:
        payload = payload["result"]
    assert payload is not None
    assert payload.get("code") == "INVALID_ARGUMENTS", (
        f"{tool_name}.{param}=garbage was accepted -- regression. "
        f"Payload: {payload}"
    )
    # The error must mention both the int and 'me' branches so the
    # caller knows what shape is acceptable.
    error = payload.get("error", "").lower()
    assert "integer" in error
    assert "'me'" in error or "me" in error
