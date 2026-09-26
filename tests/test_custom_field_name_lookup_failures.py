"""A custom field name that cannot be resolved is reported, not dropped (#362).

``create_redmine_issue`` and ``update_redmine_issue`` resolve a name-keyed
``fields`` entry (``{"Department": "Engineering"}``) by reading
``GET /projects/{id}.json?include=issue_custom_fields``. That read needs
``view_project``, which neither tool's scope entry requires, because only a
name-keyed payload makes it. When it could not be read:

- a 403 escaped ``create_redmine_issue`` as an unhandled exception, and on
  ``update_redmine_issue`` came back as "Access denied" for the update itself;
- an omitted array was read through python-redmine's include fallback, which
  re-fetched the project and answered ``[]``, leaving every name unresolved and
  sent on as a top-level key Redmine ignores. Redmine 6.1.4 and 7.0.1 leave
  the array out for a caller without ``view_issues`` on the project; earlier
  releases always send it.

The engine below keeps python-redmine whole and records every request, so the
tests can assert that nothing was written, not only that an error came back.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from redminelib import Redmine
from redminelib.engines import SyncEngine
from redminelib.exceptions import ForbiddenError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.issues import (  # noqa: E402
    create_redmine_issue,
    update_redmine_issue,
)

_ISSUE: Dict[str, Any] = {
    "id": 5,
    "project": {"id": 1, "name": "Project"},
    "tracker": {"id": 1, "name": "Bug"},
    "status": {"id": 1, "name": "New", "is_closed": False},
    "priority": {"id": 2, "name": "Normal"},
    "author": {"id": 1, "name": "Author"},
    "subject": "Subject",
    "description": "",
    "custom_fields": [{"id": 1, "name": "Department", "value": ""}],
    "created_on": "2026-01-01T10:00:00Z",
    "updated_on": "2026-01-01T10:00:00Z",
}


class _Engine(SyncEngine):
    """Serves the issue and its project as Redmine renders them, and records.

    ``fields`` is the project's ``issue_custom_fields`` array, or ``None`` for
    a response that leaves it out. ``forbidden`` names the reads that answer
    403: ``"project"`` for ``projects#show``, ``"issue"`` for ``issues#show``.
    """

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.calls: List[Dict[str, Any]] = []
        self.fields: Optional[List[Dict[str, Any]]] = [{"id": 1, "name": "Department"}]
        self.forbidden: set = set()

    @property
    def writes(self) -> List[Dict[str, Any]]:
        return [call for call in self.calls if call["method"] != "get"]

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        method = method.lower()
        data = kwargs.get("data")
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": kwargs.get("params"),
                "body": json.loads(data) if isinstance(data, str) else data,
            }
        )
        if method == "post":  # POST /projects/{id}/issues.json
            return {"issue": dict(_ISSUE)}
        if method == "put":
            return True  # 204
        if "/projects/" in url:
            if "project" in self.forbidden:
                raise ForbiddenError()
            project: Dict[str, Any] = {"id": 1, "name": "Project"}
            if self.fields is not None:
                project["issue_custom_fields"] = [dict(f) for f in self.fields]
            return {"project": project}
        if "issue" in self.forbidden:
            raise ForbiddenError()
        return {"issue": dict(_ISSUE)}


@pytest.fixture
def engine():
    client = Redmine(
        "https://redmine.example.com", key="configured-key", engine=_Engine
    )
    with patch("redmine_mcp_server._client.redmine", client):
        yield client.engine


def _project_reads(engine: _Engine) -> List[Dict[str, Any]]:
    return [
        call
        for call in engine.calls
        if call["method"] == "get" and "/projects/" in call["url"]
    ]


class TestCreate:
    @pytest.mark.asyncio
    async def test_a_denied_lookup_is_reported_and_nothing_is_created(self, engine):
        engine.forbidden = {"project"}

        result = await create_redmine_issue(
            project_id=1, subject="X", fields={"Department": "Engineering"}
        )

        assert isinstance(result, dict)
        assert "custom field names" in result["error"]
        assert "view_project" in result["error"]
        assert 'fields={"custom_fields"' in result["error"]
        assert "Nothing was written" in result["error"]
        assert engine.writes == []

    @pytest.mark.asyncio
    async def test_an_omitted_array_is_reported_and_nothing_is_created(self, engine):
        engine.fields = None

        result = await create_redmine_issue(
            project_id=1, subject="X", fields={"Department": "Engineering"}
        )

        assert "issue_custom_fields" in result["error"]
        assert "view_issues" in result["error"]
        assert 'fields={"custom_fields"' in result["error"]
        assert engine.writes == []
        # Checked on the payload: the include fallback's re-fetch never runs.
        assert len(_project_reads(engine)) == 1

    @pytest.mark.asyncio
    async def test_a_readable_lookup_still_resolves_the_name(self, engine):
        result = await create_redmine_issue(
            project_id=1, subject="X", fields={"Department": "Engineering"}
        )

        assert "error" not in result, result
        (post,) = engine.writes
        assert post["body"]["issue"]["custom_fields"] == [
            {"id": 1, "value": "Engineering"}
        ]
        assert "Department" not in post["body"]["issue"]

    @pytest.mark.asyncio
    async def test_an_empty_array_leaves_the_name_to_redmine_as_before(self, engine):
        """A project with no fields is a real answer, not an unreadable one."""
        engine.fields = []

        result = await create_redmine_issue(
            project_id=1, subject="X", fields={"Department": "Engineering"}
        )

        assert "error" not in result, result
        assert len(engine.writes) == 1

    @pytest.mark.asyncio
    async def test_standard_fields_alone_never_read_the_project(self, engine):
        engine.forbidden = {"project"}

        result = await create_redmine_issue(
            project_id=1, subject="X", fields={"priority_id": 2}
        )

        assert "error" not in result, result
        assert _project_reads(engine) == []
        assert len(engine.writes) == 1


class TestUpdate:
    @pytest.mark.asyncio
    async def test_a_denied_project_read_is_not_reported_as_the_update(self, engine):
        engine.forbidden = {"project"}

        result = await update_redmine_issue(5, {"Department": "Engineering"})

        assert "custom field names" in result["error"]
        assert "view_project" in result["error"]
        assert "Nothing was written" in result["error"]
        assert engine.writes == []

    @pytest.mark.asyncio
    async def test_a_denied_issue_read_names_view_issues(self, engine):
        engine.forbidden = {"issue"}

        result = await update_redmine_issue(5, {"Department": "Engineering"})

        assert "issue 5" in result["error"]
        assert "view_issues" in result["error"]
        assert engine.writes == []
        assert _project_reads(engine) == []

    @pytest.mark.asyncio
    async def test_an_omitted_array_is_reported_and_nothing_is_written(self, engine):
        engine.fields = None

        result = await update_redmine_issue(5, {"Department": "Engineering"})

        assert "issue_custom_fields" in result["error"]
        assert engine.writes == []
        assert len(_project_reads(engine)) == 1

    @pytest.mark.asyncio
    async def test_an_ambiguous_name_is_reported_as_itself(self, engine):
        """A ValueError from the lookup is the caller's, as it is on create."""
        engine.fields = [
            {"id": 1, "name": "Project Category"},
            {"id": 2, "name": "Project-Category"},
        ]

        result = await update_redmine_issue(5, {"project category": "Bug"})

        assert result["error"].startswith("Ambiguous custom field name")
        assert engine.writes == []

    @pytest.mark.asyncio
    async def test_a_readable_lookup_still_resolves_the_name(self, engine):
        result = await update_redmine_issue(5, {"Department": "Engineering"})

        assert "error" not in result, result
        (put,) = engine.writes
        assert put["body"]["issue"]["custom_fields"] == [
            {"id": 1, "value": "Engineering"}
        ]
