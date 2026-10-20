"""Tests for search_redmine_issues hydration via /issues.json.

The Redmine /search.json endpoint only returns id, title, type, url, and
a description snippet. It does NOT return structured fields like status,
priority, project, assigned_to, author, or timestamps. To return a usable
record to the caller, search_redmine_issues hydrates results via
/issues.json (the same endpoint list_redmine_issues uses).

These tests mock the bug-reproducing scenario: /search.json returns
sparse issues (id + description only), /issues.json returns full records.
"""

import logging
import os
import sys
import pytest
from unittest.mock import Mock, patch

from redminelib import Redmine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.issues import (  # noqa: E402
    _search_result_issue_id,
    _search_title_subject,
    search_redmine_issues,
)


def _sparse_search_issue(issue_id, description="snippet"):
    """Mock issue matching what Redmine's /search.json actually returns.

    Only id and description are populated. All structured attributes
    (subject, status, priority, project, etc.) are absent, so getattr
    falls back to its default — reproducing the bug.
    """
    sparse = Mock(spec=["id", "description"])
    sparse.id = issue_id
    sparse.description = description
    return sparse


def _full_issue(issue_id, subject=None):
    """Mock issue matching what /issues.json returns (the hydrated record)."""
    issue = Mock()
    issue.id = issue_id
    issue.subject = subject if subject is not None else f"Issue {issue_id}"
    issue.description = f"Full description for {issue_id}"

    project = Mock()
    project.id = 1
    project.name = "Test Project"
    issue.project = project

    status = Mock()
    status.id = 2
    status.name = "In Progress"
    issue.status = status

    priority = Mock()
    priority.id = 3
    priority.name = "Normal"
    issue.priority = priority

    author = Mock()
    author.id = 10
    author.name = "Alice"
    issue.author = author

    assigned = Mock()
    assigned.id = 20
    assigned.name = "Bob"
    issue.assigned_to = assigned

    issue.created_on = None
    issue.updated_on = None
    return issue


