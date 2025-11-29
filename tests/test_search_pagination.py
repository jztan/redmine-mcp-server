"""
Test cases for search_redmine_issues pagination functionality.

This module contains comprehensive tests for the pagination support
added to the search_redmine_issues tool.
"""

import pytest
from unittest.mock import Mock, patch
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import search_redmine_issues  # noqa: E402


class TestSearchRedmineIssuesPagination:
    """Test cases for search_redmine_issues pagination."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_issue(self, issue_id=1, subject="Test Issue"):
        """Create a single mock issue."""
        mock_issue = Mock()
        mock_issue.id = issue_id
        mock_issue.subject = subject
        mock_issue.description = f"Description for issue {issue_id}"

        # Mock project
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_issue.project = mock_project

        # Mock status
        mock_status = Mock()
        mock_status.id = 1
        mock_status.name = "New"
        mock_issue.status = mock_status

        # Mock priority
        mock_priority = Mock()
        mock_priority.id = 2
        mock_priority.name = "Normal"
        mock_issue.priority = mock_priority

        # Mock author
        mock_author = Mock()
        mock_author.id = 10
        mock_author.name = "John Doe"
        mock_issue.author = mock_author

        # Mock assigned_to
        mock_assigned = Mock()
        mock_assigned.id = 20
        mock_assigned.name = "Jane Smith"
        mock_issue.assigned_to = mock_assigned

        # Mock timestamps
        mock_issue.created_on = None
        mock_issue.updated_on = None

        return mock_issue

    def create_mock_issues(self, count):
        """Create a list of mock issues."""
        return [
            self.create_mock_issue(issue_id=i, subject=f"Issue {i}")
            for i in range(1, count + 1)
        ]

    @pytest.mark.asyncio
    async def test_default_pagination_limit_25(self, mock_redmine):
        """Test that default limit is 25."""
        # Create 30 mock issues but search should only return 25
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug")

        # Verify search was called with default limit
        mock_redmine.issue.search.assert_called_once()
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 25
        assert call_args[1]["offset"] == 0

        # Verify result is a list
        assert isinstance(result, list)
        assert len(result) == 25

    @pytest.mark.asyncio
    async def test_custom_limit(self, mock_redmine):
        """Test custom limit parameter."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug", limit=10)

        # Verify search was called with custom limit
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 10
        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_custom_offset(self, mock_redmine):
        """Test custom offset parameter."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug", limit=10, offset=50)  # noqa: F841

        # Verify search was called with custom offset
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["offset"] == 50
        assert call_args[1]["limit"] == 10

    @pytest.mark.asyncio
    async def test_limit_validation_negative(self, mock_redmine):
        """Test that negative limit returns empty result."""
        result = await search_redmine_issues("bug", limit=-1)  # noqa: F841

        # Should return empty list without calling API
        assert result == []
        mock_redmine.issue.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_validation_zero(self, mock_redmine):
        """Test that zero limit returns empty result."""
        result = await search_redmine_issues("bug", limit=0)  # noqa: F841

        # Should return empty list without calling API
        assert result == []
        mock_redmine.issue.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_validation_exceeds_maximum(self, mock_redmine):
        """Test that limit > 1000 is capped to 1000."""
        mock_issues = self.create_mock_issues(50)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug", limit=2000)  # noqa: F841

        # Verify limit was capped to 1000
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 1000

    @pytest.mark.asyncio
    async def test_offset_validation_negative(self, mock_redmine):
        """Test that negative offset is reset to 0."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug", offset=-10)  # noqa: F841

        # Verify offset was reset to 0
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["offset"] == 0

    @pytest.mark.asyncio
    async def test_pagination_metadata_structure(self, mock_redmine):
        """Test pagination metadata structure when include_pagination_info=True."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug", limit=25, offset=0, include_pagination_info=True
        )

        # Verify result is a dict with expected keys
        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result

        # Verify pagination metadata structure
        pagination = result["pagination"]
        assert "limit" in pagination
        assert "offset" in pagination
        assert "count" in pagination
        assert "has_next" in pagination
        assert "has_previous" in pagination
        assert "next_offset" in pagination
        assert "previous_offset" in pagination

        # Verify values
        assert pagination["limit"] == 25
        assert pagination["offset"] == 0
        assert pagination["count"] == 25
        assert pagination["has_next"] is True  # count == limit
        assert pagination["has_previous"] is False  # offset == 0
        assert pagination["next_offset"] == 25
        assert pagination["previous_offset"] is None

    @pytest.mark.asyncio
    async def test_pagination_has_next_true(self, mock_redmine):
        """Test has_next=True when result count equals limit."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug", limit=25, include_pagination_info=True
        )

        pagination = result["pagination"]
        assert pagination["has_next"] is True
        assert pagination["next_offset"] == 25

    @pytest.mark.asyncio
    async def test_pagination_has_next_false(self, mock_redmine):
        """Test has_next=False when result count < limit."""
        mock_issues = self.create_mock_issues(10)  # Less than limit
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug", limit=25, include_pagination_info=True
        )

        pagination = result["pagination"]
        assert pagination["count"] == 10
        assert pagination["has_next"] is False
        assert pagination["next_offset"] is None

    @pytest.mark.asyncio
    async def test_pagination_has_previous_true(self, mock_redmine):
        """Test has_previous=True when offset > 0."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug", limit=25, offset=50, include_pagination_info=True
        )

        pagination = result["pagination"]
        assert pagination["has_previous"] is True
        assert pagination["previous_offset"] == 25  # offset - limit

    @pytest.mark.asyncio
    async def test_pagination_previous_offset_calculation(self, mock_redmine):
        """Test previous_offset calculation."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.search.return_value = mock_issues

        # Test with offset=10, limit=25 -> previous should be 0 (max(0, 10-25))
        result = await search_redmine_issues(
            "bug", limit=25, offset=10, include_pagination_info=True
        )

        pagination = result["pagination"]
        assert pagination["previous_offset"] == 0

    @pytest.mark.asyncio
    async def test_mcp_parameter_unwrapping(self, mock_redmine):
        """Test MCP parameter unwrapping for options."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.search.return_value = mock_issues

        # Simulate MCP wrapping parameters in 'options' key
        result = await search_redmine_issues(  # noqa: F841
            "bug", options={"limit": 10, "offset": 5}
        )

        # Verify parameters were unwrapped correctly
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 10
        assert call_args[1]["offset"] == 5

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_redmine):
        """Test handling of empty search results."""
        mock_redmine.issue.search.return_value = []

        result = await search_redmine_issues("nonexistent")

        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_empty_result_with_pagination_info(self, mock_redmine):
        """Test pagination metadata with empty results."""
        mock_redmine.issue.search.return_value = []

        result = await search_redmine_issues(
            "nonexistent", include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert result["issues"] == []
        assert result["pagination"]["count"] == 0
        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    async def test_none_result_handling(self, mock_redmine):
        """Test handling when search returns None."""
        mock_redmine.issue.search.return_value = None

        result = await search_redmine_issues("bug")

        assert result == []

    @pytest.mark.asyncio
    async def test_limit_type_coercion_string(self, mock_redmine):
        """Test that string limit is coerced to int."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug", limit="10")  # noqa: F841

        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 10
        assert isinstance(call_args[1]["limit"], int)

    @pytest.mark.asyncio
    async def test_limit_type_coercion_invalid(self, mock_redmine):
        """Test that invalid limit type falls back to default."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug", limit="invalid")  # noqa: F841

        # Should fall back to default 25
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 25

    @pytest.mark.asyncio
    async def test_additional_search_options_preserved(self, mock_redmine):
        """Test that additional search options are passed through."""
        mock_issues = self.create_mock_issues(10)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(  # noqa: F841
            "bug", limit=10, custom_param="value"
        )

        # Verify custom parameter was passed through
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["custom_param"] == "value"

    @pytest.mark.asyncio
    async def test_error_handling(self, mock_redmine):
        """Test error handling when search fails."""
        mock_redmine.issue.search.side_effect = Exception("API Error")

        result = await search_redmine_issues("bug")

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_pagination_info_with_limit_zero(self, mock_redmine):
        """Test pagination info structure when limit is zero."""
        result = await search_redmine_issues(
            "bug", limit=0, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert result["issues"] == []
        assert result["pagination"]["limit"] == 0
        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_pagination_params(self, mock_redmine):
        """Test backward compatibility when no pagination params provided."""
        mock_issues = self.create_mock_issues(25)
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug")

        # Should return a simple list (backward compatible)
        assert isinstance(result, list)
        assert len(result) == 25
        # Should use default values
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 25
        assert call_args[1]["offset"] == 0
