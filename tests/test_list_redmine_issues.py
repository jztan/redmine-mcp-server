"""
Test cases for list_redmine_issues tool.

TDD RED phase: Tests written before implementation.
This tool provides a general-purpose issue listing with arbitrary filters,
replacing the hardcoded assigned_to_id='me' in list_my_redmine_issues.
"""

import pytest
from unittest.mock import Mock, patch
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    list_redmine_issues,
    list_my_redmine_issues,
)


class TestListRedmineIssues:
    """Test cases for list_redmine_issues tool."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_issue(self, issue_id=1, subject="Test Issue", project_id=1):
        """Create a single mock issue."""
        mock_issue = Mock()
        mock_issue.id = issue_id
        mock_issue.subject = subject
        mock_issue.description = f"Description for issue {issue_id}"

        mock_issue.project = Mock(id=project_id, name="Test Project")
        mock_issue.status = Mock(id=1, name="New")
        mock_issue.priority = Mock(id=2, name="Normal")
        mock_issue.author = Mock(id=10, name="John Doe")
        mock_issue.assigned_to = Mock(id=20, name="Jane Smith")
        mock_issue.created_on = None
        mock_issue.updated_on = None

        return mock_issue

    def create_mock_issues(self, count, project_id=1):
        """Create a list of mock issues."""
        return [
            self.create_mock_issue(
                issue_id=i, subject=f"Issue {i}", project_id=project_id
            )
            for i in range(1, count + 1)
        ]

    # --- Basic functionality ---

    @pytest.mark.asyncio
    async def test_list_issues_by_project_id(self, mock_redmine):
        """Test listing all issues in a project by project_id."""
        mock_issues = self.create_mock_issues(5)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(project_id=1)

        assert isinstance(result, list)
        assert len(result) == 5
        assert result[0]["id"] == 1
        # Verify project_id was passed and assigned_to_id was NOT hardcoded
        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("project_id") == 1
        assert "assigned_to_id" not in call_kwargs

    @pytest.mark.asyncio
    async def test_list_issues_by_string_project_identifier(self, mock_redmine):
        """Test listing issues using a string project identifier."""
        mock_issues = self.create_mock_issues(3)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(project_id="my-project")

        assert isinstance(result, list)
        assert len(result) == 3
        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("project_id") == "my-project"

    @pytest.mark.asyncio
    async def test_list_issues_no_filters(self, mock_redmine):
        """Test listing issues without any filters (all issues)."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues()

        assert isinstance(result, list)
        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_list_issues_with_status_filter(self, mock_redmine):
        """Test listing issues filtered by status_id."""
        mock_issues = self.create_mock_issues(3)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, status_id=2)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("status_id") == 2
        assert call_kwargs.get("project_id") == 1

    @pytest.mark.asyncio
    async def test_list_issues_with_assigned_to_filter(self, mock_redmine):
        """Test listing issues filtered by assigned_to_id."""
        mock_issues = self.create_mock_issues(3)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, assigned_to_id="me")

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("assigned_to_id") == "me"
        assert call_kwargs.get("project_id") == 1

    @pytest.mark.asyncio
    async def test_list_issues_with_tracker_filter(self, mock_redmine):
        """Test listing issues filtered by tracker_id."""
        mock_issues = self.create_mock_issues(2)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, tracker_id=3)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("tracker_id") == 3

    @pytest.mark.asyncio
    async def test_list_issues_with_sort(self, mock_redmine):
        """Test listing issues with sort parameter."""
        mock_issues = self.create_mock_issues(5)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, sort="updated_on:desc")

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("sort") == "updated_on:desc"

    # --- Combined filters ---

    @pytest.mark.asyncio
    async def test_list_issues_combined_project_status_assignee(self, mock_redmine):
        """Test combining project_id, status_id, and assigned_to_id."""
        mock_issues = self.create_mock_issues(3)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(
            project_id=1, status_id=2, assigned_to_id="me"
        )

        assert isinstance(result, list)
        assert len(result) == 3
        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("project_id") == 1
        assert call_kwargs.get("status_id") == 2
        assert call_kwargs.get("assigned_to_id") == "me"

    @pytest.mark.asyncio
    async def test_list_issues_combined_all_filters_with_pagination(self, mock_redmine):
        """Test all filters combined with pagination and sort."""
        mock_issues = self.create_mock_issues(5)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(
            project_id=1,
            status_id=1,
            tracker_id=2,
            assigned_to_id=10,
            priority_id=3,
            sort="updated_on:desc",
            limit=5,
            offset=10,
        )

        assert isinstance(result, list)
        assert len(result) == 5
        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("project_id") == 1
        assert call_kwargs.get("status_id") == 1
        assert call_kwargs.get("tracker_id") == 2
        assert call_kwargs.get("assigned_to_id") == 10
        assert call_kwargs.get("priority_id") == 3
        assert call_kwargs.get("sort") == "updated_on:desc"
        assert call_kwargs["limit"] == 5
        assert call_kwargs["offset"] == 10

    @pytest.mark.asyncio
    async def test_list_issues_combined_filters_with_fields(self, mock_redmine):
        """Test combined filters with field selection."""
        mock_issues = self.create_mock_issues(3)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(
            project_id=1,
            status_id=1,
            fields=["id", "subject", "status"],
        )

        assert isinstance(result, list)
        assert len(result) == 3
        for issue in result:
            assert "id" in issue
            assert "subject" in issue
            assert "status" in issue
            assert "description" not in issue
            assert "author" not in issue

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("project_id") == 1
        assert call_kwargs.get("status_id") == 1

    # --- Pagination ---

    @pytest.mark.asyncio
    async def test_default_pagination_limit_25(self, mock_redmine):
        """Test that default limit is 25."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs["limit"] == 25
        assert call_kwargs["offset"] == 0

    @pytest.mark.asyncio
    async def test_custom_limit_and_offset(self, mock_redmine):
        """Test custom limit and offset."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, limit=10, offset=50)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 50

    @pytest.mark.asyncio
    async def test_limit_capped_at_1000(self, mock_redmine):
        """Test that limit > 1000 is capped to 1000."""
        mock_issues = self.create_mock_issues(5)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, limit=5000)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs["limit"] <= 1000

    @pytest.mark.asyncio
    async def test_negative_limit_returns_empty(self, mock_redmine):
        """Test that negative limit returns empty result."""
        result = await list_redmine_issues(project_id=1, limit=-1)

        assert result == []
        mock_redmine.issue.filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_limit_returns_empty(self, mock_redmine):
        """Test that zero limit returns empty result."""
        result = await list_redmine_issues(project_id=1, limit=0)

        assert result == []
        mock_redmine.issue.filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_offset_reset_to_zero(self, mock_redmine):
        """Test that negative offset is reset to 0."""
        mock_issues = self.create_mock_issues(5)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, offset=-10)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs["offset"] == 0

    @pytest.mark.asyncio
    async def test_string_limit_coerced_to_int(self, mock_redmine):
        """Test that string limit is coerced to int."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, limit="10")

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs["limit"] == 10
        assert isinstance(call_kwargs["limit"], int)

    @pytest.mark.asyncio
    async def test_invalid_limit_falls_back_to_default(self, mock_redmine):
        """Test that invalid limit type falls back to default 25."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.filter.return_value = mock_issues

        await list_redmine_issues(project_id=1, limit="invalid")

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs["limit"] == 25

    # --- Pagination metadata ---

    @pytest.mark.asyncio
    async def test_pagination_metadata_structure(self, mock_redmine):
        """Test pagination metadata when include_pagination_info=True."""
        mock_issues = self.create_mock_issues(25)

        # First call returns issues, second call for total count
        first_call = Mock()
        first_call.__iter__ = Mock(return_value=iter(mock_issues))
        second_call = Mock()
        second_call.__iter__ = Mock(return_value=iter([]))
        second_call.total_count = 100

        mock_redmine.issue.filter.side_effect = [first_call, second_call]

        result = await list_redmine_issues(
            project_id=1, limit=25, offset=0, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result

        pagination = result["pagination"]
        assert pagination["limit"] == 25
        assert pagination["offset"] == 0
        assert pagination["count"] == 25
        assert pagination["has_next"] is True
        assert pagination["has_previous"] is False
        assert pagination["next_offset"] == 25
        assert pagination["previous_offset"] is None
        assert pagination["total"] == 100

    @pytest.mark.asyncio
    async def test_pagination_has_previous_true(self, mock_redmine):
        """Test has_previous=True when offset > 0."""
        mock_issues = self.create_mock_issues(10)

        first_call = Mock()
        first_call.__iter__ = Mock(return_value=iter(mock_issues))
        second_call = Mock()
        second_call.__iter__ = Mock(return_value=iter([]))
        second_call.total_count = 50

        mock_redmine.issue.filter.side_effect = [first_call, second_call]

        result = await list_redmine_issues(
            project_id=1, limit=10, offset=20, include_pagination_info=True
        )

        pagination = result["pagination"]
        assert pagination["has_previous"] is True
        assert pagination["previous_offset"] == 10

    @pytest.mark.asyncio
    async def test_pagination_has_next_false_partial_page(self, mock_redmine):
        """Test has_next=False when fewer results than limit."""
        mock_issues = self.create_mock_issues(5)

        first_call = Mock()
        first_call.__iter__ = Mock(return_value=iter(mock_issues))
        second_call = Mock()
        second_call.__iter__ = Mock(return_value=iter([]))
        second_call.total_count = 5

        mock_redmine.issue.filter.side_effect = [first_call, second_call]

        result = await list_redmine_issues(
            project_id=1, limit=25, include_pagination_info=True
        )

        pagination = result["pagination"]
        assert pagination["has_next"] is False
        assert pagination["next_offset"] is None

    @pytest.mark.asyncio
    async def test_pagination_zero_limit_with_info(self, mock_redmine):
        """Test pagination info with zero limit."""
        result = await list_redmine_issues(
            project_id=1, limit=0, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert result["issues"] == []
        assert result["pagination"]["limit"] == 0
        assert result["pagination"]["has_next"] is False

    # --- Field selection ---

    @pytest.mark.asyncio
    async def test_field_selection(self, mock_redmine):
        """Test field selection with fields parameter."""
        mock_issues = self.create_mock_issues(3)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(
            project_id=1, fields=["id", "subject", "status"]
        )

        assert isinstance(result, list)
        assert len(result) == 3
        # Should only contain selected fields
        for issue in result:
            assert "id" in issue
            assert "subject" in issue
            assert "status" in issue
            assert "description" not in issue
            assert "author" not in issue

    @pytest.mark.asyncio
    async def test_field_selection_all(self, mock_redmine):
        """Test fields=['*'] returns all fields."""
        mock_issues = self.create_mock_issues(1)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(project_id=1, fields=["*"])

        assert "id" in result[0]
        assert "subject" in result[0]
        assert "description" in result[0]
        assert "project" in result[0]
        assert "status" in result[0]

    # --- Error handling ---

    @pytest.mark.asyncio
    async def test_no_client_returns_error(self):
        """Test error when Redmine client is not initialized."""
        with patch("redmine_mcp_server.redmine_handler.redmine", None):
            result = await list_redmine_issues(project_id=1)

            assert isinstance(result, list)
            assert result[0]["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    async def test_api_error_returns_error(self, mock_redmine):
        """Test error handling when API call fails."""
        mock_redmine.issue.filter.side_effect = Exception("Connection refused")

        result = await list_redmine_issues(project_id=1)

        assert isinstance(result, list)
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_resource_not_found_error(self, mock_redmine):
        """Test error handling for ResourceNotFoundError."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue.filter.side_effect = ResourceNotFoundError()

        result = await list_redmine_issues(project_id=999)

        assert isinstance(result, list)
        assert "error" in result[0]

    # --- MCP parameter unwrapping ---

    @pytest.mark.asyncio
    async def test_mcp_parameter_unwrapping(self, mock_redmine):
        """Test MCP wrapping parameters in 'filters' key."""
        mock_issues = self.create_mock_issues(5)
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_redmine_issues(
            filters={"project_id": 1, "limit": 5, "offset": 10}
        )

        assert isinstance(result, list)
        assert len(result) == 5
        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("project_id") == 1


class TestListMyRedmineIssuesDelegation:
    """Test that list_my_redmine_issues delegates to list_redmine_issues."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_issue(self, issue_id=1):
        """Create a single mock issue."""
        mock_issue = Mock()
        mock_issue.id = issue_id
        mock_issue.subject = f"Issue {issue_id}"
        mock_issue.description = f"Description for issue {issue_id}"
        mock_issue.project = Mock(id=1, name="Test Project")
        mock_issue.status = Mock(id=1, name="New")
        mock_issue.priority = Mock(id=2, name="Normal")
        mock_issue.author = Mock(id=10, name="John Doe")
        mock_issue.assigned_to = Mock(id=20, name="Jane Smith")
        mock_issue.created_on = None
        mock_issue.updated_on = None
        return mock_issue

    @pytest.mark.asyncio
    async def test_delegates_with_assigned_to_me(self, mock_redmine):
        """Test that list_my_redmine_issues passes assigned_to_id='me'."""
        mock_issues = [self.create_mock_issue(1)]
        mock_redmine.issue.filter.return_value = mock_issues

        await list_my_redmine_issues()

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("assigned_to_id") == "me"

    @pytest.mark.asyncio
    async def test_passes_through_filters(self, mock_redmine):
        """Test that additional filters are passed through."""
        mock_issues = [self.create_mock_issue(1)]
        mock_redmine.issue.filter.return_value = mock_issues

        await list_my_redmine_issues(project_id=5, status_id=2)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("assigned_to_id") == "me"
        assert call_kwargs.get("project_id") == 5

    @pytest.mark.asyncio
    async def test_passes_through_pagination(self, mock_redmine):
        """Test that pagination parameters are passed through."""
        mock_issues = [self.create_mock_issue(1)]
        mock_redmine.issue.filter.return_value = mock_issues

        await list_my_redmine_issues(limit=10, offset=20)

        call_kwargs = mock_redmine.issue.filter.call_args[1]
        assert call_kwargs.get("assigned_to_id") == "me"
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 20

    @pytest.mark.asyncio
    async def test_no_client_returns_error(self):
        """Test backward-compatible error when client is None."""
        with patch("redmine_mcp_server.redmine_handler.redmine", None):
            result = await list_my_redmine_issues()

            assert isinstance(result, list)
            assert result[0]["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    async def test_returns_list_by_default(self, mock_redmine):
        """Test backward-compatible list return type."""
        mock_issues = [self.create_mock_issue(1)]
        mock_redmine.issue.filter.return_value = mock_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_dict_with_pagination_info(self, mock_redmine):
        """Test dict return type with pagination info."""
        mock_issues = [self.create_mock_issue(1)]

        first_call = Mock()
        first_call.__iter__ = Mock(return_value=iter(mock_issues))
        second_call = Mock()
        second_call.__iter__ = Mock(return_value=iter([]))
        second_call.total_count = 1

        mock_redmine.issue.filter.side_effect = [first_call, second_call]

        result = await list_my_redmine_issues(
            limit=25, offset=0, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result