class TestSearchHydration:
    @pytest.fixture
    def mock_redmine(self):
        with patch("redmine_mcp_server._client.redmine") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_default_fields_hydrate_structured_fields(self, mock_redmine):
        """Bug fix: sparse /search.json results must be hydrated via /issues.json."""
        mock_redmine.issue.search.return_value = [_sparse_search_issue(15883)]
        mock_redmine.issue.filter.return_value = [_full_issue(15883)]

        result = await search_redmine_issues("bug")

        assert len(result) == 1
        assert result[0]["id"] == 15883
        assert result[0]["subject"] == "Issue 15883"
        assert result[0]["status"] == {"id": 2, "name": "In Progress"}
        assert result[0]["project"] == {"id": 1, "name": "Test Project"}
        assert result[0]["priority"] == {"id": 3, "name": "Normal"}
        assert result[0]["author"] == {"id": 10, "name": "Alice"}
        assert result[0]["assigned_to"] == {"id": 20, "name": "Bob"}

        filter_call = mock_redmine.issue.filter.call_args
        assert filter_call.kwargs["issue_id"] == "15883"
        # status_id="*" required to also return closed issues; without it
        # /issues.json only returns open issues by default
        assert filter_call.kwargs["status_id"] == "*"

    @pytest.mark.asyncio
    async def test_hydration_preserves_search_order(self, mock_redmine):
        """Search relevance order must survive hydration, even when
        /issues.json returns issues in a different order (e.g., by id)."""
        mock_redmine.issue.search.return_value = [
            _sparse_search_issue(30),
            _sparse_search_issue(10),
            _sparse_search_issue(20),
        ]
        mock_redmine.issue.filter.return_value = [
            _full_issue(10),
            _full_issue(20),
            _full_issue(30),
        ]

        result = await search_redmine_issues("bug")

        assert [r["id"] for r in result] == [30, 10, 20]

    @pytest.mark.asyncio
    async def test_id_only_skips_hydration(self, mock_redmine):
        """fields=['id'] doesn't need hydration — skip the extra round-trip."""
        mock_redmine.issue.search.return_value = [_sparse_search_issue(100)]

        result = await search_redmine_issues("bug", fields=["id"])

        assert result == [{"id": 100}]
        mock_redmine.issue.filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_id_and_description_only_skips_hydration(self, mock_redmine):
        """fields=['id', 'description'] is fully servable by /search.json alone."""
        mock_redmine.issue.search.return_value = [
            _sparse_search_issue(100, "match snippet")
        ]

        result = await search_redmine_issues("bug", fields=["id", "description"])

        assert result[0]["id"] == 100
        assert "match snippet" in result[0]["description"]
        mock_redmine.issue.filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_structured_field_request_triggers_hydration(self, mock_redmine):
        """Requesting any field beyond id/description triggers hydration."""
        mock_redmine.issue.search.return_value = [_sparse_search_issue(50)]
        mock_redmine.issue.filter.return_value = [_full_issue(50)]

        result = await search_redmine_issues("bug", fields=["id", "status"])

        assert result[0]["id"] == 50
        assert result[0]["status"] == {"id": 2, "name": "In Progress"}
        mock_redmine.issue.filter.assert_called_once()

    @pytest.mark.asyncio
    async def test_subject_alone_triggers_hydration(self, mock_redmine):
        """Subject is not in /search.json (only title), so it requires hydration."""
        mock_redmine.issue.search.return_value = [_sparse_search_issue(7)]
        mock_redmine.issue.filter.return_value = [_full_issue(7)]

        result = await search_redmine_issues("bug", fields=["id", "subject"])

        assert result[0]["subject"] == "Issue 7"
        mock_redmine.issue.filter.assert_called_once()

    @pytest.mark.asyncio
    async def test_hydration_failure_falls_back_to_sparse(self, mock_redmine):
        """If hydration call raises, return sparse data rather than crashing."""
        mock_redmine.issue.search.return_value = [_sparse_search_issue(7)]
        mock_redmine.issue.filter.side_effect = RuntimeError("API down")

        result = await search_redmine_issues("bug")

        assert len(result) == 1
        assert result[0]["id"] == 7
        assert result[0]["status"] is None

    @pytest.mark.asyncio
    async def test_empty_search_results_skip_hydration(self, mock_redmine):
        """Zero results — don't fire a useless follow-up request."""
        mock_redmine.issue.search.return_value = []

        result = await search_redmine_issues("nonexistent")

        assert result == []
        mock_redmine.issue.filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_hydration_falls_back_per_issue(self, mock_redmine):
        """If some IDs aren't in the hydration response (deleted, permission
        change), keep the sparse data for those rather than dropping them."""
        mock_redmine.issue.search.return_value = [
            _sparse_search_issue(1),
            _sparse_search_issue(2),
        ]
        mock_redmine.issue.filter.return_value = [_full_issue(1)]

        result = await search_redmine_issues("bug")

        assert result[0]["subject"] == "Issue 1"
        assert result[1]["id"] == 2
        assert result[1]["subject"] == ""

    @pytest.mark.asyncio
    async def test_asterisk_fields_hydrate(self, mock_redmine):
        """fields=['*'] is equivalent to fields=None — must hydrate."""
        mock_redmine.issue.search.return_value = [_sparse_search_issue(99)]
        mock_redmine.issue.filter.return_value = [_full_issue(99)]

        result = await search_redmine_issues("bug", fields=["*"])

        assert result[0]["subject"] == "Issue 99"
        mock_redmine.issue.filter.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_fields_list_skips_hydration(self, mock_redmine):
        """fields=[] returns empty dicts — no need to hydrate."""
        mock_redmine.issue.search.return_value = [_sparse_search_issue(1)]

        result = await search_redmine_issues("bug", fields=[])

        assert result == [{}]
        mock_redmine.issue.filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_hydration_pagination_info_preserved(self, mock_redmine):
        """include_pagination_info must still report the search result count
        even after hydration."""
        mock_redmine.issue.search.return_value = [
            _sparse_search_issue(1),
            _sparse_search_issue(2),
        ]
        mock_redmine.issue.filter.return_value = [_full_issue(1), _full_issue(2)]

        result = await search_redmine_issues(
            "bug", include_pagination_info=True, limit=2
        )

        assert result["pagination"]["count"] == 2
        assert len(result["issues"]) == 2
        assert result["issues"][0]["status"] == {"id": 2, "name": "In Progress"}

    @pytest.mark.asyncio
    async def test_hydration_batches_large_id_lists(self, mock_redmine):
        """ID list >100 must be split into batches to keep URLs sane."""
        ids = list(range(1, 151))
        mock_redmine.issue.search.return_value = [_sparse_search_issue(i) for i in ids]
        mock_redmine.issue.filter.side_effect = [
            [_full_issue(i) for i in ids[:100]],
            [_full_issue(i) for i in ids[100:]],
        ]

        result = await search_redmine_issues("bug", limit=150)

        assert len(result) == 150
        assert mock_redmine.issue.filter.call_count == 2
        first_call_ids = (
            mock_redmine.issue.filter.call_args_list[0].kwargs["issue_id"].split(",")
        )
        second_call_ids = (
            mock_redmine.issue.filter.call_args_list[1].kwargs["issue_id"].split(",")
        )
        assert len(first_call_ids) == 100
        assert len(second_call_ids) == 50

    @pytest.mark.asyncio
    async def test_short_hydration_logs_a_warning(self, mock_redmine, caplog):
        """A hydration that comes back short is logged, not only one that raises."""
        mock_redmine.issue.search.return_value = [
            _sparse_search_issue(1),
            _sparse_search_issue(2),
        ]
        mock_redmine.issue.filter.return_value = [_full_issue(1)]

        with caplog.at_level(logging.WARNING):
            await search_redmine_issues("bug")

        assert "Hydration returned 1 of 2 search results" in caplog.text


