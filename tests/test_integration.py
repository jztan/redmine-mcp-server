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

        from redmine_mcp_server.redmine_handler import download_redmine_attachment, create_redmine_issue
        import tempfile
        import os

        # Pick the first available project
        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")
        project_id = projects[0].id

        issue_id = None
        attachment_id = None

        try:
            # Create a test file to attach
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as test_file:
                test_file.write("This is a test attachment for integration testing.\n")
                test_file.write("Created by the MCP Redmine integration test suite.\n")
                test_file_path = test_file.name

            try:
                # Create a new issue
                new_subject = "Integration Test Issue with Attachment"
                issue = await create_redmine_issue(
                    project_id,
                    new_subject,
                    "Testing attachment download functionality"
                )
                assert issue and "id" in issue
                issue_id = issue["id"]

                # Upload the attachment to the issue
                # First, we need to upload the file to get a token
                import requests
                from requests.auth import HTTPBasicAuth

                upload_url = f"{REDMINE_URL}/uploads.json"

                # Use API key if available, otherwise use basic auth
                api_key = os.getenv("REDMINE_API_KEY")
                username = os.getenv("REDMINE_USERNAME")
                password = os.getenv("REDMINE_PASSWORD")

                if api_key:
                    headers = {"X-Redmine-API-Key": api_key}
                    auth = None
                else:
                    headers = {}
                    auth = HTTPBasicAuth(username, password)

                with open(test_file_path, 'rb') as f:
                    # Read file content
                    file_content = f.read()

                # Set content-type header for file upload
                headers['Content-Type'] = 'application/octet-stream'

                # Upload file directly as binary data
                response = requests.post(
                    upload_url,
                    headers=headers,
                    data=file_content,
                    auth=auth,
                    params={'filename': os.path.basename(test_file_path)}
                )

                if response.status_code != 201:
                    pytest.skip(f"Failed to upload attachment: {response.status_code} - {response.text}")

                upload_token = response.json()['upload']['token']

                # Now update the issue to include the attachment
                redmine.issue.update(
                    issue_id,
                    uploads=[{'token': upload_token, 'filename': os.path.basename(test_file_path)}]
                )

                # Get the issue with attachments to find the attachment ID
                issue_with_attachments = redmine.issue.get(issue_id, include=['attachments'])
                if not issue_with_attachments.attachments:
                    pytest.skip("Failed to create attachment for testing")

                attachment_id = issue_with_attachments.attachments[0].id

            finally:
                # Clean up the temporary file
                if os.path.exists(test_file_path):
                    os.unlink(test_file_path)

            # Now test downloading the attachment
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
            # Note: Due to security fix, files are always saved to default "attachments" directory
            # regardless of the save_dir parameter (which is deprecated and ignored)
            attachments_dir = "attachments"  # Always uses server default now
            if os.path.exists(attachments_dir):
                # Check that some file was created (UUID directory structure)
                has_files = any(os.path.isdir(os.path.join(attachments_dir, item))
                              for item in os.listdir(attachments_dir))
                assert has_files, "No attachment files were created"

        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")
        finally:
            # Clean up the created issue
            if issue_id:
                try:
                    redmine.issue.delete(issue_id)
                except Exception:
                    pass  # Best effort cleanup


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
