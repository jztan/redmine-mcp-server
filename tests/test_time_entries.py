"""
Test cases for time entry tools.

Tests for list_time_entries, create_time_entry, and update_time_entry tools.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from redmine_mcp_server.redmine_handler import (
    list_time_entries,
    create_time_entry,
    update_time_entry,
    _time_entry_to_dict,
)


def make_mock_with_name(id_val, name_val):
    """Helper to create a Mock with a name attribute (not Mock's internal name)."""
    m = Mock()
    m.id = id_val
    m.name = name_val
    return m


class TestTimeEntryToDict:
    """Test cases for _time_entry_to_dict helper function."""

    def test_complete_time_entry(self):
        """Test converting a complete time entry to dict."""
        mock_entry = Mock()
        mock_entry.id = 1
        mock_entry.hours = 2.5
        mock_entry.comments = "Bug fix work"
        mock_entry.spent_on = "2024-03-15"
        mock_entry.user = make_mock_with_name(5, "John Doe")
        mock_entry.project = make_mock_with_name(10, "Test Project")
        mock_entry.issue = Mock(id=123)
        mock_entry.activity = make_mock_with_name(9, "Development")
        mock_entry.created_on = datetime(2024, 3, 15, 10, 30, 0)
        mock_entry.updated_on = datetime(2024, 3, 15, 14, 0, 0)

        result = _time_entry_to_dict(mock_entry)

        assert result["id"] == 1
        assert result["hours"] == 2.5
        assert result["comments"] == "Bug fix work"
        assert result["spent_on"] == "2024-03-15"
        assert result["user"] == {"id": 5, "name": "John Doe"}
        assert result["project"] == {"id": 10, "name": "Test Project"}
        assert result["issue"] == {"id": 123}
        assert result["activity"] == {"id": 9, "name": "Development"}
        assert result["created_on"] is not None
        assert result["updated_on"] is not None

    def test_time_entry_without_issue(self):
        """Test time entry logged against project without issue."""
        mock_entry = Mock()
        mock_entry.id = 2
        mock_entry.hours = 1.0
        mock_entry.comments = "Project meeting"
        mock_entry.spent_on = "2024-03-15"
        mock_entry.user = make_mock_with_name(5, "John Doe")
        mock_entry.project = make_mock_with_name(10, "Test Project")
        mock_entry.issue = None
        mock_entry.activity = make_mock_with_name(10, "Meeting")
        mock_entry.created_on = None
        mock_entry.updated_on = None

        result = _time_entry_to_dict(mock_entry)

        assert result["id"] == 2
        assert result["issue"] is None
        assert result["project"] == {"id": 10, "name": "Test Project"}

    def test_time_entry_minimal(self):
        """Test time entry with minimal data."""
        mock_entry = Mock()
        mock_entry.id = 3
        mock_entry.hours = 0.5
        mock_entry.comments = ""
        mock_entry.spent_on = None
        mock_entry.user = None
        mock_entry.project = None
        mock_entry.issue = None
        mock_entry.activity = None
        mock_entry.created_on = None
        mock_entry.updated_on = None

        result = _time_entry_to_dict(mock_entry)

        assert result["id"] == 3
        assert result["hours"] == 0.5
        assert result["comments"] == ""
        assert result["spent_on"] is None
        assert result["user"] is None
        assert result["project"] is None
        assert result["issue"] is None
        assert result["activity"] is None


class TestListTimeEntries:
    """Test cases for list_time_entries tool."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_time_entry(
        self, entry_id=1, hours=2.0, project_id=10, issue_id=None
    ):
        """Create a single mock time entry."""
        mock_entry = Mock()
        mock_entry.id = entry_id
        mock_entry.hours = hours
        mock_entry.comments = f"Work on entry {entry_id}"
        mock_entry.spent_on = "2024-03-15"
        mock_entry.user = make_mock_with_name(5, "John Doe")
        mock_entry.project = make_mock_with_name(project_id, "Test Project")
        mock_entry.issue = Mock(id=issue_id) if issue_id else None
        mock_entry.activity = make_mock_with_name(9, "Development")
        mock_entry.created_on = datetime(2024, 3, 15, 10, 0, 0)
        mock_entry.updated_on = datetime(2024, 3, 15, 10, 0, 0)
        return mock_entry

    @pytest.mark.asyncio
    async def test_list_all_time_entries(self, mock_redmine):
        """Test listing time entries without filters."""
        mock_entries = [
            self.create_mock_time_entry(1, 2.0),
            self.create_mock_time_entry(2, 1.5),
        ]
        mock_redmine.time_entry.filter.return_value = mock_entries

        result = await list_time_entries()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["hours"] == 2.0
        assert result[1]["hours"] == 1.5

    @pytest.mark.asyncio
    async def test_list_time_entries_by_project(self, mock_redmine):
        """Test filtering time entries by project."""
        mock_entries = [self.create_mock_time_entry(1, 2.0, project_id=10)]
        mock_redmine.time_entry.filter.return_value = mock_entries

        result = await list_time_entries(project_id=10)

        assert len(result) == 1
        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["project_id"] == 10

    @pytest.mark.asyncio
    async def test_list_time_entries_by_project_identifier(self, mock_redmine):
        """Test filtering by string project identifier."""
        mock_entries = [self.create_mock_time_entry(1, 2.0)]
        mock_redmine.time_entry.filter.return_value = mock_entries

        await list_time_entries(project_id="my-project")

        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["project_id"] == "my-project"

    @pytest.mark.asyncio
    async def test_list_time_entries_by_issue(self, mock_redmine):
        """Test filtering time entries by issue."""
        mock_entries = [self.create_mock_time_entry(1, 2.0, issue_id=123)]
        mock_redmine.time_entry.filter.return_value = mock_entries

        result = await list_time_entries(issue_id=123)

        assert len(result) == 1
        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["issue_id"] == 123

    @pytest.mark.asyncio
    async def test_list_time_entries_by_user(self, mock_redmine):
        """Test filtering time entries by user."""
        mock_entries = [self.create_mock_time_entry(1, 2.0)]
        mock_redmine.time_entry.filter.return_value = mock_entries

        await list_time_entries(user_id=5)

        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["user_id"] == 5

    @pytest.mark.asyncio
    async def test_list_time_entries_by_current_user(self, mock_redmine):
        """Test filtering time entries by 'me' for current user."""
        mock_entries = [self.create_mock_time_entry(1, 2.0)]
        mock_redmine.time_entry.filter.return_value = mock_entries

        await list_time_entries(user_id="me")

        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["user_id"] == "me"

    @pytest.mark.asyncio
    async def test_list_time_entries_date_range(self, mock_redmine):
        """Test filtering time entries by date range."""
        mock_entries = [self.create_mock_time_entry(1, 2.0)]
        mock_redmine.time_entry.filter.return_value = mock_entries

        await list_time_entries(from_date="2024-01-01", to_date="2024-03-31")

        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["from_date"] == "2024-01-01"
        assert call_kwargs["to_date"] == "2024-03-31"

    @pytest.mark.asyncio
    async def test_list_time_entries_pagination(self, mock_redmine):
        """Test pagination with limit and offset."""
        mock_entries = [self.create_mock_time_entry(1, 2.0)]
        mock_redmine.time_entry.filter.return_value = mock_entries

        await list_time_entries(limit=10, offset=20)

        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 20

    @pytest.mark.asyncio
    async def test_list_time_entries_limit_cap(self, mock_redmine):
        """Test that limit is capped at 100."""
        mock_entries = []
        mock_redmine.time_entry.filter.return_value = mock_entries

        await list_time_entries(limit=500)

        call_kwargs = mock_redmine.time_entry.filter.call_args[1]
        assert call_kwargs["limit"] == 100

    @pytest.mark.asyncio
    async def test_list_time_entries_redmine_not_initialized(self):
        """Test error when Redmine client is not initialized."""
        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            side_effect=RuntimeError("No Redmine authentication available"),
        ):
            result = await list_time_entries()

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_list_time_entries_empty_result(self, mock_redmine):
        """Test listing when no time entries exist."""
        mock_redmine.time_entry.filter.return_value = []

        result = await list_time_entries(project_id=10)

        assert isinstance(result, list)
        assert len(result) == 0


class TestCreateTimeEntry:
    """Test cases for create_time_entry tool."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_time_entry(self, entry_id=1, hours=2.0, issue_id=None):
        """Create a mock time entry for create response."""
        mock_entry = Mock()
        mock_entry.id = entry_id
        mock_entry.hours = hours
        mock_entry.comments = "Test work"
        mock_entry.spent_on = "2024-03-15"
        mock_entry.user = make_mock_with_name(5, "John Doe")
        mock_entry.project = make_mock_with_name(10, "Test Project")
        mock_entry.issue = Mock(id=issue_id) if issue_id else None
        mock_entry.activity = make_mock_with_name(9, "Development")
        mock_entry.created_on = datetime(2024, 3, 15, 10, 0, 0)
        mock_entry.updated_on = datetime(2024, 3, 15, 10, 0, 0)
        return mock_entry

    @pytest.mark.asyncio
    async def test_create_time_entry_with_issue(self, mock_redmine):
        """Test creating a time entry against an issue."""
        mock_entry = self.create_mock_time_entry(1, 2.5, issue_id=123)
        mock_redmine.time_entry.create.return_value = mock_entry

        result = await create_time_entry(hours=2.5, issue_id=123, comments="Bug fix")

        assert result["id"] == 1
        assert result["hours"] == 2.5
        call_kwargs = mock_redmine.time_entry.create.call_args[1]
        assert call_kwargs["hours"] == 2.5
        assert call_kwargs["issue_id"] == 123
        assert call_kwargs["comments"] == "Bug fix"

    @pytest.mark.asyncio
    async def test_create_time_entry_with_project(self, mock_redmine):
        """Test creating a time entry against a project."""
        mock_entry = self.create_mock_time_entry(1, 1.0)
        mock_redmine.time_entry.create.return_value = mock_entry

        result = await create_time_entry(
            hours=1.0, project_id=10, comments="Project meeting"
        )

        assert result["id"] == 1
        call_kwargs = mock_redmine.time_entry.create.call_args[1]
        assert call_kwargs["project_id"] == 10

    @pytest.mark.asyncio
    async def test_create_time_entry_with_project_identifier(self, mock_redmine):
        """Test creating time entry using string project identifier."""
        mock_entry = self.create_mock_time_entry(1, 1.0)
        mock_redmine.time_entry.create.return_value = mock_entry

        await create_time_entry(hours=1.0, project_id="my-project", comments="Work")

        call_kwargs = mock_redmine.time_entry.create.call_args[1]
        assert call_kwargs["project_id"] == "my-project"

    @pytest.mark.asyncio
    async def test_create_time_entry_with_activity(self, mock_redmine):
        """Test creating time entry with specific activity."""
        mock_entry = self.create_mock_time_entry(1, 2.0)
        mock_redmine.time_entry.create.return_value = mock_entry

        await create_time_entry(hours=2.0, issue_id=123, activity_id=9)

        call_kwargs = mock_redmine.time_entry.create.call_args[1]
        assert call_kwargs["activity_id"] == 9

    @pytest.mark.asyncio
    async def test_create_time_entry_with_spent_on(self, mock_redmine):
        """Test creating time entry with specific date."""
        mock_entry = self.create_mock_time_entry(1, 2.0)
        mock_redmine.time_entry.create.return_value = mock_entry

        await create_time_entry(hours=2.0, issue_id=123, spent_on="2024-03-15")

        call_kwargs = mock_redmine.time_entry.create.call_args[1]
        assert call_kwargs["spent_on"] == "2024-03-15"

    @pytest.mark.asyncio
    async def test_create_time_entry_missing_project_and_issue(self, mock_redmine):
        """Test error when neither project_id nor issue_id provided."""
        result = await create_time_entry(hours=2.0)

        assert "error" in result
        assert "project_id or issue_id" in result["error"]

    @pytest.mark.asyncio
    async def test_create_time_entry_zero_hours(self, mock_redmine):
        """Test error when hours is zero."""
        result = await create_time_entry(hours=0, issue_id=123)

        assert "error" in result
        assert "positive" in result["error"]

    @pytest.mark.asyncio
    async def test_create_time_entry_negative_hours(self, mock_redmine):
        """Test error when hours is negative."""
        result = await create_time_entry(hours=-1.0, issue_id=123)

        assert "error" in result
        assert "positive" in result["error"]

    @pytest.mark.asyncio
    async def test_create_time_entry_redmine_not_initialized(self):
        """Test error when Redmine client is not initialized."""
        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            side_effect=RuntimeError("No Redmine authentication available"),
        ):
            result = await create_time_entry(hours=2.0, issue_id=123)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_time_entry_issue_not_found(self, mock_redmine):
        """Test error when issue is not found."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.time_entry.create.side_effect = ResourceNotFoundError()

        result = await create_time_entry(hours=2.0, issue_id=9999)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_time_entry_decimal_hours(self, mock_redmine):
        """Test creating time entry with decimal hours."""
        mock_entry = self.create_mock_time_entry(1, 0.25)
        mock_redmine.time_entry.create.return_value = mock_entry

        result = await create_time_entry(hours=0.25, issue_id=123)

        assert result["id"] == 1
        call_kwargs = mock_redmine.time_entry.create.call_args[1]
        assert call_kwargs["hours"] == 0.25


class TestUpdateTimeEntry:
    """Test cases for update_time_entry tool."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_time_entry(self, entry_id=1, hours=2.0):
        """Create a mock time entry for update response."""
        mock_entry = Mock()
        mock_entry.id = entry_id
        mock_entry.hours = hours
        mock_entry.comments = "Updated work"
        mock_entry.spent_on = "2024-03-15"
        mock_entry.user = make_mock_with_name(5, "John Doe")
        mock_entry.project = make_mock_with_name(10, "Test Project")
        mock_entry.issue = Mock(id=123)
        mock_entry.activity = make_mock_with_name(9, "Development")
        mock_entry.created_on = datetime(2024, 3, 15, 10, 0, 0)
        mock_entry.updated_on = datetime(2024, 3, 15, 14, 0, 0)
        return mock_entry

    @pytest.mark.asyncio
    async def test_update_time_entry_hours(self, mock_redmine):
        """Test updating time entry hours."""
        mock_entry = self.create_mock_time_entry(1, 3.0)
        mock_redmine.time_entry.get.return_value = mock_entry

        result = await update_time_entry(time_entry_id=1, hours=3.0)

        assert result["id"] == 1
        assert result["hours"] == 3.0
        mock_redmine.time_entry.update.assert_called_once()
        call_kwargs = mock_redmine.time_entry.update.call_args[1]
        assert call_kwargs["hours"] == 3.0

    @pytest.mark.asyncio
    async def test_update_time_entry_comments(self, mock_redmine):
        """Test updating time entry comments."""
        mock_entry = self.create_mock_time_entry(1, 2.0)
        mock_redmine.time_entry.get.return_value = mock_entry

        await update_time_entry(time_entry_id=1, comments="New description")

        call_kwargs = mock_redmine.time_entry.update.call_args[1]
        assert call_kwargs["comments"] == "New description"

    @pytest.mark.asyncio
    async def test_update_time_entry_activity(self, mock_redmine):
        """Test updating time entry activity."""
        mock_entry = self.create_mock_time_entry(1, 2.0)
        mock_redmine.time_entry.get.return_value = mock_entry

        await update_time_entry(time_entry_id=1, activity_id=10)

        call_kwargs = mock_redmine.time_entry.update.call_args[1]
        assert call_kwargs["activity_id"] == 10

    @pytest.mark.asyncio
    async def test_update_time_entry_spent_on(self, mock_redmine):
        """Test updating time entry date."""
        mock_entry = self.create_mock_time_entry(1, 2.0)
        mock_redmine.time_entry.get.return_value = mock_entry

        await update_time_entry(time_entry_id=1, spent_on="2024-03-20")

        call_kwargs = mock_redmine.time_entry.update.call_args[1]
        assert call_kwargs["spent_on"] == "2024-03-20"

    @pytest.mark.asyncio
    async def test_update_time_entry_multiple_fields(self, mock_redmine):
        """Test updating multiple fields at once."""
        mock_entry = self.create_mock_time_entry(1, 4.0)
        mock_redmine.time_entry.get.return_value = mock_entry

        await update_time_entry(
            time_entry_id=1,
            hours=4.0,
            comments="Extended work",
            spent_on="2024-03-20",
        )

        call_kwargs = mock_redmine.time_entry.update.call_args[1]
        assert call_kwargs["hours"] == 4.0
        assert call_kwargs["comments"] == "Extended work"
        assert call_kwargs["spent_on"] == "2024-03-20"

    @pytest.mark.asyncio
    async def test_update_time_entry_no_fields(self, mock_redmine):
        """Test error when no fields provided for update."""
        result = await update_time_entry(time_entry_id=1)

        assert "error" in result
        assert "No fields" in result["error"]

    @pytest.mark.asyncio
    async def test_update_time_entry_zero_hours(self, mock_redmine):
        """Test error when hours set to zero."""
        result = await update_time_entry(time_entry_id=1, hours=0)

        assert "error" in result
        assert "positive" in result["error"]

    @pytest.mark.asyncio
    async def test_update_time_entry_negative_hours(self, mock_redmine):
        """Test error when hours set to negative."""
        result = await update_time_entry(time_entry_id=1, hours=-1.0)

        assert "error" in result
        assert "positive" in result["error"]

    @pytest.mark.asyncio
    async def test_update_time_entry_not_found(self, mock_redmine):
        """Test error when time entry not found."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.time_entry.update.side_effect = ResourceNotFoundError()

        result = await update_time_entry(time_entry_id=9999, hours=2.0)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_update_time_entry_redmine_not_initialized(self):
        """Test error when Redmine client is not initialized."""
        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            side_effect=RuntimeError("No Redmine authentication available"),
        ):
            result = await update_time_entry(time_entry_id=1, hours=2.0)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_update_time_entry_forbidden(self, mock_redmine):
        """Test error when user lacks permission to update."""
        from redminelib.exceptions import ForbiddenError

        mock_redmine.time_entry.update.side_effect = ForbiddenError()

        result = await update_time_entry(time_entry_id=1, hours=2.0)

        assert "error" in result
        assert "Access denied" in result["error"]
