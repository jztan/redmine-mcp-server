"""
Integration tests for AgentCore server - direct HTTP testing.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock

from src.redmine_mcp_server.agentcore_server import app


@pytest.mark.unit
def test_health_endpoint():
    """Test health endpoint responds correctly."""
    client = TestClient(app)
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "agentcore"
    assert "redmine_connected" in data


@pytest.mark.unit
def test_mcp_tools_list():
    """Test MCP tools/list endpoint."""
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert "result" in data
    assert "tools" in data["result"]
    
    tools = data["result"]["tools"]
    assert len(tools) > 0
    
    # Check that all expected tools are present
    tool_names = [tool["name"] for tool in tools]
    expected_tools = [
        "get_redmine_issue",
        "list_redmine_projects", 
        "list_my_redmine_issues",
        "search_redmine_issues",
        "create_redmine_issue",
        "update_redmine_issue",
        "download_redmine_attachment",
        "summarize_project_status"
    ]
    
    for expected_tool in expected_tools:
        assert expected_tool in tool_names


@pytest.mark.unit
def test_mcp_unknown_method():
    """Test MCP endpoint with unknown method."""
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "unknown/method",
        "id": 1
    })
    
    assert response.status_code == 400


@pytest.mark.unit
def test_mcp_unknown_tool():
    """Test MCP tools/call with unknown tool."""
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "unknown_tool"
        },
        "id": 2
    })
    
    assert response.status_code == 400


@pytest.mark.unit
@patch('src.redmine_mcp_server.agentcore_server.tools')
def test_mcp_tool_call_success(mock_tools):
    """Test successful tool invocation."""
    # Mock the tool method
    mock_tools.list_redmine_projects.return_value = [
        {"id": 1, "name": "Test Project", "identifier": "test"}
    ]
    
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "list_redmine_projects"
        },
        "id": 2
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 2
    assert "result" in data
    assert len(data["result"]) == 1
    assert data["result"][0]["name"] == "Test Project"


@pytest.mark.unit
@patch('src.redmine_mcp_server.agentcore_server.tools')
def test_mcp_tool_call_with_arguments(mock_tools):
    """Test tool invocation with arguments."""
    # Mock the tool method
    mock_tools.get_redmine_issue.return_value = {
        "id": 123,
        "subject": "Test Issue",
        "description": "Test description"
    }
    
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_redmine_issue",
            "arguments": {
                "issue_id": 123,
                "include_journals": False
            }
        },
        "id": 3
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 3
    assert "result" in data
    assert data["result"]["id"] == 123
    assert data["result"]["subject"] == "Test Issue"
    
    # Verify the method was called with correct arguments
    mock_tools.get_redmine_issue.assert_called_once_with(
        issue_id=123, include_journals=False
    )


@pytest.mark.unit
@patch('src.redmine_mcp_server.agentcore_server.tools')
def test_mcp_tool_call_error_handling(mock_tools):
    """Test tool error handling."""
    # Mock the tool method to raise an exception
    mock_tools.get_redmine_issue.side_effect = Exception("Test error")
    
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_redmine_issue",
            "arguments": {"issue_id": 123}
        },
        "id": 4
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0" 
    assert data["id"] == 4
    assert "error" in data
    assert data["error"]["code"] == -32603
    assert "Test error" in data["error"]["data"]


@pytest.mark.unit
def test_mcp_invalid_json():
    """Test MCP endpoint with invalid JSON."""
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        # Missing required fields
        "id": 5
    })
    
    # FastAPI should handle this as a validation error
    assert response.status_code in [400, 422]


@pytest.mark.integration
def test_mcp_tool_call_real_client():
    """Test actual tool invocation with real Redmine client (requires server)."""
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "list_redmine_projects"
        },
        "id": 6
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 6
    assert "result" in data
    
    # Result should either be projects list or error message
    result = data["result"]
    if isinstance(result, list):
        if len(result) > 0:
            # If projects exist, check structure
            if "error" not in result[0]:
                assert "id" in result[0]
                assert "name" in result[0]
        else:
            # Empty list is valid (no projects)
            pass
    else:
        # Single error dict
        assert "error" in result


@pytest.mark.integration  
def test_mcp_get_issue_real_client():
    """Test get_issue with real client (may fail gracefully if no server)."""
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_redmine_issue",
            "arguments": {"issue_id": 1}
        },
        "id": 7
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 7
    assert "result" in data
    
    # Should get either issue data or error message
    result = data["result"]
    if "error" in result:
        # Expected if no Redmine server configured
        assert isinstance(result["error"], str)
    else:
        # If successful, should have issue structure
        assert "id" in result
        assert "subject" in result


@pytest.mark.integration
def test_mcp_search_issues_real_client():
    """Test search_issues with real client."""
    client = TestClient(app)
    response = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "search_redmine_issues",
            "arguments": {"query": "test"}
        },
        "id": 8
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 8
    assert "result" in data
    
    # Should get either search results or error
    result = data["result"]
    if isinstance(result, list):
        if len(result) > 0 and "error" not in result[0]:
            # If issues found, check structure
            assert "id" in result[0]
            assert "subject" in result[0]
    else:
        # Single error response
        assert "error" in result