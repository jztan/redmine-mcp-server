"""
Test cases for redmine_handler.py MCP tools.

This module contains unit tests for the Redmine MCP server tools,
including tests for project listing and issue retrieval functionality.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch
from typing import Dict, Any, List
import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from redmine_mcp_server.redmine_handler import get_redmine_issue, list_redmine_projects


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
