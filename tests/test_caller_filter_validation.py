"""Caller-supplied ``filters`` dicts are validated before they are forwarded.

``list_redmine_projects`` gained this in #239. ``list_redmine_issues`` and
``manage_contact`` did not, and they are the remaining tools that take a filter
dict from the caller.

The issue list is the worse of the two, because it does not build a query
string and hand it over: ``issue.filter(**filters)`` runs the whole dict
through python-redmine's ``Issue.bulk_decode``, whose ``decode`` special-cases
``uploads`` by reading each named ``path`` off the local filesystem and
uploading it before the request being asked for is issued. So a filter key on a
read tool performs a local file read and a write to Redmine, and neither
``REDMINE_MCP_READ_ONLY`` nor the ``uploads`` scope check in
``oauth_scopes.py`` sees it: the read-only gate fires only for
``ActionMode.WRITE`` actions, and the scope check reads the write tools' own
named ``uploads`` parameter, not a key nested inside ``filters``.

The tests drive the real tools with only ``engine.request`` stubbed, so the
merge order, the validation and the library's own decoding are all real. Each
one is written to fail against the parent commit.

Reported privately as GHSA-xp4v-6gr8-jvwh.
"""

import os
import sys
from typing import Any, Dict, List

import pytest
from redminelib import Redmine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server import _client  # noqa: E402
from redmine_mcp_server.tools.contacts import manage_contact  # noqa: E402
from redmine_mcp_server.tools.issues import list_redmine_issues  # noqa: E402

REDMINE_URL = "https://redmine.example.invalid"


