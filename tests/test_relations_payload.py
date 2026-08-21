"""Regression tests for reading ``include=relations`` from the payload (#222).

python-redmine lists ``relations`` in both ``Issue._includes`` and
``Issue._relations``, and ``BaseResource.__getattr__`` tests ``_relations``
first, so ``issue.relations`` never reads an ``include=relations`` payload: it
issues a fresh ``GET /issues/{id}/relations.json``. That endpoint is mapped to
``manage_issue_relations`` (``lib/redmine/preparation.rb``), a permission
reading the issue does not imply, so the attribute both wasted the include and
could be denied.

These tests assert the property that matters and that a mock of the attribute
cannot show: the tools read the payload and never touch the lazy attribute.
"""

import os
import sys
from unittest.mock import Mock, PropertyMock, patch

import pytest
from redminelib.exceptions import ForbiddenError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._serialization import (  # noqa: E402
    _included_list,
    _issue_relations_to_list,
)
from redmine_mcp_server.tools.gantt import get_gantt_chart  # noqa: E402
from redmine_mcp_server.tools.issues import (  # noqa: E402
    delete_redmine_issue,
    get_redmine_issue,
)

_PAYLOAD_RELATION = {
    "id": 5,
    "issue_id": 123,
    "issue_to_id": 456,
    "relation_type": "precedes",
    "delay": 2,
}


def _issue_with_payload(relations, payload=None, **attrs):
    """An issue whose included collections live only in the payload.

    Touching ``.relations`` raises ``ForbiddenError``, standing in for the 403
    a caller without ``manage_issue_relations`` gets from the lazy re-fetch.
    """
    issue = Mock()
    issue.id = attrs.pop("id", 1)
    issue.subject = attrs.pop("subject", "Test issue")
    for key, value in attrs.items():
        setattr(issue, key, value)
    issue.raw.return_value = {**(payload or {}), "relations": list(relations)}
    type(issue).relations = PropertyMock(side_effect=ForbiddenError)
    return issue


class TestIncludedList:
    def test_reads_the_payload(self):
        issue = _issue_with_payload([_PAYLOAD_RELATION])
        assert _included_list(issue, "relations") == [_PAYLOAD_RELATION]

    def test_absent_include_is_empty_not_an_error(self):
        issue = Mock()
        issue.raw.return_value = {"relations": None}
        assert _included_list(issue, "relations") == []

    def test_requested_but_empty_is_empty(self):
        issue = Mock()
        issue.raw.return_value = {"relations": []}
        assert _included_list(issue, "relations") == []

    def test_never_touches_the_lazy_attribute(self):
        """The whole point: reading relations must not hit the attribute.

        The fake raises on ``.relations``, so a regression to ``getattr``
        fails here instead of only against a live Redmine.
        """
        issue = _issue_with_payload([_PAYLOAD_RELATION])
        assert _issue_relations_to_list(issue) == [_PAYLOAD_RELATION]
        issue.raw.assert_called()

    def test_serializes_every_relation_field(self):
        issue = _issue_with_payload([_PAYLOAD_RELATION])
        assert _issue_relations_to_list(issue) == [
            {
                "id": 5,
                "issue_id": 123,
                "issue_to_id": 456,
                "relation_type": "precedes",
                "delay": 2,
            }
        ]


class TestGetRedmineIssue:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    @patch("redmine_mcp_server._client.redmine")
    async def test_relations_come_from_the_include(self, mock_redmine, mock_cleanup):
        mock_redmine.issue.get.return_value = _issue_with_payload(
            [_PAYLOAD_RELATION],
            description="d",
            project=Mock(id=1, name="P"),
            status=Mock(id=1, name="New"),
            priority=Mock(id=2, name="Normal"),
            author=Mock(id=1, name="A"),
            assigned_to=None,
            created_on=None,
            updated_on=None,
        )

        result = await get_redmine_issue(1, include_relations=True)

        assert result["relations"] == [_PAYLOAD_RELATION]
        # The include was requested, and one request served the whole call.
        assert "relations" in mock_redmine.issue.get.call_args[1]["include"]
        assert mock_redmine.issue.get.call_count == 1


