"""
Test cases for _safe_isoformat helper.

Verifies that date fields returned as strings (by some Redmine server
configurations) are handled gracefully instead of raising AttributeError.
"""

from datetime import datetime, date
from unittest.mock import Mock

from redmine_mcp_server.redmine_handler import (
    _safe_isoformat,
    _issue_to_dict,
    _version_to_dict,
    _time_entry_to_dict,
    _journals_to_list,
    _attachments_to_list,
)


class TestSafeIsoformat:
    """Unit tests for the _safe_isoformat helper."""

    def test_none_returns_none(self):
        assert _safe_isoformat(None) is None

    def test_datetime_returns_isoformat(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        assert _safe_isoformat(dt) == "2024-01-15T10:30:00"

    def test_date_returns_isoformat(self):
        d = date(2024, 1, 15)
        assert _safe_isoformat(d) == "2024-01-15"

    def test_string_passed_through(self):
        s = "2024-01-15T10:30:00+02:00"
        assert _safe_isoformat(s) == s

    def test_empty_string_passed_through(self):
        assert _safe_isoformat("") == ""

    def test_iso_string_with_utc_offset(self):
        s = "2024-01-15T10:30:00Z"
        assert _safe_isoformat(s) == s


def _make_mock_issue(**overrides):
    """Create a minimal mock issue for testing."""
    issue = Mock()
    issue.id = overrides.get("id", 1)
    issue.subject = overrides.get("subject", "Test")
    issue.description = overrides.get("description", "Description")
    issue.project = Mock(id=1, name="Project")
    issue.status = Mock(id=1, name="New")
    issue.priority = Mock(id=2, name="Normal")
    issue.author = Mock(id=1, name="Author")
    issue.assigned_to = Mock(id=2, name="Assignee")
    issue.created_on = overrides.get("created_on", None)
    issue.updated_on = overrides.get("updated_on", None)
    return issue


class TestIssueToDict_StringDates:
    """Verify _issue_to_dict handles string date fields without crashing."""

    def test_datetime_dates(self):
        issue = _make_mock_issue(
            created_on=datetime(2024, 1, 15, 10, 30, 0),
            updated_on=datetime(2024, 1, 16, 14, 0, 0),
        )
        result = _issue_to_dict(issue)
        assert result["created_on"] == "2024-01-15T10:30:00"
        assert result["updated_on"] == "2024-01-16T14:00:00"

    def test_string_dates(self):
        issue = _make_mock_issue(
            created_on="2024-01-15T10:30:00+02:00",
            updated_on="2024-01-16T14:00:00+02:00",
        )
        result = _issue_to_dict(issue)
        assert result["created_on"] == "2024-01-15T10:30:00+02:00"
        assert result["updated_on"] == "2024-01-16T14:00:00+02:00"

    def test_none_dates(self):
        issue = _make_mock_issue(created_on=None, updated_on=None)
        result = _issue_to_dict(issue)
        assert result["created_on"] is None
        assert result["updated_on"] is None


class TestVersionToDict_StringDates:
    """Verify _version_to_dict handles string date fields without crashing."""

    def _make_mock_version(self, created_on=None, updated_on=None):
        v = Mock()
        v.id = 1
        v.name = "v1.0"
        v.description = "Release"
        v.status = "open"
        v.due_date = "2024-06-01"
        v.sharing = "none"
        v.wiki_page_title = ""
        v.project = Mock(id=1, name="Project")
        v.created_on = created_on
        v.updated_on = updated_on
        return v

    def test_string_dates(self):
        v = self._make_mock_version(
            created_on="2024-01-15T10:30:00+02:00",
            updated_on="2024-02-01T14:30:00+02:00",
        )
        result = _version_to_dict(v)
        assert result["created_on"] == "2024-01-15T10:30:00+02:00"
        assert result["updated_on"] == "2024-02-01T14:30:00+02:00"

    def test_datetime_dates(self):
        v = self._make_mock_version(
            created_on=datetime(2024, 1, 15, 10, 30, 0),
            updated_on=datetime(2024, 2, 1, 14, 30, 0),
        )
        result = _version_to_dict(v)
        assert result["created_on"] == "2024-01-15T10:30:00"
        assert result["updated_on"] == "2024-02-01T14:30:00"


class TestTimeEntryToDict_StringDates:
    """Verify _time_entry_to_dict handles string date fields without crashing."""

    def _make_mock_entry(self, created_on=None, updated_on=None):
        e = Mock()
        e.id = 1
        e.hours = 2.5
        e.comments = "Work"
        e.spent_on = "2024-03-15"
        e.user = Mock(id=5)
        e.user.name = "John"
        e.project = Mock(id=10)
        e.project.name = "Project"
        e.issue = Mock(id=123)
        e.activity = Mock(id=9)
        e.activity.name = "Development"
        e.created_on = created_on
        e.updated_on = updated_on
        return e

    def test_string_dates(self):
        e = self._make_mock_entry(
            created_on="2024-03-15T10:30:00+02:00",
            updated_on="2024-03-15T14:00:00+02:00",
        )
        result = _time_entry_to_dict(e)
        assert result["created_on"] == "2024-03-15T10:30:00+02:00"
        assert result["updated_on"] == "2024-03-15T14:00:00+02:00"


class TestJournalsList_StringDates:
    """Verify _journals_to_list handles string date fields without crashing."""

    def test_string_dates(self):
        journal = Mock()
        journal.id = 1
        journal.notes = "A comment"
        journal.user = Mock(id=1)
        journal.user.name = "Author"
        journal.created_on = "2024-01-15T10:30:00+02:00"

        issue = Mock()
        issue.journals = [journal]

        result = _journals_to_list(issue)
        assert len(result) == 1
        assert result[0]["created_on"] == "2024-01-15T10:30:00+02:00"


class TestAttachmentsList_StringDates:
    """Verify _attachments_to_list handles string date fields without crashing."""

    def test_string_dates(self):
        attachment = Mock()
        attachment.id = 1
        attachment.filename = "file.txt"
        attachment.filesize = 1024
        attachment.content_type = "text/plain"
        attachment.description = ""
        attachment.content_url = "http://example.com/file.txt"
        attachment.author = Mock(id=1)
        attachment.author.name = "Author"
        attachment.created_on = "2024-01-15T10:30:00+02:00"

        issue = Mock()
        issue.attachments = [attachment]

        result = _attachments_to_list(issue)
        assert len(result) == 1
        assert result[0]["created_on"] == "2024-01-15T10:30:00+02:00"