class _Recorder:
    """Records the requests a call attempted.

    Only ``engine.request`` is replaced, never the engine itself: a list read
    goes through python-redmine's ``bulk_request``, which is the library's own
    paging arithmetic and has to stay real, and an ``uploads`` value is decoded
    by the library before any request is issued at all. Stubbing one layer
    lower would hide both.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> Any:
        body = kwargs.get("data")
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": dict(kwargs.get("params") or {}),
                "data_bytes": body.read() if hasattr(body, "read") else None,
            }
        )
        if url.endswith("/uploads.json"):
            return {"upload": {"token": "TOKEN"}}
        if url.endswith("/contacts.json"):
            return {"contacts": [], "total_count": 0}
        return {"issues": [], "total_count": 0}

    @property
    def urls(self) -> List[str]:
        return [call["url"] for call in self.calls]


@pytest.fixture
def engine(monkeypatch):
    client = Redmine(REDMINE_URL, key="CONFIGURED-SERVER-KEY")
    recorder = _Recorder()
    monkeypatch.setattr(client.engine, "request", recorder)
    monkeypatch.setattr(_client, "redmine", client)
    return recorder


@pytest.fixture
def crm(monkeypatch):
    monkeypatch.setenv("REDMINE_CRM_ENABLED", "true")
    monkeypatch.setenv("REDMINE_CRM_EDITION", "pro")


def _error(result: Any) -> str:
    assert isinstance(result, dict), f"expected an error dict, got {result!r}"
    assert "error" in result, f"expected an error key, got {sorted(result)}"
    return result["error"]


# --------------------------------------------------------------------------
# The file read. This is the case the whole change exists for.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_filters_cannot_read_a_local_file(engine, tmp_path):
    secret = tmp_path / "dot-env"
    secret.write_bytes(b"REDMINE_API_KEY=super-secret\n")

    result = await list_redmine_issues(
        filters={"uploads": [{"path": str(secret), "filename": "exfil"}]}
    )

    _error(result)
    assert engine.calls == [], (
        "the tool must refuse before any request: "
        f"{[c['method'] + ' ' + c['url'] for c in engine.calls]}"
    )


@pytest.mark.asyncio
async def test_issue_filters_refusal_survives_read_only_mode(
    engine, tmp_path, monkeypatch
):
    """The refusal is the validation, not the read-only gate.

    Pinned because ``REDMINE_MCP_READ_ONLY`` is the mechanism a reader would
    assume already covers this, and it does not: the gate fires only for
    ``ActionMode.WRITE`` and this is a read tool.
    """
    monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
    secret = tmp_path / "dot-env"
    secret.write_bytes(b"REDMINE_API_KEY=super-secret\n")

    result = await list_redmine_issues(filters={"uploads": [{"path": str(secret)}]})

    _error(result)
    assert "/uploads.json" not in engine.urls
    assert secret.read_bytes() == b"REDMINE_API_KEY=super-secret\n"


# --------------------------------------------------------------------------
# The credential substitution, on both tools.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_filters_cannot_carry_a_credential(engine):
    result = await list_redmine_issues(filters={"key": "SOMEONE-ELSES-KEY"})

    assert "key" in _error(result)
    assert engine.calls == []


@pytest.mark.asyncio
async def test_contact_filters_cannot_carry_a_credential(engine, crm):
    result = await manage_contact(action="list", filters={"key": "SOMEONE-ELSES-KEY"})

    assert "key" in _error(result)
    assert engine.calls == []


# --------------------------------------------------------------------------
# Unregistered names and non-scalar values, the general cases behind both.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["uploads", "key", "not_a_filter", "include_journals"])
async def test_issue_filters_refuse_unregistered_keys(engine, key):
    result = await list_redmine_issues(filters={key: "x"})
    assert key in _error(result)
    assert engine.calls == []


@pytest.mark.asyncio
async def test_issue_filters_refuse_non_scalar_values(engine):
    result = await list_redmine_issues(filters={"status_id": ["1", "2"]})
    assert "status_id" in _error(result)
    assert engine.calls == []


@pytest.mark.asyncio
async def test_issue_filters_cannot_widen_the_request_window(engine):
    """A ``limit`` inside ``filters`` is bounded like the named parameter.

    It is not refused: some MCP clients wrap every parameter into ``filters``,
    and ``test_mcp_parameter_unwrapping`` pins that as supported. But the dict
    was spread last, so before this change a limit there beat both the
    ``le=1000`` bound on the parameter and the cap in the body -- and
    python-redmine issues one request per 100 rows *asked for*, so an unbounded
    limit multiplies the request count rather than the rows.
    """
    result = await list_redmine_issues(filters={"limit": 99999})

    assert not isinstance(result, dict) or "error" not in result, result
    assert engine.calls[0]["params"]["limit"] == 1000


@pytest.mark.asyncio
async def test_a_wrapped_window_still_reaches_redmine(engine):
    result = await list_redmine_issues(
        filters={"project_id": 1, "limit": 5, "offset": 10}
    )

    assert not isinstance(result, dict) or "error" not in result, result
    sent = engine.calls[0]["params"]
    assert (sent["limit"], sent["offset"], sent["project_id"]) == (5, 10, 1)


# --------------------------------------------------------------------------
# What must keep working. A filter allowlist that refuses a registered filter
# is worse than none, so these are the regression pins.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters",
    [
        {"cf_42": "value"},
        {"cf_42.cf_7": "value"},
        {"cf_42.due_date": ">=2024-01-01"},
        {"author.cf_42": "value"},
        {"assigned_to.cf_42": "value"},
        {"project.cf_42": "value"},
        {"fixed_version.cf_42": "value"},
        {"subject": "~api"},
        {"created_on": ">=2024-01-01"},
        {"tracker_id": "56|57"},
        {"assigned_to_id": "!*"},
        {"relates": "*"},
        {"any_searchable": "~thing"},
        {"project.status": "1"},
        {"author.group": "5"},
    ],
)
async def test_registered_issue_filters_still_reach_redmine(engine, filters):
    result = await list_redmine_issues(filters=filters)

    assert not isinstance(result, dict) or "error" not in result, result
    assert len(engine.calls) == 1, engine.urls
    sent = engine.calls[0]["params"]
    for name, value in filters.items():
        assert sent.get(name) == value, f"{name} was not forwarded: {sent}"


@pytest.mark.asyncio
async def test_include_may_still_be_a_list_in_issue_filters(engine):
    """``include`` is a request parameter, not a query filter.

    The tool reads it out of ``filters`` and normalises a list into Redmine's
    comma-separated form on purpose, so the scalar rule must not reach it.
    """
    result = await list_redmine_issues(
        include_relations=True, filters={"include": ["journals"]}
    )

    assert not isinstance(result, dict) or "error" not in result, result
    assert engine.calls[0]["params"]["include"] == "journals,relations"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters", [{"cf_42": "value"}, {"author.cf_42": "v"}, {"is_company": "1"}]
)
async def test_registered_contact_filters_still_reach_redmine(engine, crm, filters):
    result = await manage_contact(action="list", filters=filters)

    assert not isinstance(result, dict) or "error" not in result, result
    assert len(engine.calls) == 1, engine.urls
    sent = engine.calls[0]["params"]
    for name, value in filters.items():
        assert sent.get(name) == value, f"{name} was not forwarded: {sent}"


@pytest.mark.asyncio
async def test_contact_filters_refuse_unregistered_keys(engine, crm):
    result = await manage_contact(action="list", filters={"not_a_filter": "x"})
    assert "not_a_filter" in _error(result)
    assert engine.calls == []


# --------------------------------------------------------------------------
# ``query_id`` runs a saved query. ``list_redmine_queries`` documents this as
# the way to run one, so it must keep reaching Redmine on the issue tool even
# though it is a reserved key on the project list. The scalar rule still binds.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_saved_query_id_still_reaches_redmine(engine):
    result = await list_redmine_issues(filters={"query_id": 7})

    assert not isinstance(result, dict) or "error" not in result, result
    assert engine.calls[0]["params"]["query_id"] == 7


@pytest.mark.asyncio
async def test_a_non_scalar_query_id_is_refused(engine):
    result = await list_redmine_issues(filters={"query_id": [7]})

    assert "query_id" in _error(result)
    assert engine.calls == []


@pytest.mark.asyncio
async def test_query_id_stays_reserved_on_contacts(engine, crm):
    result = await manage_contact(action="list", filters={"query_id": 7})

    assert "query_id" in _error(result)
    assert engine.calls == []