class TestGanttChart:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_no_extra_request_per_issue(self, mock_redmine):
        """The N+1 this fixes: three issues used to mean three extra calls."""
        issues = [
            _issue_with_payload([dict(_PAYLOAD_RELATION, issue_id=n)], id=n)
            for n in (1, 2, 3)
        ]
        for issue in issues:
            issue.start_date = "2026-04-01"
            issue.due_date = "2026-04-15"
            issue.done_ratio = 0
            issue.estimated_hours = 1.0
            issue.parent = None
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.version.filter.return_value = []

        result = await get_gantt_chart(project_id="proj")

        assert [len(i["relations"]) for i in result["issues"]] == [1, 1, 1]
        # One issues.json call for the whole chart, plus the versions call.
        assert mock_redmine.issue.filter.call_count == 1


class TestDeletePreview:
    """The delete preview read relations outside its own try/except."""

    def _issue(self, **kw):
        return _issue_with_payload(
            kw.pop("relations", [_PAYLOAD_RELATION]),
            payload={"children": [], "journals": [], "attachments": []},
            **kw,
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_preview_survives_without_manage_issue_relations(self, mock_redmine):
        """Previously raised out of the tool instead of returning the gate."""
        mock_redmine.issue.get.return_value = self._issue(time_entries=[])

        result = await delete_redmine_issue(issue_id=42)

        assert result["code"] == "CONFIRMATION_REQUIRED"
        assert result["impact"]["relations_count"] == 1
        mock_redmine.issue.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_unreadable_time_entries_are_not_reported_as_zero(self, mock_redmine):
        """Redmine has no time_entries include, so that fetch is real and can
        be denied. Saying "0" would understate an irreversible cascade."""
        issue = self._issue()
        type(issue).time_entries = PropertyMock(side_effect=ForbiddenError)
        mock_redmine.issue.get.return_value = issue

        result = await delete_redmine_issue(issue_id=42)

        impact = result["impact"]
        # Unknown, not 0 -- 0 would understate an irreversible cascade.
        assert impact["time_entries_count"] is None
        mock_redmine.issue.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_leaf_issue_counts_children_from_the_payload(self, mock_redmine):
        """Redmine omits ``children`` entirely for a leaf issue --
        ``render_api_issue_children`` returns early on ``issue.leaf?`` -- and
        python-redmine re-fetches whenever an include key is missing. That made
        the preview fire an unguarded extra request on the common case. The
        omission means zero, so the payload is the answer.
        """
        issue = _issue_with_payload(
            [], payload={"journals": [], "attachments": []}, time_entries=[]
        )
        type(issue).children = PropertyMock(side_effect=ForbiddenError)
        mock_redmine.issue.get.return_value = issue

        result = await delete_redmine_issue(issue_id=42)

        assert result["code"] == "CONFIRMATION_REQUIRED"
        assert result["impact"]["children_count"] == 0
        # One fetch for the whole preview.
        assert mock_redmine.issue.get.call_count == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_unexpected_time_entry_error_returns_an_envelope(self, mock_redmine):
        """A 500 or dropped connection is not a permission problem, so it must
        surface as an error rather than a silent 'unknown'."""
        from redminelib.exceptions import ServerError

        issue = self._issue()
        type(issue).time_entries = PropertyMock(side_effect=ServerError)
        mock_redmine.issue.get.return_value = issue

        result = await delete_redmine_issue(issue_id=42)

        assert "error" in result
        mock_redmine.issue.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_readable_time_entries_are_counted(self, mock_redmine):
        mock_redmine.issue.get.return_value = self._issue(
            time_entries=[Mock(id=1), Mock(id=2)]
        )

        result = await delete_redmine_issue(issue_id=42)

        assert result["impact"]["time_entries_count"] == 2
