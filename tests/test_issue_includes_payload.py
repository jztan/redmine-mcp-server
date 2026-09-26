"""Regression tests for reading issue includes without re-fetching (#360).

``journals``, ``attachments``, ``watchers`` and ``children`` are in
python-redmine's ``Issue._includes``. Reading one as an attribute when the key
is missing from the payload makes ``BaseResource.__getattr__`` call
``refresh(itself=False, include=<name>)`` -- a second ``GET`` of the whole
issue -- and answer ``[]`` when Redmine omits it again. Redmine omits two of
them on purpose (``app/views/issues/show.api.rsb`` in 6.1.1 and 7.0.0):
``children`` for every leaf issue, and ``watchers`` for a caller without
``view_issue_watchers``.

These tests keep python-redmine whole and cut the socket at the engine, so the
``__getattr__`` fallback is the real one and every request it would send is
counted. A ``Mock`` issue cannot show this: it has no fallback to trigger.
"""

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from redminelib import Redmine
from redminelib.engines import SyncEngine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._serialization import _included_resources  # noqa: E402
from redmine_mcp_server.tools.issues import (  # noqa: E402
    _attachments_to_list,
    _journals_to_list,
    _newest_journal_id,
    get_private_notes,
    get_redmine_issue,
)

_ISSUE: Dict[str, Any] = {
    "id": 1,
    "project": {"id": 1, "name": "Project"},
    "tracker": {"id": 1, "name": "Bug"},
    "status": {"id": 1, "name": "New", "is_closed": False},
    "priority": {"id": 2, "name": "Normal"},
    "author": {"id": 1, "name": "Author"},
    "subject": "Parent",
    "description": "d",
    "created_on": "2026-01-01T10:00:00Z",
    "updated_on": "2026-01-02T10:00:00Z",
}

# What Redmine renders for each include when it renders it at all.
_INCLUDES: Dict[str, List[Dict[str, Any]]] = {
    "journals": [
        {
            "id": 7,
            "user": {"id": 1, "name": "Author"},
            "notes": "a comment",
            "created_on": "2026-01-02T10:00:00Z",
            "private_notes": False,
            "details": [],
        },
        {
            "id": 8,
            "user": {"id": 1, "name": "Author"},
            "notes": "a private comment",
            "created_on": "2026-01-03T10:00:00Z",
            "private_notes": True,
            "details": [],
        },
    ],
    "attachments": [
        {
            "id": 99,
            "filename": "a.txt",
            "filesize": 3,
            "content_type": "text/plain",
            "description": "",
            "content_url": "https://redmine.example.com/attachments/download/99/a.txt",
            "author": {"id": 1, "name": "Author"},
            "created_on": "2026-01-02T10:00:00Z",
        }
    ],
    "watchers": [{"id": 10, "name": "Watcher"}],
    "children": [{"id": 2, "tracker": {"id": 1, "name": "Bug"}, "subject": "Child"}],
}


class _IssueEngine(SyncEngine):
    """Serves ``GET /issues/1.json`` the way Redmine renders it, and counts.

    ``omitted`` names includes Redmine leaves out even when asked: ``children``
    on a leaf issue, ``watchers`` without ``view_issue_watchers``.
    """

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.calls: List[Optional[str]] = []
        self.omitted: set = set()

    def request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        params = kwargs.get("params") or {}
        include = params.get("include")
        self.calls.append(include)
        issue = dict(_ISSUE)
        for name in (include or "").split(","):
            if name in _INCLUDES and name not in self.omitted:
                issue[name] = [dict(item) for item in _INCLUDES[name]]
        return {"issue": issue}


@pytest.fixture
def client():
    redmine = Redmine(
        "https://redmine.example.com", key="configured-key", engine=_IssueEngine
    )
    with patch("redmine_mcp_server._client.redmine", redmine):
        yield redmine


class TestIncludedResources:
    def test_present_include_is_read_from_the_payload(self, client):
        issue = client.issue.get(1, include="watchers")
        watchers = _included_resources(issue, "watchers")
        assert [(w.id, w.name) for w in watchers] == [(10, "Watcher")]
        assert client.engine.calls == ["watchers"]

    @pytest.mark.parametrize(
        "name", ["journals", "attachments", "watchers", "children"]
    )
    def test_absent_include_is_empty_and_never_fetched(self, client, name):
        issue = client.issue.get(1)
        assert _included_resources(issue, name) == []
        assert client.engine.calls == [None]

    def test_omitted_include_is_empty_and_never_fetched(self, client):
        client.engine.omitted = {"children"}
        issue = client.issue.get(1, include="children")
        assert _included_resources(issue, "children") == []
        assert client.engine.calls == ["children"]

    def test_requested_but_empty_is_empty(self, client):
        issue = client.issue.get(1)
        issue.raw()["watchers"] = []
        assert _included_resources(issue, "watchers") == []
        assert client.engine.calls == [None]

    def test_a_fallback_that_already_ran_is_not_read_as_present(self, client):
        """The attribute leaves the key in ``raw()`` holding ``None``."""
        client.engine.omitted = {"children"}
        issue = client.issue.get(1)
        assert list(issue.children) == []  # the old read: one re-fetch
        assert issue.raw()["children"] is None
        assert _included_resources(issue, "children") == []
        assert client.engine.calls == [None, "children"]


class TestSerializersNeverFetch:
    def test_journals_attachments_and_newest_id_without_the_include(self, client):
        issue = client.issue.get(1)
        assert _journals_to_list(issue) == []
        assert _attachments_to_list(issue) == []
        assert _newest_journal_id(issue) is None
        assert client.engine.calls == [None]

    def test_journals_attachments_and_newest_id_with_the_include(self, client):
        issue = client.issue.get(1, include="attachments,journals")
        assert [j["id"] for j in _journals_to_list(issue)] == [7, 8]
        assert [a["id"] for a in _attachments_to_list(issue)] == [99]
        assert _newest_journal_id(issue) == 8
        assert client.engine.calls == ["attachments,journals"]


class TestGetRedmineIssue:
    @pytest.mark.asyncio
    async def test_a_leaf_issue_costs_one_request(self, client):
        client.engine.omitted = {"children"}
        result = await get_redmine_issue(1, include_children=True)
        assert result["children"] == []
        assert len(client.engine.calls) == 1

    @pytest.mark.asyncio
    async def test_watchers_withheld_by_redmine_cost_one_request(self, client):
        client.engine.omitted = {"watchers"}
        result = await get_redmine_issue(1, include_watchers=True)
        assert result["watchers"] == []
        assert len(client.engine.calls) == 1

    @pytest.mark.asyncio
    async def test_every_include_is_served_by_one_request(self, client):
        result = await get_redmine_issue(
            1, include_watchers=True, include_children=True
        )
        assert [j["id"] for j in result["journals"]] == [7, 8]
        assert [a["id"] for a in result["attachments"]] == [99]
        assert result["watchers"] == [{"id": 10, "name": "Watcher"}]
        assert result["children"] == [
            {"id": 2, "subject": "Child", "tracker": {"id": 1, "name": "Bug"}}
        ]
        assert len(client.engine.calls) == 1
        assert set(client.engine.calls[0].split(",")) == {
            "journals",
            "attachments",
            "watchers",
            "children",
        }


class TestGetPrivateNotes:
    @pytest.mark.asyncio
    async def test_reads_the_journals_include(self, client):
        result = await get_private_notes(issue_id=1)
        assert [j["id"] for j in result] == [8]
        assert client.engine.calls == ["journals"]
