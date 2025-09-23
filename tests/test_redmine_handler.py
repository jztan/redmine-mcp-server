"""
Test cases for redmine_handler.py MCP tools.

This module contains unit tests for the Redmine MCP server tools,
including tests for project listing and issue retrieval functionality.
"""
import pytest
import asyncio
import uuid
from unittest.mock import Mock, patch, MagicMock, mock_open
from typing import Dict, Any, List
import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from redmine_mcp_server.redmine_handler import get_redmine_issue, list_redmine_projects, summarize_project_status, _analyze_issues
from redminelib.exceptions import ResourceNotFoundError


class TestRedmineHandler:
    """Test cases for Redmine MCP tools."""

    @pytest.fixture
    def mock_redmine_issue(self):
        """Create a mock Redmine issue object."""
        mock_issue = Mock()
        mock_issue.id = 123
        mock_issue.subject = "Test Issue Subject"
        mock_issue.description = "Test issue description"
        
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
        mock_author.id = 1
        mock_author.name = "Test Author"
        mock_issue.author = mock_author
        
        # Mock assigned_to (optional field)
        mock_assigned = Mock()
        mock_assigned.id = 2
        mock_assigned.name = "Test Assignee"
        mock_issue.assigned_to = mock_assigned
        
        # Mock dates
        from datetime import datetime
        mock_issue.created_on = datetime(2025, 1, 1, 10, 0, 0)
        mock_issue.updated_on = datetime(2025, 1, 2, 15, 30, 0)

        # Mock attachments
        attachment = Mock()
        attachment.id = 10
        attachment.filename = "test.txt"
        attachment.filesize = 100
        attachment.content_type = "text/plain"
        attachment.description = "test attachment"
        attachment.content_url = "http://example.com/test.txt"
        att_author = Mock()
        att_author.id = 4
        att_author.name = "Attachment Author"
        attachment.author = att_author
        attachment.created_on = datetime(2025, 1, 2, 11, 0, 0)
        mock_issue.attachments = [attachment]

        return mock_issue

    @pytest.fixture
    def mock_redmine_projects(self):
        """Create mock Redmine project objects."""
        projects = []
        for i in range(3):
            mock_project = Mock()
            mock_project.id = i + 1
            mock_project.name = f"Test Project {i + 1}"
            mock_project.identifier = f"test-project-{i + 1}"
            mock_project.description = f"Description for project {i + 1}"
            
            from datetime import datetime
            mock_project.created_on = datetime(2025, 1, i + 1, 10, 0, 0)
            projects.append(mock_project)
        
        return projects

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_get_redmine_issue_success(self, mock_redmine, mock_issue_with_comments):
        """Test successful issue retrieval including journals by default."""
        # Setup
        mock_redmine.issue.get.return_value = mock_issue_with_comments

        # Execute
        result = await get_redmine_issue(123)

        # Verify
        assert result is not None
        assert result["id"] == 123
        assert result["subject"] == "Test Issue Subject"
        assert result["description"] == "Test issue description"
        assert result["project"]["id"] == 1
        assert result["project"]["name"] == "Test Project"
        assert result["status"]["id"] == 1
        assert result["status"]["name"] == "New"
        assert result["priority"]["id"] == 2
        assert result["priority"]["name"] == "Normal"
        assert result["author"]["id"] == 1
        assert result["author"]["name"] == "Test Author"
        assert result["assigned_to"]["id"] == 2
        assert result["assigned_to"]["name"] == "Test Assignee"
        assert result["created_on"] == "2025-01-01T10:00:00"
        assert result["updated_on"] == "2025-01-02T15:30:00"
        assert isinstance(result.get("journals"), list)
        assert result["journals"][0]["notes"] == "First comment"

        assert isinstance(result.get("attachments"), list)
        assert result["attachments"][0]["filename"] == "test.txt"

        # Verify the mock was called correctly
        mock_redmine.issue.get.assert_called_once_with(123, include="journals,attachments")

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_get_redmine_issue_not_found(self, mock_redmine):
        """Test issue not found scenario."""
        from redminelib.exceptions import ResourceNotFoundError
        
        # Setup - ResourceNotFoundError doesn't take a message parameter
        mock_redmine.issue.get.side_effect = ResourceNotFoundError()
        
        # Execute
        result = await get_redmine_issue(999)
        
        # Verify
        assert result is not None
        assert "error" in result
        assert result["error"] == "Issue 999 not found."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_get_redmine_issue_general_error(self, mock_redmine):
        """Test general error handling in issue retrieval."""
        # Setup
        mock_redmine.issue.get.side_effect = Exception("Connection error")
        
        # Execute
        result = await get_redmine_issue(123)
        
        # Verify
        assert result is not None
        assert "error" in result
        assert "An error occurred while fetching issue 123" in result["error"]

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_get_redmine_issue_no_client(self):
        """Test issue retrieval when Redmine client is not initialized."""
        # Execute
        result = await get_redmine_issue(123)
        
        # Verify
        assert result is not None
        assert "error" in result
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_get_redmine_issue_no_assigned_to(self, mock_redmine, mock_redmine_issue):
        """Test issue retrieval when issue has no assigned_to field."""
        # Setup - remove assigned_to attribute
        delattr(mock_redmine_issue, 'assigned_to')
        mock_redmine.issue.get.return_value = mock_redmine_issue

        # Execute
        result = await get_redmine_issue(123)

        # Verify
        assert result is not None
        assert result["assigned_to"] is None

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_get_redmine_issue_without_journals(self, mock_redmine, mock_redmine_issue):
        """Test opting out of journal retrieval."""
        mock_redmine.issue.get.return_value = mock_redmine_issue

        result = await get_redmine_issue(123, include_journals=False)

        assert "journals" not in result
        assert isinstance(result.get("attachments"), list)
        mock_redmine.issue.get.assert_called_once_with(123, include="attachments")

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_get_redmine_issue_without_attachments(self, mock_redmine, mock_redmine_issue):
        """Test opting out of attachment retrieval."""
        mock_redmine.issue.get.return_value = mock_redmine_issue

        result = await get_redmine_issue(123, include_attachments=False)

        assert "attachments" not in result
        mock_redmine.issue.get.assert_called_once_with(123, include="journals")

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_redmine_projects_success(self, mock_redmine, mock_redmine_projects):
        """Test successful project listing."""
        # Setup
        mock_redmine.project.all.return_value = mock_redmine_projects
        
        # Execute
        result = await list_redmine_projects()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 3
        
        for i, project in enumerate(result):
            assert project["id"] == i + 1
            assert project["name"] == f"Test Project {i + 1}"
            assert project["identifier"] == f"test-project-{i + 1}"
            assert project["description"] == f"Description for project {i + 1}"
            assert project["created_on"] == f"2025-01-0{i + 1}T10:00:00"
        
        # Verify the mock was called correctly
        mock_redmine.project.all.assert_called_once()

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_redmine_projects_empty(self, mock_redmine):
        """Test project listing when no projects exist."""
        # Setup
        mock_redmine.project.all.return_value = []
        
        # Execute
        result = await list_redmine_projects()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_redmine_projects_error(self, mock_redmine):
        """Test error handling in project listing."""
        # Setup
        mock_redmine.project.all.side_effect = Exception("Connection error")
        
        # Execute
        result = await list_redmine_projects()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]
        assert "An error occurred while listing projects" in result[0]["error"]

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_list_redmine_projects_no_client(self):
        """Test project listing when Redmine client is not initialized."""
        # Execute
        result = await list_redmine_projects()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]
        assert result[0]["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_redmine_projects_missing_attributes(self, mock_redmine):
        """Test project listing when projects have missing optional attributes."""
        # Setup - create project with missing description and created_on
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_project.identifier = "test-project"
        # Remove description and created_on attributes to simulate missing attributes
        del mock_project.description
        del mock_project.created_on
        
        mock_redmine.project.all.return_value = [mock_project]
        
        # Execute
        result = await list_redmine_projects()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        
        project = result[0]
        assert project["id"] == 1
        assert project["name"] == "Test Project"
        assert project["identifier"] == "test-project"
        assert project["description"] == ""  # getattr default
        assert project["created_on"] is None  # hasattr check

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_create_redmine_issue_success(self, mock_redmine, mock_redmine_issue):
        """Test successful issue creation."""
        mock_redmine.issue.create.return_value = mock_redmine_issue

        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(1, "Test Issue Subject", "Test issue description")

        assert result is not None
        assert result["id"] == 123
        mock_redmine.issue.create.assert_called_once_with(
            project_id=1, subject="Test Issue Subject", description="Test issue description"
        )

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_create_redmine_issue_error(self, mock_redmine):
        """Test error during issue creation."""
        mock_redmine.issue.create.side_effect = Exception("Boom")

        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(1, "A", "B")
        assert "error" in result

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_create_redmine_issue_no_client(self):
        """Test issue creation when client is not initialized."""
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(1, "A")
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_update_redmine_issue_success(self, mock_redmine, mock_redmine_issue):
        """Test successful issue update."""
        mock_redmine.issue.update.return_value = True
        mock_redmine.issue.get.return_value = mock_redmine_issue

        from redmine_mcp_server.redmine_handler import update_redmine_issue

        result = await update_redmine_issue(123, {"subject": "New"})

        assert result["id"] == 123
        mock_redmine.issue.update.assert_called_once_with(123, subject="New")

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_update_redmine_issue_status_name(self, mock_redmine, mock_redmine_issue):
        """Update issue using a status name instead of an ID."""
        mock_redmine.issue.update.return_value = True
        mock_redmine.issue.get.return_value = mock_redmine_issue

        status = Mock()
        status.id = 5
        status.name = "Closed"
        mock_redmine.issue_status.all.return_value = [status]

        from redmine_mcp_server.redmine_handler import update_redmine_issue

        result = await update_redmine_issue(123, {"status_name": "Closed"})

        assert result["id"] == 123
        mock_redmine.issue.update.assert_called_once_with(123, status_id=5)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_update_redmine_issue_not_found(self, mock_redmine):
        """Test update when issue not found."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue.update.side_effect = ResourceNotFoundError()

        from redmine_mcp_server.redmine_handler import update_redmine_issue

        result = await update_redmine_issue(999, {"subject": "X"})

        assert result["error"] == "Issue 999 not found."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_update_redmine_issue_no_client(self):
        """Test update when client not initialized."""
        from redmine_mcp_server.redmine_handler import update_redmine_issue

        result = await update_redmine_issue(1, {"subject": "X"})
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_success(self, mock_redmine, mock_redmine_issue):
        """Test listing issues assigned to current user."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue]

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert result[0]["id"] == 123
        mock_redmine.issue.filter.assert_called_once_with(assigned_to_id="me", offset=0, limit=25)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_empty(self, mock_redmine):
        """Test listing issues when none exist."""
        mock_redmine.issue.filter.return_value = []

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_error(self, mock_redmine):
        """Test error handling when listing issues."""
        mock_redmine.issue.filter.side_effect = Exception("Boom")

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert "error" in result[0]

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_list_my_redmine_issues_no_client(self):
        """Test listing issues when client is not initialized."""
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert result[0]["error"] == "Redmine client not initialized."

    # Pagination Test Cases
    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_with_limit_basic(self, mock_redmine, mock_redmine_issue):
        """Test basic limit functionality."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 5

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(limit=5)

        assert isinstance(result, list)
        assert len(result) == 5
        mock_redmine.issue.filter.assert_called_once_with(assigned_to_id="me", offset=0, limit=5)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_with_offset(self, mock_redmine, mock_redmine_issue):
        """Test offset pagination."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 10

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(limit=10, offset=25)

        assert isinstance(result, list)
        assert len(result) == 10
        mock_redmine.issue.filter.assert_called_once_with(assigned_to_id="me", offset=25, limit=10)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_with_metadata(self, mock_redmine, mock_redmine_issue):
        """Test pagination metadata response."""
        # Create mock ResourceSet that behaves like a list when converted
        mock_resource_set = Mock()
        mock_resource_set.__iter__ = Mock(return_value=iter([mock_redmine_issue] * 10))
        mock_resource_set.total_count = 150

        # Make filter() return our mock ResourceSet
        mock_redmine.issue.filter.return_value = mock_resource_set

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(limit=10, offset=25, include_pagination_info=True)

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result
        assert len(result["issues"]) == 10
        assert result["pagination"]["total"] == 150
        assert result["pagination"]["limit"] == 10
        assert result["pagination"]["offset"] == 25
        assert result["pagination"]["has_next"] == True
        assert result["pagination"]["has_previous"] == True
        assert result["pagination"]["next_offset"] == 35

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_edge_cases(self, mock_redmine):
        """Test zero, negative, and excessive limits."""
        mock_redmine.issue.filter.return_value = []

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        # Test zero limit
        result = await list_my_redmine_issues(limit=0)
        assert isinstance(result, list)
        assert len(result) == 0

        # Test negative limit
        result = await list_my_redmine_issues(limit=-5)
        assert isinstance(result, list)
        assert len(result) == 0

        # Test excessive limit (should be capped to 1000)
        mock_redmine.issue.filter.return_value = []
        result = await list_my_redmine_issues(limit=5000)
        # Should be called with limit capped to 100 (Redmine API max per request)
        mock_redmine.issue.filter.assert_called_with(assigned_to_id="me", offset=0, limit=100)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_default_limit(self, mock_redmine, mock_redmine_issue):
        """Test default limit behavior."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 25

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert len(result) == 25
        mock_redmine.issue.filter.assert_called_once_with(assigned_to_id="me", offset=0, limit=25)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_limit_with_filters(self, mock_redmine, mock_redmine_issue):
        """Test limit + other filters."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 15

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(limit=15, project_id=123, status_id=1)

        assert isinstance(result, list)
        assert len(result) == 15
        mock_redmine.issue.filter.assert_called_once_with(
            assigned_to_id="me", offset=0, limit=15, project_id=123, status_id=1
        )

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_pagination_navigation(self, mock_redmine, mock_redmine_issue):
        """Test next/previous logic."""
        # Create mock ResourceSet that behaves like a list when converted
        mock_resource_set = Mock()
        mock_resource_set.__iter__ = Mock(return_value=iter([mock_redmine_issue] * 10))
        mock_resource_set.total_count = 100

        # Make filter() return our mock ResourceSet
        mock_redmine.issue.filter.return_value = mock_resource_set

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        # Test middle page
        result = await list_my_redmine_issues(limit=10, offset=25, include_pagination_info=True)
        pagination = result["pagination"]
        assert pagination["has_next"] == True
        assert pagination["has_previous"] == True
        assert pagination["next_offset"] == 35
        assert pagination["previous_offset"] == 15

        # Test first page
        result = await list_my_redmine_issues(limit=10, offset=0, include_pagination_info=True)
        pagination = result["pagination"]
        assert pagination["has_previous"] == False
        assert pagination["previous_offset"] == None

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_issues_parameter_validation(self, mock_redmine, mock_redmine_issue):
        """Test input validation and sanitization."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 10

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        # Test string limit conversion
        result = await list_my_redmine_issues(limit="10")
        mock_redmine.issue.filter.assert_called_with(assigned_to_id="me", offset=0, limit=10)

        # Test invalid limit type
        mock_redmine.issue.filter.reset_mock()
        result = await list_my_redmine_issues(limit="invalid")
        mock_redmine.issue.filter.assert_called_with(assigned_to_id="me", offset=0, limit=25)  # default

        # Test negative offset (should reset to 0)
        mock_redmine.issue.filter.reset_mock()
        result = await list_my_redmine_issues(offset=-10)
        mock_redmine.issue.filter.assert_called_with(assigned_to_id="me", offset=0, limit=25)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    @patch.dict('os.environ', {'SERVER_HOST': 'localhost', 'SERVER_PORT': '8000'})
    async def test_download_redmine_attachment_success(self, mock_redmine, tmp_path):
        """Test successful attachment download with HTTP URL return."""
        # Create a real temporary file for the mock to return
        test_file = tmp_path / "test_attachment.pdf"
        test_file.write_text("test content")

        mock_attachment = Mock()
        mock_attachment.download.return_value = str(test_file)
        mock_attachment.filename = "test_attachment.pdf"
        mock_attachment.content_type = "application/pdf"
        mock_redmine.attachment.get.return_value = mock_attachment

        from redmine_mcp_server.redmine_handler import download_redmine_attachment

        result = await download_redmine_attachment(5, str(tmp_path))

        # Test new HTTP URL format
        assert "download_url" in result
        assert "filename" in result
        assert "content_type" in result
        assert "size" in result
        assert "expires_at" in result
        assert "attachment_id" in result

        assert result["filename"] == "test_attachment.pdf"
        assert result["content_type"] == "application/pdf"
        assert result["attachment_id"] == 5
        assert "http://localhost:8000/files/" in result["download_url"]

        mock_redmine.attachment.get.assert_called_once_with(5)
        # Note: deprecated function now ignores save_dir and uses server default
        mock_attachment.download.assert_called_once_with(savepath="attachments")

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_download_redmine_attachment_not_found(self, mock_redmine):
        """Attachment not found scenario."""
        from redminelib.exceptions import ResourceNotFoundError
        mock_redmine.attachment.get.side_effect = ResourceNotFoundError()

        from redmine_mcp_server.redmine_handler import download_redmine_attachment

        result = await download_redmine_attachment(999)

        assert result["error"] == "Attachment 999 not found."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_download_redmine_attachment_error(self, mock_redmine):
        """General error during download."""
        mock_redmine.attachment.get.side_effect = Exception("boom")

        from redmine_mcp_server.redmine_handler import download_redmine_attachment

        result = await download_redmine_attachment(1)

        assert "error" in result

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_download_redmine_attachment_no_client(self):
        """Download when client not initialized."""
        from redmine_mcp_server.redmine_handler import download_redmine_attachment

        result = await download_redmine_attachment(1)

        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    @patch('redmine_mcp_server.redmine_handler._ensure_cleanup_started')
    async def test_get_redmine_attachment_download_url_success(self, mock_cleanup, mock_redmine):
        """Test successful URL generation with secure implementation."""
        # Mock setup
        mock_attachment = MagicMock()
        mock_attachment.filename = "test.pdf"
        mock_attachment.content_type = "application/pdf"
        mock_attachment.download = MagicMock(return_value="/tmp/test_download")

        mock_redmine.attachment.get.return_value = mock_attachment

        with patch('uuid.uuid4', return_value=MagicMock(spec=uuid.UUID)) as mock_uuid:
            mock_uuid.return_value.__str__ = MagicMock(return_value="test-uuid-123")
            with patch('builtins.open', mock_open()) as mock_file:
                with patch('pathlib.Path.mkdir'):
                    with patch('pathlib.Path.stat') as mock_stat:
                        mock_stat.return_value.st_size = 1024
                        with patch('os.rename'):
                            with patch('json.dump'):
                                from redmine_mcp_server.redmine_handler import get_redmine_attachment_download_url

                                result = await get_redmine_attachment_download_url(123)

        # Assertions
        assert "error" not in result
        assert "download_url" in result
        assert "filename" in result
        assert "attachment_id" in result
        assert result["attachment_id"] == 123
        assert "test.pdf" in result["filename"]
        assert "test-uuid-123" in result["download_url"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_get_redmine_attachment_download_url_not_found(self, mock_redmine):
        """Test handling of non-existent attachment ID."""
        mock_redmine.attachment.get.side_effect = ResourceNotFoundError()

        from redmine_mcp_server.redmine_handler import get_redmine_attachment_download_url

        result = await get_redmine_attachment_download_url(999)

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.get_redmine_attachment_download_url')
    async def test_download_redmine_attachment_deprecation_warning(self, mock_new_func, caplog):
        """Test that deprecated function logs warning and delegates properly."""
        # Mock the new function
        expected_result = {"download_url": "http://test.com", "attachment_id": 123}
        mock_new_func.return_value = expected_result

        import logging
        from redmine_mcp_server.redmine_handler import download_redmine_attachment

        # Call deprecated function
        with caplog.at_level(logging.WARNING):
            result = await download_redmine_attachment(123, save_dir="../dangerous")

        # Verify deprecation warning
        assert "DEPRECATED" in caplog.text
        assert "get_redmine_attachment_download_url" in caplog.text

        # Verify security warning for dangerous save_dir
        assert "SECURITY: Rejected save_dir" in caplog.text
        assert "path traversal attack" in caplog.text

        # Verify delegation
        assert result == expected_result
        mock_new_func.assert_called_once_with(123)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_search_redmine_issues_success(self, mock_redmine, mock_redmine_issue):
        """Search issues successfully."""
        mock_redmine.issue.search.return_value = [mock_redmine_issue]

        from redmine_mcp_server.redmine_handler import search_redmine_issues

        result = await search_redmine_issues("test")

        assert isinstance(result, list)
        assert result[0]["id"] == 123
        mock_redmine.issue.search.assert_called_once_with("test")

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_search_redmine_issues_empty(self, mock_redmine):
        """Search issues with no matches."""
        mock_redmine.issue.search.return_value = []

        from redmine_mcp_server.redmine_handler import search_redmine_issues

        result = await search_redmine_issues("none")

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_search_redmine_issues_error(self, mock_redmine):
        """General search error handling."""
        mock_redmine.issue.search.side_effect = Exception("boom")

        from redmine_mcp_server.redmine_handler import search_redmine_issues

        result = await search_redmine_issues("a")

        assert isinstance(result, list)
        assert "error" in result[0]

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_search_redmine_issues_no_client(self):
        """Search when client not initialized."""
        from redmine_mcp_server.redmine_handler import search_redmine_issues

        result = await search_redmine_issues("a")

        assert result[0]["error"] == "Redmine client not initialized."

    @pytest.fixture
    def mock_issue_with_comments(self, mock_redmine_issue):
        """Add journals with comments to the mock issue."""
        from datetime import datetime

        journal = Mock()
        journal.id = 1
        journal.notes = "First comment"
        journal.created_on = datetime(2025, 1, 3, 12, 0, 0)
        user = Mock()
        user.id = 3
        user.name = "Commenter"
        journal.user = user

        mock_redmine_issue.journals = [journal]
        return mock_redmine_issue

    @pytest.fixture
    def mock_project(self):
        """Create a mock Redmine project object."""
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_project.identifier = "test-project"
        return mock_project

    @pytest.fixture
    def mock_issues_list(self):
        """Create a list of mock issues for testing."""
        issues = []
        
        # Create 3 mock issues with different statuses and priorities
        for i in range(3):
            issue = Mock()
            issue.id = i + 1
            issue.subject = f"Test Issue {i + 1}"
            
            # Mock status
            status = Mock()
            if i == 0:
                status.name = "New"
            elif i == 1:
                status.name = "In Progress"
            else:
                status.name = "Resolved"
            issue.status = status
            
            # Mock priority
            priority = Mock()
            priority.name = "Normal" if i != 2 else "High"
            issue.priority = priority
            
            # Mock assignee
            if i == 0:
                issue.assigned_to = None  # Unassigned
            else:
                assigned = Mock()
                assigned.name = f"User {i}"
                issue.assigned_to = assigned
            
            issues.append(issue)
        
        return issues

    def test_analyze_issues_helper(self, mock_issues_list):
        """Test the _analyze_issues helper function."""
        result = _analyze_issues(mock_issues_list)
        
        assert result["total"] == 3
        assert result["by_status"]["New"] == 1
        assert result["by_status"]["In Progress"] == 1
        assert result["by_status"]["Resolved"] == 1
        assert result["by_priority"]["Normal"] == 2
        assert result["by_priority"]["High"] == 1
        assert result["by_assignee"]["Unassigned"] == 1
        assert result["by_assignee"]["User 1"] == 1
        assert result["by_assignee"]["User 2"] == 1

    def test_analyze_issues_empty_list(self):
        """Test _analyze_issues with empty list."""
        result = _analyze_issues([])
        
        assert result["total"] == 0
        assert result["by_status"] == {}
        assert result["by_priority"] == {}
        assert result["by_assignee"] == {}

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_summarize_project_status_success(self, mock_redmine, mock_project, mock_issues_list):
        """Test successful project status summarization."""
        mock_redmine.project.get.return_value = mock_project
        mock_redmine.issue.filter.return_value = mock_issues_list
        
        result = await summarize_project_status(1, 30)
        
        assert "error" not in result
        assert result["project"]["id"] == 1
        assert result["project"]["name"] == "Test Project"
        assert result["analysis_period"]["days"] == 30
        assert "recent_activity" in result
        assert "project_totals" in result
        assert "insights" in result
        
        # Verify the analysis period dates are set
        assert "start_date" in result["analysis_period"]
        assert "end_date" in result["analysis_period"]
        
        # Verify insights calculations
        insights = result["insights"]
        assert "daily_creation_rate" in insights
        assert "daily_update_rate" in insights
        assert "recent_activity_percentage" in insights

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_summarize_project_status_project_not_found(self, mock_redmine):
        """Test project status summarization with non-existent project."""
        from redminelib.exceptions import ResourceNotFoundError
        mock_redmine.project.get.side_effect = ResourceNotFoundError()
        
        result = await summarize_project_status(999, 30)
        
        assert result["error"] == "Project 999 not found."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_summarize_project_status_no_client(self):
        """Test project status summarization with no Redmine client."""
        result = await summarize_project_status(1, 30)
        
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_summarize_project_status_custom_days(self, mock_redmine, mock_project):
        """Test project status summarization with custom days parameter."""
        mock_redmine.project.get.return_value = mock_project
        mock_redmine.issue.filter.return_value = []
        
        result = await summarize_project_status(1, 7)
        
        assert result["analysis_period"]["days"] == 7
        
    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_summarize_project_status_exception_handling(self, mock_redmine, mock_project):
        """Test project status summarization exception handling."""
        mock_redmine.project.get.return_value = mock_project
        mock_redmine.issue.filter.side_effect = Exception("API Error")
        
        result = await summarize_project_status(1, 30)

        assert result["error"] == "An error occurred while summarizing project 1."

    @pytest.mark.asyncio
    @patch.dict('os.environ', {'ATTACHMENTS_DIR': './test_attachments'})
    async def test_cleanup_attachment_files_success(self, tmp_path):
        """Test successful attachment cleanup."""
        from redmine_mcp_server.redmine_handler import cleanup_attachment_files

        result = await cleanup_attachment_files()

        assert "cleanup" in result
        assert "current_storage" in result
        assert isinstance(result["cleanup"], dict)
        assert isinstance(result["current_storage"], dict)

        # Check expected keys in cleanup stats
        assert "cleaned_files" in result["cleanup"]
        assert "cleaned_bytes" in result["cleanup"]
        assert "cleaned_mb" in result["cleanup"]

        # Check expected keys in storage stats
        assert "total_files" in result["current_storage"]
        assert "total_bytes" in result["current_storage"]
        assert "total_mb" in result["current_storage"]

