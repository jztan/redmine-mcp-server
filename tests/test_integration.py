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

from redmine_mcp_server.redmine_handler import redmine, REDMINE_URL, search_entire_redmine


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
        """Integration test for getting an issue with journals and attachments."""
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
            
            # Test getting the issue including journals and attachments by default
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
            assert "journals" in result
            assert isinstance(result["journals"], list)
            assert "attachments" in result
            assert isinstance(result["attachments"], list)
            
        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_issue_without_journals_integration(self):
        """Integration test for opting out of journal retrieval."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import get_redmine_issue

        try:
            projects = redmine.project.all()
            if not projects:
                pytest.skip("No projects found for testing")

            test_issue_id = None
            for project in projects:
                try:
                    issues = redmine.issue.filter(project_id=project.id, limit=1)
                    if issues:
                        test_issue_id = issues[0].id
                        break
                except Exception:
                    continue

            if test_issue_id is None:
                pytest.skip("No issues found for testing")

            result = await get_redmine_issue(test_issue_id, include_journals=False)

            assert result is not None
            assert "journals" not in result
            assert "attachments" in result
            assert isinstance(result["attachments"], list)

        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_issue_without_attachments_integration(self):
        """Integration test for opting out of attachment retrieval."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import get_redmine_issue

        try:
            projects = redmine.project.all()
            if not projects:
                pytest.skip("No projects found for testing")

            test_issue_id = None
            for project in projects:
                try:
                    issues = redmine.issue.filter(project_id=project.id, limit=1)
                    if issues:
                        test_issue_id = issues[0].id
                        break
                except Exception:
                    continue

            if test_issue_id is None:
                pytest.skip("No issues found for testing")

            result = await get_redmine_issue(test_issue_id, include_attachments=False)

            assert result is not None
            assert "attachments" not in result

        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_create_update_issue_integration(self):
        """Integration test for creating and updating an issue."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import create_redmine_issue, update_redmine_issue

        # Pick the first available project
        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")
        project_id = projects[0].id

        try:
            # Create a new issue
            new_subject = "Integration Test Issue"
            issue = await create_redmine_issue(project_id, new_subject, "Created by integration test")
            assert issue and "id" in issue
            issue_id = issue["id"]

            # Update the issue
            updated_subject = new_subject + " Updated"
            updated = await update_redmine_issue(issue_id, {"subject": updated_subject})
            assert updated["id"] == issue_id
            assert updated["subject"] == updated_subject
        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")
        finally:
            # Clean up the created issue if possible
            try:
                redmine.issue.delete(issue_id)
            except Exception as e:
                pytest.fail(f"Integration test failed: {e}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_download_attachment_integration(self, tmp_path):
        """Integration test for downloading an attachment."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import download_redmine_attachment

        attachment_id = None
        try:
            for project in redmine.project.all():
                try:
                    issues = redmine.issue.filter(project_id=project.id, include="attachments", limit=1)
                    if issues and getattr(issues[0], "attachments", []):
                        attachment_id = issues[0].attachments[0].id
                        break
                except Exception:
                    continue

            if attachment_id is None:
                pytest.skip("No attachments found for testing")

            result = await download_redmine_attachment(attachment_id, str(tmp_path))

            # Test the current API format (HTTP download URLs, not file paths)
            assert "download_url" in result
            assert "filename" in result
            assert "content_type" in result
            assert "size" in result
            assert "expires_at" in result
            assert "attachment_id" in result
            assert result["attachment_id"] == attachment_id

            # Verify the download URL is properly formatted
            assert result["download_url"].startswith("http")
            assert "/files/" in result["download_url"]

            # Verify file was actually downloaded to the attachments directory
            # (The API creates files in UUID-based directories for security)
            attachments_dir = tmp_path if str(tmp_path) != "attachments" else "attachments"
            if os.path.exists(attachments_dir):
                # Check that some file was created (UUID directory structure)
                has_files = any(os.path.isdir(os.path.join(attachments_dir, item))
                              for item in os.listdir(attachments_dir))
                assert has_files, "No attachment files were created"

        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")


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
    def test_mcp_endpoint_exists(self):
        """Test that the MCP endpoint is properly configured."""
        from redmine_mcp_server.main import app

        # Check that routes are configured
        route_paths = [route.path for route in app.router.routes if hasattr(route, 'path')]

        # Should have the MCP endpoint (replaced SSE)
        assert '/mcp' in route_paths, f"MCP endpoint not found. Available routes: {route_paths}"

    @pytest.mark.integration
    def test_health_endpoint_exists(self):
        """Test that the health check endpoint is configured."""
        from redmine_mcp_server.main import app

        route_paths = [route.path for route in app.router.routes if hasattr(route, 'path')]

        assert '/health' in route_paths, f"Health endpoint not found. Available routes: {route_paths}"


@pytest.mark.integration
class TestSearchIntegration:
    """Integration tests for the new global search functionality."""

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.asyncio
    async def test_search_entire_redmine_basic(self):
        """Test basic search against real Redmine server."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        result = await search_entire_redmine("project")

        assert "error" not in result
        assert "results" in result
        assert "total_count" in result
        assert "query" in result
        assert result["query"] == "project"
        print(f"Search returned {result['total_count']} results")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.asyncio
    async def test_search_entire_redmine_pagination(self):
        """Test pagination with real server."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        # Get first page
        result1 = await search_entire_redmine("test", limit=5, offset=0)

        assert "error" not in result1

        # Get second page if results exist
        if result1["total_count"] > 5:
            result2 = await search_entire_redmine("test", limit=5, offset=5)
            assert "error" not in result2
            # Results should be different (different offset)
            # Note: We can't guarantee different content but structure should be same
            assert "results" in result2

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.asyncio
    async def test_search_entire_redmine_resource_filtering(self):
        """Test resource type filtering."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        result = await search_entire_redmine("test", resource_types=["issues"])

        assert "error" not in result
        # All results should be issues if any results exist
        if result["results"]:
            for item in result["results"]:
                assert item["type"] == "issues"

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.asyncio
    async def test_search_entire_redmine_empty_query(self):
        """Test search with empty or non-matching query."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        result = await search_entire_redmine("xyznonexistentquery123")

        assert "error" not in result
        # Should handle empty results gracefully
        assert result["total_count"] >= 0
        assert result["results"] == []

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.asyncio
    async def test_search_entire_redmine_multiple_types(self):
        """Test search across multiple resource types."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        result = await search_entire_redmine("project", resource_types=["issues", "projects"])

        assert "error" not in result
        # Verify results structure
        assert "results_by_type" in result
        # Should only have results from requested types if any results exist
        if result["results"]:
            for item in result["results"]:
                assert item["type"] in ["issues", "projects"]


@pytest.mark.integration
class TestEnvironmentConfiguration:
    """Test environment configuration and setup."""

    def test_environment_variables_loaded(self):
        """Test that environment variables are properly loaded."""
        from redmine_mcp_server.redmine_handler import REDMINE_URL, REDMINE_USERNAME, REDMINE_API_KEY

        if REDMINE_URL is None:
            pytest.skip("REDMINE_URL not configured")

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
