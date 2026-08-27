"""``list_redmine_issues`` and Redmine's short-filter forms.

Redmine carries a filter's operator *inside* the value -- ``Query#add_short_filter``
(``app/models/query.rb:745-755`` on 6.1.1) detects an operator prefix for the
filter's type and splits the remainder on ``|``, defaulting to ``=`` over the
split list. So ``"56|57"`` is two trackers, ``"!*"`` is "none", and
``"!5"`` is "not 5".

None of that can be written on the named parameters, and it should not be:
``assigned_to_id`` is deliberately ``Optional[Union[int, Literal["me"]]]`` so
the boundary refuses garbage rather than passing it to Redmine and returning an
empty list that a model reads as "nothing matched" (#116, pinned in
``test_user_id_typing_schema.py``). The route is ``filters``, which is merged
over the named parameters and so can express what they cannot.

That route worked and was undiscoverable: the docstring's own ``filters`` entry
said it was for "any filter not listed above", which tells a caller it does
*not* apply to these keys, while the tool's leading prose offers "find
unassigned issues" as a use case. These tests pin the route and pin the text
that makes it findable, since a shipped docstring is the only place most callers
can learn it.

See https://github.com/jztan/redmine-mcp-server/issues/250 (#250).
"""

import os
import sys
from typing import Any, Dict, List

import pytest
from fastmcp import Client
from redminelib import Redmine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server import _client  # noqa: E402
from redmine_mcp_server import server as _server  # noqa: E402,F401
from redmine_mcp_server import tools  # noqa: E402,F401
from redmine_mcp_server.tools.issues import list_redmine_issues  # noqa: E402

REDMINE_URL = "https://redmine.example.invalid"


@pytest.fixture
def sent(monkeypatch):
    """The query parameters of each request the call issued."""
    calls: List[Dict[str, Any]] = []

    def record(method: str, url: str, **kwargs: Any) -> Any:
        calls.append(dict(kwargs.get("params") or {}))
        return {"issues": [], "total_count": 0}

    client = Redmine(REDMINE_URL, key="k")
    monkeypatch.setattr(client.engine, "request", record)
    monkeypatch.setattr(_client, "redmine", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value",
    [
        ("assigned_to_id", "!*"),
        ("assigned_to_id", "*"),
        ("assigned_to_id", "1|2"),
        ("tracker_id", "56|57"),
        ("priority_id", "!4"),
        ("fixed_version_id", "*"),
        ("status_id", "!5"),
    ],
)
async def test_short_filter_forms_reach_redmine_through_filters(sent, key, value):
    result = await list_redmine_issues(filters={key: value})

    assert not isinstance(result, dict) or "error" not in result, result
    assert sent[0].get(key) == value, f"{key} was not forwarded verbatim: {sent[0]}"


@pytest.mark.asyncio
async def test_filters_overrides_the_named_parameter(sent):
    """The merge order is what makes the escape hatch work.

    ``filters`` is merged after the named parameters, so a caller who needs a
    form the parameter cannot express writes it here and it wins. Pinned
    because reversing the merge would close the only route to a negated or
    multi-value filter while every test that uses one key or the other still
    passed.
    """
    result = await list_redmine_issues(tracker_id=56, filters={"tracker_id": "56|57"})

    assert not isinstance(result, dict) or "error" not in result, result
    assert sent[0]["tracker_id"] == "56|57"


@pytest.mark.asyncio
async def test_named_parameters_still_refuse_garbage(sent):
    """#116 stays intact: widening these types is not the fix for the above."""
    async with Client(_server.mcp) as client:
        result = await client.call_tool("list_redmine_issues", {"assigned_to_id": "!*"})

    payload = result.structured_content
    if payload and "result" in payload:
        payload = payload["result"]
    assert payload.get("code") == "INVALID_ARGUMENTS", payload
    assert sent == []


# --------------------------------------------------------------------------
# What the shipped schema has to say. FastMCP ships the leading prose and each
# `Args:` entry in every `tools/list`, and nothing else from the docstring, so
# these facts are only actionable if they are in one of those two places.
# --------------------------------------------------------------------------


async def _described(param: str) -> str:
    """The shipped description, with the docstring's line wrapping collapsed.

    FastMCP ships the ``Args:`` entry as written, newlines included, so an
    assertion on a phrase has to be indifferent to where the source happened
    to wrap it.
    """
    async with Client(_server.mcp) as client:
        listed = {t.name: t for t in await client.list_tools()}
    schema = listed["list_redmine_issues"].inputSchema or {}
    prop = schema.get("properties", {}).get(param) or {}
    return " ".join(prop.get("description", "").split())


@pytest.mark.asyncio
async def test_filters_description_states_the_operator_rule():
    described = await _described("filters")
    assert "|" in described, "the alternatives-join form is not described"
    assert "!*" in described, "the unassigned form the prose promises is not shown"


@pytest.mark.asyncio
async def test_filters_description_states_the_silent_discard():
    """A discarded filter answers 200 with the collection unnarrowed.

    The failure mode is a plausible superset rather than an error, so a caller
    who is not told cannot detect it. ``list_redmine_projects`` already carries
    this sentence; the two tools should not disagree.
    """
    described = (await _described("filters")).lower()
    assert "used as a filter" in described, "the filterable precondition is missing"
    assert "200" in described or "unnarrowed" in described


@pytest.mark.asyncio
async def test_limit_description_states_the_paging_cost():
    """A limit above 100 is paged in chunks of 100, one request per chunk asked
    for, whether or not the rows exist. ``list_redmine_projects`` says so."""
    described = (await _described("limit")).lower()
    assert "100" in described
    assert "request" in described
