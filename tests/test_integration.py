"""
Integration tests for the Redmine MCP server.

This module contains integration tests that test the actual connection
to Redmine and the overall functionality of the MCP server.
"""
import pytest
import asyncio
import os
import sys
from unittest.mock import patch
import httpx

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from redmine_mcp_server.redmine_handler import redmine, REDMINE_URL


class TestRedmineIntegration:
    """Integration tests for Redmine connectivity."""

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    def test_redmine_connection(self):
        """Test actual connection to Redmine server."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")
        
        try:
            # Try to access projects - this will test authentication
            projects = redmine.project.all()
            assert projects is not None
            print(f"Successfully connected to Redmine. Found {len(list(projects))} projects.")
        except Exception as e:
            pytest.fail(f"Failed to connect to Redmine: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_projects_integration(self):
        """Integration test for listing projects."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")
        
        from redmine_mcp_server.redmine_handler import list_redmine_projects
        
        result = await list_redmine_projects()
        
        assert result is not None
        assert isinstance(result, list)
        
        if len(result) > 0:
            # Verify structure of first project
            project = result[0]
            assert "id" in project
            assert "name" in project
            assert "identifier" in project
            assert "description" in project
            assert "created_on" in project
            
            assert isinstance(project["id"], int)
            assert isinstance(project["name"], str)
            assert isinstance(project["identifier"], str)

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_issue_integration(self):
        """Integration test for getting an issue."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")
        
        from redmine_mcp_server.redmine_handler import get_redmine_issue
        
        # First, try to get any issue to test with
        try:
            # Get the first project and see if it has issues
            projects = redmine.project.all()
            if not projects:
                pytest.skip("No projects found for testing")
            
            # Try to find an issue in any project
            test_issue_id = None
            for project in projects:
                try:
                    issues = redmine.issue.filter(project_id=project.id, limit=1)
                    if issues:
                        test_issue_id = issues[0].id
                        break
                except:
                    continue
            
            if test_issue_id is None:
                pytest.skip("No issues found for testing")
            
            # Test getting the issue
            result = await get_redmine_issue(test_issue_id)
            
            assert result is not None
            assert "id" in result
            assert "subject" in result
            assert "project" in result
            assert "status" in result
            assert "priority" in result
            assert "author" in result
            
            assert result["id"] == test_issue_id
            assert isinstance(result["subject"], str)
            assert isinstance(result["project"], dict)
            assert isinstance(result["status"], dict)
            
        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_my_issues_integration(self):
        """Integration test for listing my issues."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")
        
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues
        
        try:
            # Test basic functionality
            result = await list_my_redmine_issues()
            
            assert result is not None
            assert isinstance(result, list)
            
            # If there are issues, check their structure
            if len(result) > 0 and "error" not in result[0]:
                issue = result[0]
                assert "id" in issue
                assert "subject" in issue
                assert "project" in issue
                assert "status" in issue
                assert "priority" in issue
                assert "author" in issue
                
                assert isinstance(issue["id"], int)
                assert isinstance(issue["subject"], str)
                assert isinstance(issue["project"], dict)
                assert isinstance(issue["status"], dict)
                assert isinstance(issue["priority"], dict)
                assert isinstance(issue["author"], dict)
                
                # Test assigned_to field (can be None for unassigned issues)
                if issue["assigned_to"] is not None:
                    assert isinstance(issue["assigned_to"], dict)
                    assert "id" in issue["assigned_to"]
                    assert "name" in issue["assigned_to"]
                
                print(f"Successfully retrieved {len(result)} issues assigned to current user.")
            else:
                print("No issues found for current user or client initialization error.")
                
        except Exception as e:
            pytest.fail(f"Integration test for list_my_redmine_issues failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_my_issues_with_filters_integration(self):
        """Integration test for listing issues with filters."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")
        
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues
        
        try:
            # Test with various filters
            result = await list_my_redmine_issues(
                status_id='open',
                limit=5,
                sort='updated_on:desc'
            )
            
            assert result is not None
            assert isinstance(result, list)
            assert len(result) <= 5  # Should respect limit
            
            # If there are multiple issues, check sorting
            if len(result) > 1 and "error" not in result[0]:
                # With sort='updated_on:desc', newer items should come first
                for i in range(len(result) - 1):
                    if result[i]["updated_on"] and result[i+1]["updated_on"]:
                        assert result[i]["updated_on"] >= result[i+1]["updated_on"], \
                            "Issues should be sorted by updated_on descending"
                
                print(f"Successfully retrieved {len(result)} filtered issues with sorting.")
            
        except Exception as e:
            pytest.fail(f"Integration test for filtered list_my_redmine_issues failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_my_issues_pagination_integration(self):
        """Integration test for pagination functionality."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")
        
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues
        
        try:
            # Get first page with small limit
            page1 = await list_my_redmine_issues(limit=2, offset=0)
            assert isinstance(page1, list)
            
            # Get second page
            page2 = await list_my_redmine_issues(limit=2, offset=2)
            assert isinstance(page2, list)
            
            # If both pages have results and no errors, they should be different
            if (len(page1) > 0 and "error" not in page1[0] and
                len(page2) > 0 and "error" not in page2[0]):
                
                # Issue IDs should be different between pages
                page1_ids = {issue["id"] for issue in page1}
                page2_ids = {issue["id"] for issue in page2}
                
                # There should be no overlap (assuming enough issues exist)
                overlap = page1_ids.intersection(page2_ids)
                assert len(overlap) == 0, f"Pages should not overlap, but found common IDs: {overlap}"
                
                print(f"Successfully tested pagination: Page 1 ({len(page1)} issues), Page 2 ({len(page2)} issues)")
            else:
                print("Insufficient issues for pagination testing or client initialization error.")
                
        except Exception as e:
            pytest.fail(f"Integration test for pagination failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_my_issues_with_invalid_filter_integration(self):
        """Integration test for listing issues with an invalid filter."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")
        
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues
        
        try:
            # Test with an invalid status_id
            result = await list_my_redmine_issues(status_id='invalid_status')
            
            assert result is not None
            assert isinstance(result, list)
            
            # The result should either be empty (no matches) or contain an error
            if len(result) > 0:
                # If there's a result, check if it's an error
                if "error" in result[0]:
                    print(f"Successfully handled invalid filter with error: {result[0]['error']}")
                else:
                    # If no error, it means the filter was silently ignored (valid behavior)
                    print("Invalid filter was silently ignored - no issues returned.")
            else:
                print("Successfully handled request with an invalid filter: no issues returned.")
            
        except Exception as e:
            pytest.fail(f"Integration test for list_my_redmine_issues with invalid filter failed: {e}")


class TestFastAPIIntegration:
    """Integration tests for the FastAPI server."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_fastapi_health(self):
        """Test that the FastAPI server can start and respond."""
        # This test would require the server to be running
        # For now, we'll test the app creation
        from redmine_mcp_server.main import app
        
        assert app is not None
        assert hasattr(app, 'router')

    @pytest.mark.integration
    def test_sse_endpoint_exists(self):
        """Test that the SSE endpoint is properly configured."""
        from redmine_mcp_server.main import app
        
        # Check that routes are configured
        route_paths = [route.path for route in app.router.routes if hasattr(route, 'path')]
        
        # Should have the SSE endpoint
        assert any('/sse' in path or path == '/sse' for path in route_paths), f"SSE endpoint not found. Available routes: {route_paths}"


@pytest.mark.integration
class TestEnvironmentConfiguration:
    """Test environment configuration and setup."""

    def test_environment_variables_loaded(self):
        """Test that environment variables are properly loaded."""
        from redmine_mcp_server.redmine_handler import REDMINE_URL, REDMINE_USERNAME, REDMINE_API_KEY
        
        # At least REDMINE_URL should be set for the server to work
        assert REDMINE_URL is not None, "REDMINE_URL should be configured"
        
        # Either username or API key should be set
        has_username = REDMINE_USERNAME is not None
        has_api_key = REDMINE_API_KEY is not None
        
        assert has_username or has_api_key, "Either REDMINE_USERNAME or REDMINE_API_KEY should be configured"

    def test_redmine_client_initialization(self):
        """Test that Redmine client is properly initialized."""
        from redmine_mcp_server.redmine_handler import redmine
        
        if redmine is None:
            pytest.skip("Redmine client not initialized - check your .env configuration")
        
        # Test that the client has expected attributes
        assert hasattr(redmine, 'project')
        assert hasattr(redmine, 'issue')


if __name__ == "__main__":
    # Run integration tests
    pytest.main([
        __file__,
        "-v",
        "-m", "integration",
        "--tb=short"
    ])
