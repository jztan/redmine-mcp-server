"""
Unit tests for RedmineTools class - easily testable with mocked clients.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.redmine_mcp_server.redmine_tools import RedmineTools, get_redmine_client


def create_mock_issue():
    """Helper to create a properly configured mock issue."""
    mock_issue = Mock()
    mock_issue.id = 1
    mock_issue.subject = "Test Issue"
    mock_issue.description = "Test description"
    
    mock_project = Mock()
    mock_project.id = 1
    mock_project.name = "Test Project"
    mock_issue.project = mock_project
    
    mock_status = Mock()
    mock_status.id = 1
    mock_status.name = "New"
    mock_issue.status = mock_status
    
    mock_priority = Mock()
    mock_priority.id = 1
    mock_priority.name = "Normal"
    mock_issue.priority = mock_priority
    
    mock_author = Mock()
    mock_author.id = 1
    mock_author.name = "Test User"
    mock_issue.author = mock_author
    
    mock_issue.assigned_to = None
    mock_issue.created_on = datetime(2023, 1, 1, 12, 0, 0)
    mock_issue.updated_on = datetime(2023, 1, 2, 12, 0, 0)
    
    return mock_issue


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_issue():
    """Test get_issue with mocked client."""
    mock_client = Mock()
    mock_issue = create_mock_issue()
    mock_client.issue.get.return_value = mock_issue
    
    tools = RedmineTools(mock_client)
    result = await tools.get_redmine_issue(1)
    
    assert result["id"] == 1
    assert result["subject"] == "Test Issue"
    assert result["description"] == "Test description"
    assert result["project"]["name"] == "Test Project"
    assert result["status"]["name"] == "New"
    mock_client.issue.get.assert_called_once_with(1, include="journals,attachments")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_issue_without_journals_attachments():
    """Test get_issue with journals and attachments disabled."""
    mock_client = Mock()
    mock_issue = Mock()
    mock_issue.id = 1
    mock_issue.subject = "Test Issue"
    mock_issue.description = "Test description"
    mock_issue.project = Mock(id=1, name="Test Project")
    mock_issue.status = Mock(id=1, name="New")
    mock_issue.priority = Mock(id=1, name="Normal")
    mock_issue.author = Mock(id=1, name="Test User")
    mock_issue.assigned_to = None
    mock_issue.created_on = datetime(2023, 1, 1, 12, 0, 0)
    mock_issue.updated_on = datetime(2023, 1, 2, 12, 0, 0)
    
    mock_client.issue.get.return_value = mock_issue
    
    tools = RedmineTools(mock_client)
    result = await tools.get_redmine_issue(1, include_journals=False, include_attachments=False)
    
    assert result["id"] == 1
    assert result["subject"] == "Test Issue"
    mock_client.issue.get.assert_called_once_with(1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_projects():
    """Test list_projects with mocked client."""
    mock_client = Mock()
    mock_project = Mock()
    mock_project.id = 1
    mock_project.name = "Test Project"
    mock_project.identifier = "test-project"
    mock_project.description = "A test project"
    mock_project.created_on = datetime(2023, 1, 1, 12, 0, 0)
    
    mock_client.project.all.return_value = [mock_project]
    
    tools = RedmineTools(mock_client)
    result = await tools.list_redmine_projects()
    
    assert len(result) == 1
    assert result[0]["name"] == "Test Project"
    assert result[0]["identifier"] == "test-project"
    assert result[0]["description"] == "A test project"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_my_issues():
    """Test list_my_issues with mocked client."""
    mock_client = Mock()
    mock_issue = create_mock_issue()
    mock_issue.subject = "My Issue"
    mock_issue.description = "Issue assigned to me"
    
    # Fix the assigned_to mock
    mock_assigned = Mock()
    mock_assigned.id = 2
    mock_assigned.name = "Me"
    mock_issue.assigned_to = mock_assigned
    
    mock_client.issue.filter.return_value = [mock_issue]
    
    tools = RedmineTools(mock_client)
    result = await tools.list_my_redmine_issues(project_id=1)
    
    assert len(result) == 1
    assert result[0]["subject"] == "My Issue"
    assert result[0]["assigned_to"]["name"] == "Me"
    mock_client.issue.filter.assert_called_once_with(assigned_to_id="me", project_id=1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_issues():
    """Test search_issues with mocked client."""
    mock_client = Mock()
    mock_issue = Mock()
    mock_issue.id = 1
    mock_issue.subject = "Search Result"
    mock_issue.description = "Found issue"
    mock_issue.project = Mock(id=1, name="Test Project")
    mock_issue.status = Mock(id=1, name="New")
    mock_issue.priority = Mock(id=1, name="Normal")
    mock_issue.author = Mock(id=1, name="Test User")
    mock_issue.assigned_to = None
    mock_issue.created_on = datetime(2023, 1, 1, 12, 0, 0)
    mock_issue.updated_on = datetime(2023, 1, 2, 12, 0, 0)
    
    mock_client.issue.search.return_value = [mock_issue]
    
    tools = RedmineTools(mock_client)
    result = await tools.search_redmine_issues("test query")
    
    assert len(result) == 1
    assert result[0]["subject"] == "Search Result"
    mock_client.issue.search.assert_called_once_with("test query")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_issue():
    """Test create_issue with mocked client."""
    mock_client = Mock()
    mock_issue = Mock()
    mock_issue.id = 1
    mock_issue.subject = "New Issue"
    mock_issue.description = "Created issue"
    mock_issue.project = Mock(id=1, name="Test Project")
    mock_issue.status = Mock(id=1, name="New")
    mock_issue.priority = Mock(id=1, name="Normal")
    mock_issue.author = Mock(id=1, name="Test User")
    mock_issue.assigned_to = None
    mock_issue.created_on = datetime(2023, 1, 1, 12, 0, 0)
    mock_issue.updated_on = datetime(2023, 1, 2, 12, 0, 0)
    
    mock_client.issue.create.return_value = mock_issue
    
    tools = RedmineTools(mock_client)
    result = await tools.create_redmine_issue(1, "New Issue", "Created issue")
    
    assert result["id"] == 1
    assert result["subject"] == "New Issue"
    mock_client.issue.create.assert_called_once_with(
        project_id=1, subject="New Issue", description="Created issue"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_issue():
    """Test update_issue with mocked client."""
    mock_client = Mock()
    mock_issue = Mock()
    mock_issue.id = 1
    mock_issue.subject = "Updated Issue"
    mock_issue.description = "Updated description"
    mock_issue.project = Mock(id=1, name="Test Project")
    mock_issue.status = Mock(id=2, name="In Progress")
    mock_issue.priority = Mock(id=1, name="Normal")
    mock_issue.author = Mock(id=1, name="Test User")
    mock_issue.assigned_to = None
    mock_issue.created_on = datetime(2023, 1, 1, 12, 0, 0)
    mock_issue.updated_on = datetime(2023, 1, 2, 12, 0, 0)
    
    mock_client.issue.get.return_value = mock_issue
    
    tools = RedmineTools(mock_client)
    result = await tools.update_redmine_issue(1, {"subject": "Updated Issue"})
    
    assert result["subject"] == "Updated Issue"
    mock_client.issue.update.assert_called_once_with(1, subject="Updated Issue")
    mock_client.issue.get.assert_called_once_with(1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_issue_with_status_name():
    """Test update_issue with status_name conversion."""
    mock_client = Mock()
    mock_status = Mock()
    mock_status.id = 2
    mock_status.name = "In Progress"
    
    mock_client.issue_status.all.return_value = [mock_status]
    
    mock_issue = create_mock_issue()
    mock_issue.subject = "Updated Issue"
    mock_issue.description = "Updated description"
    
    # Fix the status mock for the updated issue
    mock_updated_status = Mock()
    mock_updated_status.id = 2
    mock_updated_status.name = "In Progress"
    mock_issue.status = mock_updated_status
    
    mock_client.issue.get.return_value = mock_issue
    
    tools = RedmineTools(mock_client)
    result = await tools.update_redmine_issue(1, {"status_name": "in progress"})
    
    assert result["status"]["name"] == "In Progress"
    mock_client.issue.update.assert_called_once_with(1, status_id=2)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_download_attachment():
    """Test download_attachment with mocked client."""
    mock_client = Mock()
    mock_attachment = Mock()
    mock_attachment.download.return_value = "/tmp/test_file.pdf"
    
    mock_client.attachment.get.return_value = mock_attachment
    
    tools = RedmineTools(mock_client)
    result = await tools.download_redmine_attachment(1, "/tmp")
    
    assert result["file_path"] == "/tmp/test_file.pdf"
    mock_client.attachment.get.assert_called_once_with(1)
    mock_attachment.download.assert_called_once_with(savepath="/tmp")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_client_unavailable():
    """Test error handling when client is unavailable."""
    tools = RedmineTools(None)
    
    result = await tools.get_redmine_issue(1)
    assert "error" in result
    assert "not initialized" in result["error"]
    
    result = await tools.list_redmine_projects()
    assert isinstance(result, list)
    assert len(result) == 1
    assert "error" in result[0]
    assert "not initialized" in result[0]["error"]
    
    result = await tools.list_my_redmine_issues()
    assert isinstance(result, list)
    assert len(result) == 1
    assert "error" in result[0]
    assert "not initialized" in result[0]["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_project_status():
    """Test project status summary with mocked client."""
    mock_client = Mock()
    
    # Mock project
    mock_project = Mock()
    mock_project.id = 1
    mock_project.name = "Test Project"
    mock_project.identifier = "test-project"
    mock_client.project.get.return_value = mock_project
    
    # Mock issues
    mock_issue1 = Mock()
    mock_issue1.status = Mock(name="New")
    mock_issue1.priority = Mock(name="High")
    mock_issue1.assigned_to = None
    
    mock_issue2 = Mock()
    mock_issue2.status = Mock(name="In Progress")
    mock_issue2.priority = Mock(name="Normal")
    mock_issue2.assigned_to = Mock(name="User1")
    
    # Mock filter calls for different date ranges
    mock_client.issue.filter.side_effect = [
        [mock_issue1],  # created issues
        [mock_issue1, mock_issue2],  # updated issues  
        [mock_issue1, mock_issue2]  # all issues
    ]
    
    tools = RedmineTools(mock_client)
    result = await tools.summarize_project_status(1, 30)
    
    assert result["project"]["name"] == "Test Project"
    assert result["recent_activity"]["issues_created"] == 1
    assert result["recent_activity"]["issues_updated"] == 2
    assert result["project_totals"]["total_issues"] == 2
    assert "insights" in result
    assert "daily_creation_rate" in result["insights"]


@pytest.mark.unit
def test_get_redmine_client_with_api_key():
    """Test get_redmine_client with API key."""
    with patch.dict("os.environ", {
        "REDMINE_URL": "http://test.redmine.com",
        "REDMINE_API_KEY": "test_api_key"
    }):
        with patch("src.redmine_mcp_server.redmine_tools.Redmine") as mock_redmine:
            mock_instance = Mock()
            mock_redmine.return_value = mock_instance
            
            client = get_redmine_client()
            
            assert client == mock_instance
            mock_redmine.assert_called_once_with("http://test.redmine.com", key="test_api_key")


@pytest.mark.unit
def test_get_redmine_client_with_username_password():
    """Test get_redmine_client with username/password."""
    with patch.dict("os.environ", {
        "REDMINE_URL": "http://test.redmine.com",
        "REDMINE_USERNAME": "testuser",
        "REDMINE_PASSWORD": "testpass"
    }, clear=True):
        with patch("src.redmine_mcp_server.redmine_tools.Redmine") as mock_redmine:
            mock_instance = Mock()
            mock_redmine.return_value = mock_instance
            
            client = get_redmine_client()
            
            assert client == mock_instance
            mock_redmine.assert_called_once_with(
                "http://test.redmine.com", 
                username="testuser", 
                password="testpass"
            )


@pytest.mark.unit
@patch('src.redmine_mcp_server.redmine_tools.load_dotenv')
@patch.dict('os.environ', {}, clear=True)
def test_get_redmine_client_missing_credentials(mock_load_dotenv):
    """Test get_redmine_client with missing credentials."""
    # Set only URL, no credentials
    with patch.dict('os.environ', {"REDMINE_URL": "http://test.redmine.com"}):
        client = get_redmine_client()
        assert client is None


@pytest.mark.unit
@patch('src.redmine_mcp_server.redmine_tools.load_dotenv')
@patch.dict('os.environ', {}, clear=True)
def test_get_redmine_client_missing_url(mock_load_dotenv):
    """Test get_redmine_client with missing URL."""
    # Set only API key, no URL
    with patch.dict('os.environ', {"REDMINE_API_KEY": "test_key"}):
        client = get_redmine_client()
        assert client is None