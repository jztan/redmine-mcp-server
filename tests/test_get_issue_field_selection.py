"""Tests for `fields` on `get_redmine_issue` (#319).

After #315 stopped the journals echoing past descriptions, the *current*
description became the bulk of what a read costs -- 42,561 of ~54,900
characters on the ticket #313 measured, 78% of the response. A caller that
wants the status pays it in full. `fields` is the way not to.
"""

from unittest.mock import MagicMock, patch

import pytest

from redmine_mcp_server.tools.issues import get_redmine_issue

LONG_DESCRIPTION = "<p>Ein langer Text.</p>\n" * 500


def _issue():
    issue = MagicMock()
    issue.id = 43376
    issue.subject = "Cleanup-Review"
    issue.description = LONG_DESCRIPTION
    issue.journals = []
    issue.attachments = []
    status = MagicMock()
    status.id = 16
    status.name = "WORKING"
    issue.status = status
    return issue


@pytest.fixture
def mock_redmine():
    with patch("redmine_mcp_server._client.redmine") as mock:
        yield mock


@pytest.mark.unit
class TestNarrowing:
    @pytest.mark.asyncio
    async def test_naming_fields_leaves_the_rest_out(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue()

        result = await get_redmine_issue(
            issue_id=43376,
            fields=["id", "subject", "status"],
            include_journals=False,
            include_attachments=False,
            include_custom_fields=False,
        )

        assert set(result) == {"id", "subject", "status", "description_sha256"}
        assert result["id"] == 43376

    @pytest.mark.asyncio
    async def test_the_description_is_what_this_saves(self, mock_redmine):
        """The point of the issue, measured rather than asserted by name."""
        mock_redmine.issue.get.return_value = _issue()
        kwargs = dict(
            include_journals=False,
            include_attachments=False,
            include_custom_fields=False,
        )

        full = await get_redmine_issue(issue_id=43376, **kwargs)
        narrow = await get_redmine_issue(
            issue_id=43376, fields=["id", "status"], **kwargs
        )

        assert len(str(narrow)) < len(str(full)) / 50
        assert "description" not in narrow
        # But the digest survives, so the caller can still patch the text
        # it chose not to read.
        assert narrow["description_sha256"] == full["description_sha256"]

    @pytest.mark.asyncio
    async def test_omitting_fields_returns_everything(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue()

        result = await get_redmine_issue(issue_id=43376, include_journals=False)

        assert "description" in result
        assert "subject" in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize("wildcard", [["*"], ["all"]])
    async def test_the_wildcards_mean_everything(self, mock_redmine, wildcard):
        mock_redmine.issue.get.return_value = _issue()

        result = await get_redmine_issue(
            issue_id=43376, fields=wildcard, include_journals=False
        )

        assert "description" in result

    @pytest.mark.asyncio
    async def test_an_unknown_name_is_skipped_not_refused(self, mock_redmine):
        """Same forgiveness `list_redmine_issues` shows, through the same helper."""
        mock_redmine.issue.get.return_value = _issue()

        result = await get_redmine_issue(
            issue_id=43376,
            fields=["id", "nonsense"],
            include_journals=False,
            include_attachments=False,
            include_custom_fields=False,
        )

        assert "error" not in result
        assert set(result) == {"id", "description_sha256"}


@pytest.mark.unit
class TestWhatFieldsDoesNotReach:
    @pytest.mark.asyncio
    async def test_journals_and_attachments_ignore_it(self, mock_redmine):
        """Their switches stay independent -- and both default to True."""
        mock_redmine.issue.get.return_value = _issue()

        result = await get_redmine_issue(issue_id=43376, fields=["id"])

        assert "journals" in result
        assert "attachments" in result

    @pytest.mark.asyncio
    async def test_a_cheap_read_needs_the_switches_too(self, mock_redmine):
        """Three `include_*` default to True, so `fields` alone is not enough."""
        mock_redmine.issue.get.return_value = _issue()

        result = await get_redmine_issue(
            issue_id=43376,
            fields=["id", "status"],
            include_journals=False,
            include_attachments=False,
            include_custom_fields=False,
        )

        assert set(result) == {"id", "status", "description_sha256"}


@pytest.mark.unit
class TestImpliedFlags:
    @pytest.mark.asyncio
    async def test_naming_custom_fields_implies_the_flag(self, mock_redmine):
        issue = _issue()
        issue.custom_fields = []
        mock_redmine.issue.get.return_value = issue

        result = await get_redmine_issue(
            issue_id=43376,
            fields=["id", "custom_fields"],
            include_custom_fields=False,
            include_journals=False,
            include_attachments=False,
        )

        assert "custom_fields" in result

    @pytest.mark.asyncio
    async def test_the_flag_works_without_naming_it(self, mock_redmine):
        issue = _issue()
        issue.custom_fields = []
        mock_redmine.issue.get.return_value = issue

        result = await get_redmine_issue(
            issue_id=43376,
            fields=["id"],
            include_custom_fields=True,
            include_journals=False,
            include_attachments=False,
        )

        assert "custom_fields" in result
