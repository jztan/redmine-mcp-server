"""
Test cases for redmine_handler.py MCP tools.

This module contains unit tests for the Redmine MCP server tools,
including tests for project listing and issue retrieval functionality.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List
import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from redmine_mcp_server.redmine_handler import get_redmine_issue, list_redmine_projects, list_my_redmine_issues


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
    async def test_get_redmine_issue_success(self, mock_redmine, mock_redmine_issue):
        """Test successful issue retrieval."""
        # Setup
        mock_redmine.issue.get.return_value = mock_redmine_issue
        
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
        
        # Verify the mock was called correctly
        mock_redmine.issue.get.assert_called_once_with(123)

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

    @pytest.fixture
    def mock_current_user(self):
        """Create a mock current user object."""
        mock_user = Mock()
        mock_user.id = 42
        mock_user.name = "Current User"
        return mock_user

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_success(self, mock_redmine, mock_redmine_issue, mock_current_user):
        """Test successful retrieval of my issues."""
        # Setup - add groups attribute to mock current user
        mock_current_user.groups = []  # No groups for this test
        mock_redmine.user.get.return_value = mock_current_user
        mock_redmine.issue.filter.return_value = [mock_redmine_issue]
        
        # Execute
        result = await list_my_redmine_issues()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        
        issue = result[0]
        assert issue["id"] == 123
        assert issue["subject"] == "Test Issue Subject"
        assert issue["description"] == "Test issue description"
        assert issue["project"]["id"] == 1
        assert issue["project"]["name"] == "Test Project"
        assert issue["status"]["id"] == 1
        assert issue["status"]["name"] == "New"
        assert issue["priority"]["id"] == 2
        assert issue["priority"]["name"] == "Normal"
        assert issue["author"]["id"] == 1
        assert issue["author"]["name"] == "Test Author"
        assert issue["assigned_to"]["id"] == 2
        assert issue["assigned_to"]["name"] == "Test Assignee"
        assert issue["created_on"] == "2025-01-01T10:00:00"
        assert issue["updated_on"] == "2025-01-02T15:30:00"
        
        # Verify the mocks were called correctly - now accommodating the enhanced group detection
        # The implementation first calls get('current') and then get('current', include='groups')
        assert mock_redmine.user.get.call_count >= 1
        assert ('current',) in [args for args, kwargs in mock_redmine.user.get.call_args_list]
        assert ('current', {'include': 'groups'}) in [(args[0], kwargs) for args, kwargs in mock_redmine.user.get.call_args_list if kwargs]
        
        # Verify at least one filter call was made for the user's issues
        assert mock_redmine.issue.filter.call_count >= 1
        assert any(call.kwargs.get('assigned_to_id') == 42 for call in mock_redmine.issue.filter.call_args_list)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_with_filters(self, mock_redmine, mock_current_user):
        """Test issue retrieval with various filters."""
        # Setup - add groups attribute to mock current user
        mock_current_user.groups = []  # No groups for this test
        mock_redmine.user.get.return_value = mock_current_user
        mock_redmine.issue.filter.return_value = []
        
        # Execute
        result = await list_my_redmine_issues(
            project_id=1, 
            status_id='open', 
            sort='priority:desc',
            limit=10,
            offset=5
        )
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 0
        
        # Verify the filter was called with correct parameters at least once
        # The enhanced implementation may make additional calls for group discovery
        assert mock_redmine.issue.filter.call_count >= 1
        assert any(
            all(item in call.kwargs.items() for item in {
                'project_id': 1,
                'status_id': 'open',
                'sort': 'priority:desc',
                'assigned_to_id': 42,
                'limit': 20,  # Doubled internally for deduplication
                'offset': 5,
            }.items())
            for call in mock_redmine.issue.filter.call_args_list
        )

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_specific_user(self, mock_redmine):
        """Test issue retrieval with specific user ID (not 'me')."""
        # Setup
        mock_redmine.issue.filter.return_value = []
        
        # Execute
        result = await list_my_redmine_issues(assigned_to_id='123')
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 0
        
        # Verify user.get was NOT called since we didn't use 'me'
        mock_redmine.user.get.assert_not_called()
        mock_redmine.issue.filter.assert_called_once_with(
            limit=50, offset=0, assigned_to_id='123'  # Doubled internally for deduplication
        )

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_user_fetch_error(self, mock_redmine):
        """Test error handling when fetching current user fails."""
        # Setup
        mock_redmine.user.get.side_effect = Exception("User fetch error")
        
        # Execute
        result = await list_my_redmine_issues()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]
        assert "Could not determine current user ID for 'me'" in result[0]["error"]

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_filter_error(self, mock_redmine, mock_current_user):
        """Test error handling when issue filtering fails."""
        # Setup - add groups attribute to mock current user
        mock_current_user.groups = []  # No groups for this test
        mock_redmine.user.get.return_value = mock_current_user
        mock_redmine.issue.filter.side_effect = Exception("Filter error")
        
        # Execute
        result = await list_my_redmine_issues()
        
        # Verify - the enhanced function handles errors gracefully and returns empty list
        # rather than an error, as it tries to continue with available data
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 0  # No issues returned due to filter error

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine', None)
    async def test_list_my_redmine_issues_no_client(self):
        """Test issue retrieval when Redmine client is not initialized."""
        # Execute
        result = await list_my_redmine_issues()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]
        assert result[0]["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_with_groups(self, mock_redmine, mock_redmine_issue, mock_current_user):
        """Test issue retrieval including group assignments."""
        # Setup - create mock group
        mock_group = Mock()
        mock_group.id = 10
        mock_group.name = "Dev Team"
        
        # Setup current user with groups
        mock_current_user.groups = [mock_group]
        mock_redmine.user.get.return_value = mock_current_user
        
        # Setup issue filter to return different issues for user vs group
        def mock_filter(**kwargs):
            if kwargs.get('assigned_to_id') == 42:  # User ID
                return [mock_redmine_issue]
            elif kwargs.get('assigned_to_id') == 10:  # Group ID
                # Create a different mock issue for group assignment
                group_issue = Mock()
                group_issue.id = 456
                group_issue.subject = "Group Issue"
                group_issue.description = "Group issue description"
                group_issue.project = Mock(id=2, name="Group Project")
                group_issue.status = Mock(id=2, name="In Progress")
                group_issue.priority = Mock(id=3, name="High")
                group_issue.author = Mock(id=3, name="Group Author")
                group_issue.assigned_to = Mock()
                group_issue.assigned_to.id = 10
                group_issue.assigned_to.name = "Dev Team"
                group_issue.created_on = Mock()
                group_issue.created_on.isoformat.return_value = "2025-01-03T12:00:00"
                group_issue.updated_on = Mock()
                group_issue.updated_on.isoformat.return_value = "2025-01-04T16:00:00"
                return [group_issue]
            return []
        
        mock_redmine.issue.filter.side_effect = mock_filter
        
        # Execute
        result = await list_my_redmine_issues()
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 2  # Should have both user and group issues
        
        # Verify user issue
        user_issue = next((issue for issue in result if issue["id"] == 123), None)
        assert user_issue is not None
        assert user_issue["subject"] == "Test Issue Subject"
        
        # Verify group issue
        group_issue = next((issue for issue in result if issue["id"] == 456), None)
        assert group_issue is not None
        assert group_issue["subject"] == "Group Issue"
        assert group_issue["assigned_to"]["name"] == "Dev Team"
        
        # Verify the mocks were called correctly
        # The implementation now calls get('current') first, then get('current', include='groups')
        assert mock_redmine.user.get.call_count >= 1
        assert ('current',) in [args for args, kwargs in mock_redmine.user.get.call_args_list]
        assert ('current', {'include': 'groups'}) in [(args[0], kwargs) for args, kwargs in mock_redmine.user.get.call_args_list if kwargs]
        
        # Verify the issue filter calls include both user ID and group ID
        assert mock_redmine.issue.filter.call_count >= 2  # At least once for user and once for group
        assert any(call.kwargs.get('assigned_to_id') == 42 for call in mock_redmine.issue.filter.call_args_list)
        assert any(call.kwargs.get('assigned_to_id') == 10 for call in mock_redmine.issue.filter.call_args_list)

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_exclude_groups(self, mock_redmine, mock_redmine_issue, mock_current_user):
        """Test issue retrieval excluding group assignments."""
        # Setup - create mock group
        mock_group = Mock()
        mock_group.id = 10
        mock_group.name = "Dev Team"
        
        # Setup current user with groups
        mock_current_user.groups = [mock_group]
        mock_redmine.user.get.return_value = mock_current_user
        mock_redmine.issue.filter.return_value = [mock_redmine_issue]
        
        # Execute with include_group_assignments=False
        result = await list_my_redmine_issues(include_group_assignments=False)
        
        # Verify
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1  # Should only have user issue, not group issues
        
        issue = result[0]
        assert issue["id"] == 123
        assert issue["subject"] == "Test Issue Subject"
        
        # Verify the filter was called only once (for user, not for groups)
        mock_redmine.issue.filter.assert_called_once_with(
            limit=50, offset=0, assigned_to_id=42
        )

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    async def test_list_my_redmine_issues_deduplication(self, mock_redmine, mock_current_user):
        """Test that duplicate issues are properly deduplicated."""
        # Setup - create mock group
        mock_group = Mock()
        mock_group.id = 10
        mock_group.name = "Dev Team"
        
        # Setup current user with groups
        mock_current_user.groups = [mock_group]
        mock_redmine.user.get.return_value = mock_current_user
        
        # Create a mock issue that appears in both user and group results
        duplicate_issue = Mock()
        duplicate_issue.id = 789  # Same ID for both queries
        duplicate_issue.subject = "Duplicate Issue"
        duplicate_issue.description = "Duplicate issue description"
        duplicate_issue.project = Mock(id=1, name="Test Project")
        duplicate_issue.status = Mock(id=1, name="New")
        duplicate_issue.priority = Mock(id=2, name="Normal")
        duplicate_issue.author = Mock(id=1, name="Test Author")
        duplicate_issue.assigned_to = Mock(id=2, name="Test Assignee")
        duplicate_issue.created_on = Mock()
        duplicate_issue.created_on.isoformat.return_value = "2025-01-01T10:00:00"
        duplicate_issue.updated_on = Mock()
        duplicate_issue.updated_on.isoformat.return_value = "2025-01-02T15:30:00"
        
        # Both user and group queries return the same issue
        mock_redmine.issue.filter.return_value = [duplicate_issue]
        
        # Execute
        result = await list_my_redmine_issues()
        
        # Verify - should only appear once despite being returned by both queries
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == 789
        assert result[0]["subject"] == "Duplicate Issue"
