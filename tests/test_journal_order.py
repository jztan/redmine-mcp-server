"""Tests for `journal_order` and the sort that makes it mean anything (#318).

Redmine does not always send journals oldest first: `IssuesController#show`
reverses them for an API user who has "display comments in reverse
chronological order" set. So which journals a `journal_limit` returned used
to depend on the account behind the key. These tests pin that the server
sorts by id first, and that `desc` answers "the last few comments" without
fetching everything to learn `total`.
"""

from unittest.mock import MagicMock, patch

import pytest

from redmine_mcp_server.tools.issues import get_redmine_issue


def _journal(journal_id, note):
    journal = MagicMock()
    journal.id = journal_id
    journal.notes = note
    journal.details = []
    journal.user = None
    journal.created_on = None
    journal.private_notes = False
    return journal


def _issue(journals):
    issue = MagicMock()
    issue.id = 7
    issue.description = "beschreibung"
    issue.journals = journals
    issue.attachments = []
    issue.raw.return_value = {"journals": journals, "attachments": []}
    return issue


ASCENDING = [_journal(100 + n, f"note {n}") for n in range(6)]


@pytest.fixture
def mock_redmine():
    with patch("redmine_mcp_server._client.redmine") as mock:
        yield mock


def _ids(result):
    return [j["id"] for j in result["journals"]]


@pytest.mark.unit
class TestSortingBeatsRedminesOrder:
    @pytest.mark.asyncio
    async def test_a_reversed_journal_list_is_sorted_back(self, mock_redmine):
        """What an account with reverse-chronological display receives."""
        mock_redmine.issue.get.return_value = _issue(list(reversed(ASCENDING)))

        result = await get_redmine_issue(issue_id=7, journal_limit=3)

        assert _ids(result) == [100, 101, 102]

    @pytest.mark.asyncio
    async def test_the_two_orders_agree_whatever_redmine_sent(self, mock_redmine):
        forward, backward = [], []
        for arrangement, sink in ((ASCENDING, forward), (ASCENDING[::-1], backward)):
            mock_redmine.issue.get.return_value = _issue(list(arrangement))
            sink.append(_ids(await get_redmine_issue(issue_id=7, journal_limit=2)))
            mock_redmine.issue.get.return_value = _issue(list(arrangement))
            sink.append(
                _ids(
                    await get_redmine_issue(
                        issue_id=7, journal_limit=2, journal_order="desc"
                    )
                )
            )

        assert forward == backward

    @pytest.mark.asyncio
    async def test_sorting_applies_without_a_limit_too(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(reversed(ASCENDING)))

        result = await get_redmine_issue(issue_id=7)

        assert _ids(result) == [100, 101, 102, 103, 104, 105]
        assert "journal_pagination" not in result


@pytest.mark.unit
class TestOrdering:
    @pytest.mark.asyncio
    async def test_desc_answers_the_last_few_comments(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(ASCENDING))

        result = await get_redmine_issue(
            issue_id=7, journal_limit=3, journal_order="desc"
        )

        assert _ids(result) == [105, 104, 103]

    @pytest.mark.asyncio
    async def test_asc_is_the_default_and_unchanged(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(ASCENDING))

        result = await get_redmine_issue(issue_id=7, journal_limit=3)

        assert _ids(result) == [100, 101, 102]

    @pytest.mark.asyncio
    async def test_offset_counts_from_the_selected_end(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(ASCENDING))

        result = await get_redmine_issue(
            issue_id=7, journal_limit=2, journal_offset=2, journal_order="desc"
        )

        assert _ids(result) == [103, 102]

    @pytest.mark.asyncio
    async def test_desc_without_a_limit_reverses_the_whole_list(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(ASCENDING))

        result = await get_redmine_issue(issue_id=7, journal_order="desc")

        assert _ids(result) == [105, 104, 103, 102, 101, 100]


@pytest.mark.unit
class TestPaginationMetadata:
    @pytest.mark.asyncio
    async def test_the_order_is_echoed_back(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(ASCENDING))

        result = await get_redmine_issue(
            issue_id=7, journal_limit=2, journal_order="desc"
        )

        assert result["journal_pagination"]["order"] == "desc"

    @pytest.mark.asyncio
    async def test_the_default_order_is_named_too(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(ASCENDING))

        result = await get_redmine_issue(issue_id=7, journal_limit=2)

        assert result["journal_pagination"]["order"] == "asc"

    @pytest.mark.asyncio
    async def test_the_other_counters_keep_their_meaning(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(list(ASCENDING))

        result = await get_redmine_issue(
            issue_id=7, journal_limit=2, journal_offset=4, journal_order="desc"
        )

        pagination = result["journal_pagination"]
        assert pagination["total"] == 6
        assert pagination["offset"] == 4
        assert pagination["count"] == 2
        assert pagination["has_more"] is False
