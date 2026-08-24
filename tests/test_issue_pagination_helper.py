"""The issue tools' pagination envelope, after migrating to _pagination_info.

Issue #240: `list_redmine_issues` hand-built its pagination keys with two
defects the shared helper fixes, and `search_redmine_issues` shipped a
seven-key envelope with no `total` at all.

- `has_next` was inferred from ``len(result) == limit``, which reports one
  page too many whenever the collection size is an exact multiple of the
  page size. The helper measures it from the total instead.
- The total cost a second ``limit=1`` request, although python-redmine's
  ResourceSet carries ``total_count`` on the response the rows already came
  from. Reading it there makes the envelope free.
- When nothing measured the collection, the old code invented an estimate
  (``offset + count + 1``); the helper reports ``null``, which the docs
  define as "not reported" rather than a number nothing measured.

The fakes avoid ``Mock`` for the resource set on purpose: a ``Mock`` answers
``total_count`` whether the response carried one or not, and presence versus
absence of that number is the thing under test.
"""

import pytest
from unittest.mock import Mock, patch

from redmine_mcp_server.tools.issues import (
    list_redmine_issues,
    search_redmine_issues,
)
from redmine_mcp_server._serialization import _pagination_info

PAGINATION_KEYS = {
    "total",
    "limit",
    "offset",
    "count",
    "has_next",
    "has_previous",
    "next_offset",
    "previous_offset",
}


def _mock_issue(issue_id):
    issue = Mock()
    issue.id = issue_id
    issue.subject = f"Issue {issue_id}"
    issue.description = f"Description for issue {issue_id}"
    issue.project = Mock(id=1, name="Test Project")
    issue.status = Mock(id=1, name="New")
    issue.priority = Mock(id=2, name="Normal")
    issue.author = Mock(id=10, name="John Doe")
    issue.assigned_to = Mock(id=20, name="Jane Smith")
    issue.created_on = None
    issue.updated_on = None
    return issue


class FakeResourceSet:
    """Iterable of issues that carries total_count only when told to.

    Mirrors python-redmine's ResourceSet closely enough for these tests:
    iterating yields the issues, and ``total_count`` either answers the
    number the response envelope carried or raises, the way an unevaluated
    or metadata-less set does.
    """

    def __init__(self, issues, total_count=None):
        self._issues = list(issues)
        self._total_count = total_count

    def __iter__(self):
        return iter(self._issues)

    @property
    def total_count(self):
        if self._total_count is None:
            raise AttributeError("total_count not available")
        return self._total_count


@pytest.fixture
def mock_redmine():
    with patch("redmine_mcp_server._client.redmine") as mock:
        yield mock


class TestListIssuesMeasuredHasNext:
    """`has_next` is measured from the total, not inferred from a full page."""

    @pytest.mark.asyncio
    async def test_exact_multiple_last_page_is_the_last(self, mock_redmine):
        """A full last page of an exact-multiple collection has no next.

        total 200, limit 100, offset 100: the inference
        ``len(result) == limit`` claims a further page; the measurement
        ``offset + limit < total`` knows there is none.
        """
        issues = [_mock_issue(i) for i in range(101, 201)]
        mock_redmine.issue.filter.return_value = FakeResourceSet(
            issues, total_count=200
        )

        result = await list_redmine_issues(
            project_id=1, limit=100, offset=100, include_pagination_info=True
        )

        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["next_offset"] is None

    @pytest.mark.asyncio
    async def test_middle_page_still_has_next(self, mock_redmine):
        issues = [_mock_issue(i) for i in range(1, 101)]
        mock_redmine.issue.filter.return_value = FakeResourceSet(
            issues, total_count=300
        )

        result = await list_redmine_issues(
            project_id=1, limit=100, offset=0, include_pagination_info=True
        )

        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["next_offset"] == 100


