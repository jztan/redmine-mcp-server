"""
Test cases for field selection in search_redmine_issues.

This module contains tests for the field selection functionality
integrated into the search_redmine_issues tool.
"""

import pytest
from unittest.mock import Mock, patch
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import search_redmine_issues  # noqa: E402


class TestSearchFieldSelection:
    """Test cases for field selection in search_redmine_issues."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_issue(self, issue_id=1):
        """Create a mock issue with all fields."""
        mock_issue = Mock()
        mock_issue.id = issue_id
        mock_issue.subject = f"Issue {issue_id}"
        mock_issue.description = f"Description {issue_id}"

        # Mock project
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_issue.project = mock_project

        # Mock status
        mock_status = Mock()
        mock_status.id = 2
        mock_status.name = "In Progress"
        mock_issue.status = mock_status

        # Mock priority
        mock_priority = Mock()
        mock_priority.id = 3
        mock_priority.name = "High"
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

    @pytest.mark.asyncio
    async def test_fields_none_returns_all_fields(self, mock_redmine):
        """Test that fields=None returns all fields (backward compatible)."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug")

        # Should return all 10 fields
        assert isinstance(result, list)
        assert len(result) == 1
        assert len(result[0]) == 10
        assert "id" in result[0]
        assert "subject" in result[0]
        assert "description" in result[0]
        assert "project" in result[0]
        assert "status" in result[0]
        assert "priority" in result[0]
        assert "author" in result[0]
        assert "assigned_to" in result[0]
        assert "created_on" in result[0]
        assert "updated_on" in result[0]

    @pytest.mark.asyncio
    async def test_fields_minimal_id_subject(self, mock_redmine):
        """Test minimal field selection (id and subject only)."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", fields=["id", "subject"])

        assert isinstance(result, list)
        assert len(result) == 1
        assert len(result[0]) == 2
        assert result[0]["id"] == 1
        assert result[0]["subject"] == "Issue 1"
        # Verify other fields are not present
        assert "description" not in result[0]
        assert "project" not in result[0]

    @pytest.mark.asyncio
    async def test_fields_with_pagination_info(self, mock_redmine):
        """Test field selection combined with pagination metadata."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues(
            "bug",
            fields=["id", "subject", "status"],
            include_pagination_info=True,
        )

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result

        # Check field selection in issues
        issues = result["issues"]
        assert len(issues) == 1
        assert len(issues[0]) == 3
        assert "id" in issues[0]
        assert "subject" in issues[0]
        assert "status" in issues[0]
        assert "description" not in issues[0]

    @pytest.mark.asyncio
    async def test_fields_token_reduction(self, mock_redmine):
        """Test that field selection significantly reduces data size."""
        mock_issues = [self.create_mock_issue(i) for i in range(1, 26)]
        mock_redmine.issue.search.return_value = mock_issues

        # Get all fields
        result_all = await search_redmine_issues("bug")

        # Get minimal fields
        result_minimal = await search_redmine_issues("bug", fields=["id", "subject"])

        assert len(result_all) == 25
        assert len(result_minimal) == 25

        # Minimal should have fewer keys per issue
        assert len(result_minimal[0]) < len(result_all[0])
        assert len(result_minimal[0]) == 2  # Only id and subject
        assert len(result_all[0]) == 10  # All fields

    @pytest.mark.asyncio
    async def test_fields_asterisk_returns_all(self, mock_redmine):
        """Test that fields=["*"] returns all fields."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", fields=["*"])

        assert len(result[0]) == 10  # All fields

    @pytest.mark.asyncio
    async def test_fields_all_keyword(self, mock_redmine):
        """Test that fields=["all"] returns all fields."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", fields=["all"])

        assert len(result[0]) == 10  # All fields

    @pytest.mark.asyncio
    async def test_fields_invalid_ignored(self, mock_redmine):
        """Test that invalid field names are silently ignored."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues(
            "bug", fields=["id", "invalid_field", "subject"]
        )

        # Should only have id and subject
        assert len(result[0]) == 2
        assert "id" in result[0]
        assert "subject" in result[0]
        assert "invalid_field" not in result[0]

    @pytest.mark.asyncio
    async def test_fields_combined_with_custom_limit(self, mock_redmine):
        """Test field selection with custom limit."""
        mock_issues = [self.create_mock_issue(i) for i in range(1, 11)]
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug", limit=10, fields=["id", "subject", "priority"]
        )

        assert len(result) == 10
        assert len(result[0]) == 3
        assert "priority" in result[0]

    @pytest.mark.asyncio
    async def test_fields_combined_with_offset(self, mock_redmine):
        """Test field selection with pagination offset."""
        mock_issues = [self.create_mock_issue(i) for i in range(1, 6)]
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues(
            "bug", limit=5, offset=10, fields=["id", "status"]
        )

        # Verify API was called with correct parameters
        call_args = mock_redmine.issue.search.call_args
        assert call_args[1]["limit"] == 5
        assert call_args[1]["offset"] == 10

        # Verify field selection
        assert len(result[0]) == 2
        assert "id" in result[0]
        assert "status" in result[0]

    @pytest.mark.asyncio
    async def test_fields_empty_list_returns_empty_dicts(self, mock_redmine):
        """Test that empty fields list returns empty dictionaries."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", fields=[])

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {}

    @pytest.mark.asyncio
    async def test_fields_with_nested_objects(self, mock_redmine):
        """Test field selection with nested objects (project, status)."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues("bug", fields=["id", "project", "status"])

        assert len(result[0]) == 3
        assert isinstance(result[0]["project"], dict)
        assert isinstance(result[0]["status"], dict)
        assert "id" in result[0]["project"]
        assert "name" in result[0]["project"]
        assert "id" in result[0]["status"]
        assert "name" in result[0]["status"]

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_fields_param(self, mock_redmine):
        """Test backward compatibility when fields param not provided."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        # Call without fields parameter
        result = await search_redmine_issues("bug", limit=25)

        # Should return all fields (backward compatible)
        assert len(result[0]) == 10

    @pytest.mark.asyncio
    async def test_fields_with_mcp_parameter_unwrapping(self, mock_redmine):
        """Test field selection with MCP parameter unwrapping."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        # Simulate MCP wrapping parameters
        result = await search_redmine_issues(
            "bug", options={"fields": ["id", "subject"], "limit": 10}
        )

        assert len(result[0]) == 2
        assert "id" in result[0]
        assert "subject" in result[0]

    @pytest.mark.asyncio
    async def test_fields_multiple_issues_consistent(self, mock_redmine):
        """Test that field selection is consistent across multiple issues."""
        mock_issues = [self.create_mock_issue(i) for i in range(1, 6)]
        mock_redmine.issue.search.return_value = mock_issues

        result = await search_redmine_issues("bug", fields=["id", "subject"])

        # All issues should have same fields
        for issue in result:
            assert len(issue) == 2
            assert "id" in issue
            assert "subject" in issue
            assert "description" not in issue

    @pytest.mark.asyncio
    async def test_fields_preserves_data_types(self, mock_redmine):
        """Test that field selection preserves correct data types."""
        mock_issue = self.create_mock_issue()
        mock_redmine.issue.search.return_value = [mock_issue]

        result = await search_redmine_issues(
            "bug", fields=["id", "project", "assigned_to"]
        )

        # id should be int
        assert isinstance(result[0]["id"], int)
        # project should be dict
        assert isinstance(result[0]["project"], dict)
        # assigned_to should be dict
        assert isinstance(result[0]["assigned_to"], dict)