# Easy Redmine offsets the ids /search.json returns per entity type (issues by
# 300000000) and keeps the real id in `url`. Its title is the plain subject.
EASY_SEARCH_ROW = {
    "id": 300024224,
    "title": "S2-51 Close or defer the open ADRs",
    "type": "issue",
    "url": "https://redmine.example.test/issues/24224",
    "description": "match snippet",
    "datetime": "2026-09-01T10:00:00Z",
}


def _client(search_rows, issues):
    """A real python-redmine client answering /search.json and /issues.json.

    A real resource matters here: its `url` attribute is a property built
    from the (offset) id, not the `url` Redmine sent.
    """
    client = Redmine("https://redmine.example.test", key="unused")
    client.requests_made = []

    def _request(method, url, headers=None, params=None, data=None):
        client.requests_made.append((url, dict(params or {})))
        if url.endswith("/search.json"):
            # python-redmine pops `type` off each row, so hand it copies.
            rows = [dict(row) for row in search_rows]
            return {"results": rows, "total_count": len(rows), "offset": 0}
        if url.endswith("/issues.json"):
            return {"issues": issues, "total_count": len(issues), "offset": 0}
        raise AssertionError(f"unexpected request to {url}")

    client.engine.request = _request
    return client


def _issues_json_calls(client):
    return [params for url, params in client.requests_made if "/issues" in url]