class TestListIssuesTotalCostsNothing:
    """The total is read off the response the rows came from."""

    @pytest.mark.asyncio
    async def test_no_second_request_for_the_total(self, mock_redmine):
        issues = [_mock_issue(i) for i in range(1, 26)]
        mock_redmine.issue.filter.return_value = FakeResourceSet(
            issues, total_count=100
        )

        result = await list_redmine_issues(
            project_id=1, limit=25, offset=0, include_pagination_info=True
        )

        assert mock_redmine.issue.filter.call_count == 1
        assert result["pagination"]["total"] == 100

    @pytest.mark.asyncio
    async def test_unmeasured_total_is_null_not_an_estimate(self, mock_redmine):
        """A response carrying no total yields null, not offset+count+1."""
        issues = [_mock_issue(i) for i in range(1, 26)]
        mock_redmine.issue.filter.return_value = FakeResourceSet(
            issues, total_count=None
        )

        result = await list_redmine_issues(
            project_id=1, limit=25, offset=0, include_pagination_info=True
        )

        assert result["pagination"]["total"] is None
        # Without a total, has_next falls back to the full-page inference.
        assert result["pagination"]["has_next"] is True

    @pytest.mark.asyncio
    async def test_unmeasured_total_short_page_is_the_end(self, mock_redmine):
        issues = [_mock_issue(i) for i in range(1, 6)]
        mock_redmine.issue.filter.return_value = FakeResourceSet(
            issues, total_count=None
        )

        result = await list_redmine_issues(
            project_id=1, limit=25, offset=0, include_pagination_info=True
        )

        assert result["pagination"]["total"] is None
        assert result["pagination"]["has_next"] is False


class TestListIssuesRequestedLimitIsSent:
    """The limit the schema allows is the limit the request carries.

    python-redmine pages a limit above 100 itself, in chunks of 100, so
    capping the request at 100 silently truncated ``limit=250`` to 100 rows
    while the envelope reported the requested 250 -- and a measured
    ``next_offset`` of 250 would then step over the 150 rows never fetched.
    """

    @pytest.mark.asyncio
    async def test_limit_above_100_is_passed_through(self, mock_redmine):
        issues = [_mock_issue(i) for i in range(1, 101)]
        mock_redmine.issue.filter.return_value = FakeResourceSet(
            issues, total_count=100
        )

        await list_redmine_issues(
            project_id=1, limit=250, offset=0, include_pagination_info=True
        )

        assert mock_redmine.issue.filter.call_args[1]["limit"] == 250


class TestEnvelopeShape:
    """Both issue tools return the shared helper's key set."""

    @pytest.mark.asyncio
    async def test_list_envelope_matches_the_shared_helper(self, mock_redmine):
        issues = [_mock_issue(i) for i in range(1, 4)]
        mock_redmine.issue.filter.return_value = FakeResourceSet(issues, total_count=3)

        result = await list_redmine_issues(
            project_id=1, limit=25, offset=0, include_pagination_info=True
        )

        assert set(result["pagination"].keys()) == PAGINATION_KEYS
        assert result["pagination"] == _pagination_info(
            limit=25, offset=0, count=3, total=3
        )

    @pytest.mark.asyncio
    async def test_search_envelope_carries_a_null_total(self, mock_redmine):
        """The search API reports no total, so the envelope says null.

        Previously the search envelope simply omitted the key, so the two
        issue tools disagreed about the shape a caller had learned.
        """
        issues = [_mock_issue(i) for i in range(1, 6)]
        mock_redmine.issue.search.return_value = issues

        result = await search_redmine_issues(
            "bug", limit=25, offset=0, include_pagination_info=True
        )

        assert set(result["pagination"].keys()) == PAGINATION_KEYS
        assert result["pagination"]["total"] is None
        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    async def test_search_full_page_still_infers_a_next(self, mock_redmine):
        issues = [_mock_issue(i) for i in range(1, 26)]
        mock_redmine.issue.search.return_value = issues

        result = await search_redmine_issues(
            "bug", limit=25, offset=0, include_pagination_info=True
        )

        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["next_offset"] == 25
