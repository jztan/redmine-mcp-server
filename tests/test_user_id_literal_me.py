"""Schema + runtime tests for user-ID-style params with the ``"me"``
sentinel (#116).

``list_redmine_issues.assigned_to_id`` and ``list_time_entries.user_id``
accept either a numeric user ID or the Redmine sentinel string ``"me"``.
They are typed as ``Optional[Union[int, Literal["me"]]]`` so FastMCP
surfaces the literal as a JSON-schema enum, and
``CleanValidationErrorMiddleware`` (#108) rejects arbitrary strings with
the standardized ``INVALID_ARGUMENTS`` envelope -- instead of forwarding
garbage to Redmine, which returns an empty list and leaves callers
unable to tell a bad filter from no matches.
"""

import pytest
from fastmcp import Client

from redmine_mcp_server import server as _server  # noqa: F401  -- register tools
from redmine_mcp_server import tools  # noqa: F401  -- triggers @mcp.tool

# (tool_name, param) -- params that must expose ``"me"`` as the only
# allowed string value in their JSON schema.
USER_ID_ME_PARAMS = [
    ("list_redmine_issues", "assigned_to_id"),
    ("list_time_entries", "user_id"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,param", USER_ID_ME_PARAMS)
async def test_user_id_param_exposes_me_literal_in_schema(tool_name, param):
    """The JSON schema for these params must include ``"me"`` as an enum
    on the string branch -- not a free-form ``"type": "string"``."""
    async with Client(_server.mcp) as client:
        listed = {t.name: t for t in await client.list_tools()}

    assert tool_name in listed, f"Tool {tool_name} not registered"
    schema = listed[tool_name].inputSchema or {}
    prop = schema.get("properties", {}).get(param)
    assert prop is not None, f"{tool_name}.{param} missing from input schema"

    any_of = prop.get("anyOf")
    assert any_of, (
        f"{tool_name}.{param} should be Optional[Union[int, Literal['me']]]; "
        f"got {prop}"
    )

    int_branch = next((b for b in any_of if b.get("type") == "integer"), None)
    assert (
        int_branch is not None
    ), f"{tool_name}.{param} must keep an integer branch; got {any_of}"

    # Pydantic v2 emits ``Literal["me"]`` as ``{"const": "me"}`` or
    # ``{"enum": ["me"], "type": "string"}`` depending on version. Both
    # forms must reject arbitrary strings -- a plain ``"type": "string"``
    # branch would silently accept anything.
    string_branch = next(
        (b for b in any_of if b.get("type") == "string" or "const" in b or "enum" in b),
        None,
    )
    assert (
        string_branch is not None
    ), f"{tool_name}.{param} must expose the 'me' sentinel; got {any_of}"
    allowed = set(
        string_branch.get("enum")
        or ([string_branch["const"]] if "const" in string_branch else [])
    )
    assert allowed == {"me"}, (
        f"{tool_name}.{param} must restrict the string branch to 'me'; "
        f"got {allowed} (full branch: {string_branch})"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,param", USER_ID_ME_PARAMS)
async def test_user_id_param_rejects_arbitrary_string(tool_name, param):
    """Arbitrary strings must trip the validation middleware rather than
    being silently forwarded to Redmine (which would return ``[]`` and
    look like 'no matches')."""
    async with Client(_server.mcp) as client:
        result = await client.call_tool(tool_name, {param: "garbage"})

    payload = result.structured_content
    assert payload is not None, f"{tool_name}.{param}: no structured content"
    # ``Union[List, Dict]`` returns get wrapped under ``"result"`` by
    # FastMCP; the envelope is mirrored into both shapes by the
    # middleware. Unwrap when present.
    envelope = payload.get("result", payload) if isinstance(payload, dict) else payload
    assert envelope.get("code") == "INVALID_ARGUMENTS", (
        f"{tool_name}.{param}='garbage' should hit the validation middleware; "
        f"got {envelope}"
    )
    assert f"'{param}'" in envelope["error"]
    assert "garbage" in envelope["hint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,param", USER_ID_ME_PARAMS)
async def test_user_id_param_accepts_me_sentinel(tool_name, param, monkeypatch):
    """The ``"me"`` sentinel must clear validation and reach the tool
    body. We stub the Redmine client so the call resolves locally."""

    from unittest.mock import MagicMock

    captured: dict = {}
    fake_client = MagicMock()
    if tool_name == "list_redmine_issues":
        fake_filter = MagicMock(return_value=[])
        fake_client.issue.filter = fake_filter
        monkeypatch.setattr(
            "redmine_mcp_server.tools.issues._get_redmine_client",
            lambda: fake_client,
        )

        async def call():
            async with Client(_server.mcp) as client:
                await client.call_tool(tool_name, {param: "me"})

        await call()
        captured["kwargs"] = fake_filter.call_args.kwargs
    else:  # list_time_entries
        fake_filter = MagicMock(return_value=[])
        fake_client.time_entry.filter = fake_filter
        monkeypatch.setattr(
            "redmine_mcp_server.tools.time_tracking._get_redmine_client",
            lambda: fake_client,
        )

        async def call():
            async with Client(_server.mcp) as client:
                await client.call_tool(tool_name, {param: "me"})

        await call()
        captured["kwargs"] = fake_filter.call_args.kwargs

    assert captured["kwargs"].get(param) == "me", (
        f"{tool_name}.{param}='me' should reach the Redmine client unchanged; "
        f"got {captured['kwargs']}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,param", USER_ID_ME_PARAMS)
async def test_user_id_param_accepts_integer(tool_name, param, monkeypatch):
    """Numeric IDs must continue to work -- the tightening should not
    break the common case."""

    from unittest.mock import MagicMock

    fake_client = MagicMock()
    if tool_name == "list_redmine_issues":
        fake_filter = MagicMock(return_value=[])
        fake_client.issue.filter = fake_filter
        monkeypatch.setattr(
            "redmine_mcp_server.tools.issues._get_redmine_client",
            lambda: fake_client,
        )
    else:
        fake_filter = MagicMock(return_value=[])
        fake_client.time_entry.filter = fake_filter
        monkeypatch.setattr(
            "redmine_mcp_server.tools.time_tracking._get_redmine_client",
            lambda: fake_client,
        )

    async with Client(_server.mcp) as client:
        await client.call_tool(tool_name, {param: 42})

    assert fake_filter.call_args.kwargs.get(param) == 42
