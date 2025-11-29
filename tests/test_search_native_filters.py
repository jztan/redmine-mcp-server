"""
Test cases for native filters in search_redmine_issues.

This module contains tests for the native Redmine Search API filters
(scope and open_issues) added to the search_redmine_issues tool.
"""

import pytest
from unittest.mock import Mock, patch
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import search_redmine_issues  # noqa: E402


class TestSearchNativeFilters:
    """Test cases for native filters in search_redmine_issues."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_issue(self, issue_id=1):
        """Create a mock issue."""
        mock_issue = Mock()
        mock_issue.id = issue_id
        mock_issue.subject = f"Issue {issue_id}"
        mock_issue.description = "Test description"

        # Mock required objects
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_issue.project = mock_project

        mock_status = Mock()
        mock_status.id = 1
        mock_status.name = "Open"
        mock_issue.status = mock_status

        mock_priority = Mock()
        mock_priority.id = 2
        mock_priority.name = "Normal"
        mock_issue.priority = mock_priority

        mock_author = Mock()
        mock_author.id = 10
        mock_author.name = "Author"
        mock_issue.author = mock_author

        mock_issue.assigned_to = None
        mock_issue.created_on = None
        mock_issue.updated_on = None

        return mock_issue

    @pytest.mark.asyncio
    async def test_scope_all(self, mock_redmine):
        """Test scope='all' parameter is passed to API."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", scope="all")  # noqa: F841

        # Verify API was called with scope parameter
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "all"

    @pytest.mark.asyncio
    async def test_scope_my_project(self, mock_redmine):
        """Test scope='my_project' parameter is passed to API."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", scope="my_project")  # noqa: F841

        # Verify API was called with scope parameter
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "my_project"

    @pytest.mark.asyncio
    async def test_scope_subprojects(self, mock_redmine):
        """Test scope='subprojects' parameter is passed to API."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", scope="subprojects")  # noqa: F841

        # Verify API was called with scope parameter
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "subprojects"

    @pytest.mark.asyncio
    async def test_open_issues_true(self, mock_redmine):
        """Test open_issues=True parameter is passed to API."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", open_issues=True)  # noqa: F841

        # Verify API was called with open_issues parameter
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["open_issues"] is True

    @pytest.mark.asyncio
    async def test_open_issues_false(self, mock_redmine):
        """Test open_issues=False parameter is passed to API."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", open_issues=False)  # noqa: F841

        # Verify API was called with open_issues parameter
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["open_issues"] is False

    @pytest.mark.asyncio
    async def test_scope_and_open_issues_combined(self, mock_redmine):
        """Test scope and open_issues parameters combined."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues(  # noqa: F841
            "bug", scope="my_project", open_issues=True
        )

        # Verify both parameters passed to API
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "my_project"
        assert call_args[1]["open_issues"] is True

    @pytest.mark.asyncio
    async def test_native_filters_with_pagination(self, mock_redmine):
        """Test native filters combined with pagination."""
        mock_issues = [self.create_mock_issue(i) for i in range(1, 11)]
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(  # noqa: F841
            "bug", scope="my_project", open_issues=True, limit=10, offset=0
        )

        # Verify all parameters passed correctly
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "my_project"
        assert call_args[1]["open_issues"] is True
        assert call_args[1]["limit"] == 10
        assert call_args[1]["offset"] == 0

    @pytest.mark.asyncio
    async def test_native_filters_with_field_selection(self, mock_redmine):
        """Test native filters combined with field selection."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues(
            "bug",
            scope="my_project",
            open_issues=True,
            fields=["id", "subject"],
        )

        # Verify native filters passed to API
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "my_project"
        assert call_args[1]["open_issues"] is True

        # Verify field selection worked
        assert len(result[0]) == 2
        assert "id" in result[0]
        assert "subject" in result[0]

    @pytest.mark.asyncio
    async def test_native_filters_with_pagination_info(self, mock_redmine):
        """Test native filters with pagination metadata."""
        mock_issues = [self.create_mock_issue(i) for i in range(1, 26)]
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug",
            scope="my_project",
            open_issues=True,
            include_pagination_info=True,
        )

        # Verify result structure
        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result

        # Verify native filters passed to API
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "my_project"
        assert call_args[1]["open_issues"] is True

    @pytest.mark.asyncio
    async def test_native_filters_backward_compatible(self, mock_redmine):
        """Test that native filters are optional (backward compatible)."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        # Call without native filters
        result = await search_redmine_issues("bug")

        # Should work without errors
        assert isinstance(result, list)
        assert len(result) == 1

        # Verify scope and open_issues not in call if not provided
        call_args = mock_redmine.issue.search.call_args
        # They should not be in the call args
        assert "scope" not in call_args[1]
        assert "open_issues" not in call_args[1]

    @pytest.mark.asyncio
    async def test_mcp_parameter_unwrapping_with_filters(self, mock_redmine):
        """Test MCP parameter unwrapping with native filters."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        # Simulate MCP wrapping
        result = await search_redmine_issues(  # noqa: F841
            "bug", options={"scope": "my_project", "open_issues": True}
        )

        # Verify parameters unwrapped and passed correctly
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "my_project"
        assert call_args[1]["open_issues"] is True

    @pytest.mark.asyncio
    async def test_all_features_combined(self, mock_redmine):
        """Test all features combined: pagination, field selection, filters."""
        mock_issues = [self.create_mock_issue(i) for i in range(1, 11)]
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug",
            scope="my_project",
            open_issues=True,
            limit=10,
            offset=20,
            fields=["id", "subject", "status"],
            include_pagination_info=True,
        )

        # Verify result structure
        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result

        # Verify field selection
        assert len(result["issues"]) == 10
        assert len(result["issues"][0]) == 3

        # Verify all parameters passed to API
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["scope"] == "my_project"
        assert call_args[1]["open_issues"] is True
        assert call_args[1]["limit"] == 10
        assert call_args[1]["offset"] == 20

        # Verify pagination metadata
        pagination = result["pagination"]
        assert pagination["limit"] == 10
        assert pagination["offset"] == 20

    @pytest.mark.asyncio
    async def test_scope_parameter_string_type(self, mock_redmine):
        """Test that scope parameter accepts string values."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", scope="all")  # noqa: F841

        call_args = mock_redmine.issue.search.call_args
        assert isinstance(call_args[1]["scope"], str)

    @pytest.mark.asyncio
    async def test_open_issues_parameter_bool_type(self, mock_redmine):
        """Test that open_issues parameter accepts boolean values."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", open_issues=True)  # noqa: F841

        call_args = mock_redmine.issue.search.call_args
        assert isinstance(call_args[1]["open_issues"], bool)

    @pytest.mark.asyncio
    async def test_native_filters_with_empty_results(self, mock_redmine):
        """Test native filters with empty search results."""
        mock_redmine.issue.search.return_value = []

        result = await search_redmine_issues(
            "nonexistent", scope="my_project", open_issues=True
        )

        assert result == []
        assert isinstance(result, list)