class TestSearchOffsetIds:
    @pytest.mark.asyncio
    async def test_easy_offset_id_with_no_hydration_match(self, caplog):
        """Easy answers the offset ids with zero issues and no error."""
        client = _client([EASY_SEARCH_ROW], issues=[])

        with patch("redmine_mcp_server._client.redmine", client):
            with caplog.at_level(logging.WARNING):
                result = await search_redmine_issues("ADR")

        assert result[0]["id"] == 24224
        assert result[0]["subject"] == "S2-51 Close or defer the open ADRs"
        assert result[0]["status"] is None
        assert [c["issue_id"] for c in _issues_json_calls(client)] == ["24224"]
        assert "Hydration returned 0 of 1 search results" in caplog.text

    @pytest.mark.asyncio
    async def test_easy_offset_id_hydrates_by_real_id(self):
        full = {
            "id": 24224,
            "subject": "S2-51 Close or defer the open ADRs",
            "status": {"id": 2, "name": "In Progress"},
            "project": {"id": 1, "name": "Test Project"},
        }
        client = _client([EASY_SEARCH_ROW], issues=[full])

        with patch("redmine_mcp_server._client.redmine", client):
            result = await search_redmine_issues("ADR")

        assert result[0]["id"] == 24224
        assert result[0]["status"] == {"id": 2, "name": "In Progress"}

    @pytest.mark.asyncio
    async def test_id_and_description_return_the_real_id(self):
        """fields=['id', 'description'] skips hydration but not the id fix."""
        client = _client([EASY_SEARCH_ROW], issues=[])

        with patch("redmine_mcp_server._client.redmine", client):
            result = await search_redmine_issues("ADR", fields=["id", "description"])

        assert result[0]["id"] == 24224
        assert "match snippet" in result[0]["description"]
        assert _issues_json_calls(client) == []

    @pytest.mark.asyncio
    async def test_stock_title_prefix_is_stripped_when_not_hydrated(self):
        row = dict(
            EASY_SEARCH_ROW,
            id=42,
            title="Bug #42 (In Progress): Login fails",
            url="https://redmine.example.test/issues/42",
        )
        client = _client([row], issues=[])

        with patch("redmine_mcp_server._client.redmine", client):
            result = await search_redmine_issues("login")

        assert result[0]["id"] == 42
        assert result[0]["subject"] == "Login fails"


class TestSearchResultIssueId:
    @staticmethod
    def _row(**attrs):
        client = Redmine("https://redmine.example.test", key="unused")
        return client.issue.to_resource(dict(EASY_SEARCH_ROW, **attrs))

    @pytest.mark.parametrize(
        "url",
        [
            "https://redmine.example.test/issues/24224",
            "https://redmine.example.test/redmine/issues/24224",
            "https://redmine.example.test/issues/24224#change-7",
            "https://redmine.example.test/issues/24224?tab=history",
        ],
    )
    def test_id_is_read_from_url(self, url):
        assert _search_result_issue_id(self._row(url=url)) == 24224

    @pytest.mark.parametrize(
        "url",
        [None, "https://redmine.example.test/projects/demo", "not a url"],
    )
    def test_unreadable_url_falls_back_to_id(self, url):
        assert _search_result_issue_id(self._row(url=url)) == 300024224

    def test_mock_row_without_url_falls_back_to_id(self):
        assert _search_result_issue_id(_sparse_search_issue(7)) == 7


class TestSearchTitleSubject:
    @pytest.mark.parametrize(
        "title, expected",
        [
            ("Bug #42 (New): Login fails", "Login fails"),
            ("Change request #42 (In review): Login fails", "Login fails"),
            ("Bug #42 (Waiting (customer)): Login fails", "Login fails"),
            ("Bug #42 (New): Fix (a): b", "Fix (a): b"),
        ],
    )
    def test_stock_prefix_is_stripped(self, title, expected):
        assert _search_title_subject(title, 42) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "S2-51 Close or defer the open ADRs",
            "Bug #421 (New): Login fails",
            "Bug #7 (New): Login fails",
            "Follow-up to #42: Login fails",
        ],
    )
    def test_title_without_the_rows_own_prefix_is_kept(self, title):
        assert _search_title_subject(title, 42) == title
