"""
Integration tests for the Redmine MCP server.

This module contains integration tests that test the actual connection
to Redmine and the overall functionality of the MCP server.
"""

import os
import sys

import pytest

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import redmine, REDMINE_URL  # noqa: E402


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
            project_count = len(list(projects))
            print(f"Successfully connected to Redmine. Found {project_count} projects.")
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
                except Exception:
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

        from redmine_mcp_server.redmine_handler import (
            create_redmine_issue,
            update_redmine_issue,
        )

        # Pick the first available project
        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")
        project_id = projects[0].id

        try:
            # Create a new issue
            new_subject = "Integration Test Issue"
            issue = await create_redmine_issue(
                project_id, new_subject, "Created by integration test"
            )
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

        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
            create_redmine_issue,
        )
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
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as test_file:
                test_file.write("This is a test attachment for integration testing.\n")
                test_file.write("Created by the MCP Redmine integration test suite.\n")
                test_file_path = test_file.name

            try:
                # Create a new issue
                new_subject = "Integration Test Issue with Attachment"
                issue = await create_redmine_issue(
                    project_id, new_subject, "Testing attachment download functionality"
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

                with open(test_file_path, "rb") as f:
                    # Read file content
                    file_content = f.read()

                # Set content-type header for file upload
                headers["Content-Type"] = "application/octet-stream"

                # Upload file directly as binary data
                response = requests.post(
                    upload_url,
                    headers=headers,
                    data=file_content,
                    auth=auth,
                    params={"filename": os.path.basename(test_file_path)},
                )

                if response.status_code != 201:
                    skip_msg = (
                        f"Failed to upload attachment: "
                        f"{response.status_code} - {response.text}"
                    )
                    pytest.skip(skip_msg)

                upload_token = response.json()["upload"]["token"]

                # Now update the issue to include the attachment
                redmine.issue.update(
                    issue_id,
                    uploads=[
                        {
                            "token": upload_token,
                            "filename": os.path.basename(test_file_path),
                        }
                    ],
                )

                # Get the issue with attachments to find the attachment ID
                issue_with_attachments = redmine.issue.get(
                    issue_id, include=["attachments"]
                )
                if not issue_with_attachments.attachments:
                    pytest.skip("Failed to create attachment for testing")

                attachment_id = issue_with_attachments.attachments[0].id

            finally:
                # Clean up the temporary file
                if os.path.exists(test_file_path):
                    os.unlink(test_file_path)

            # Now test downloading the attachment
            result = await get_redmine_attachment_download_url(attachment_id)

            # Test the API format (HTTP download URLs)
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
            attachments_dir = "attachments"
            if os.path.exists(attachments_dir):
                # Check that some file was created (UUID directory structure)
                has_files = any(
                    os.path.isdir(os.path.join(attachments_dir, item))
                    for item in os.listdir(attachments_dir)
                )
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

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_wiki_page_lifecycle_integration(self):
        """Integration test for creating, updating, and deleting a wiki page."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import (
            create_redmine_wiki_page,
            update_redmine_wiki_page,
            delete_redmine_wiki_page,
            get_redmine_wiki_page,
        )

        # Pick the first available project
        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        project_id = projects[0].identifier
        wiki_title = "Integration_Test_Wiki_Page"

        try:
            # 1. Create a new wiki page
            create_result = await create_redmine_wiki_page(
                project_id=project_id,
                wiki_page_title=wiki_title,
                text="# Integration Test\n\nCreated by integration tests.",
                comments="Initial creation by integration test",
            )

            # Check for permission errors (some projects may not allow wiki editing)
            if "error" in create_result:
                if (
                    "denied" in create_result["error"].lower()
                    or "permission" in create_result["error"].lower()
                    or "forbidden" in create_result["error"].lower()
                ):
                    pytest.skip(f"Wiki editing not permitted: {create_result['error']}")
                pytest.fail(f"Failed to create wiki page: {create_result['error']}")

            assert create_result["title"] == wiki_title
            assert "Integration Test" in create_result["text"]
            assert create_result["version"] == 1

            # 2. Verify the page was created by reading it
            read_result = await get_redmine_wiki_page(
                project_id=project_id,
                wiki_page_title=wiki_title,
            )
            assert "error" not in read_result
            assert read_result["title"] == wiki_title

            # 3. Update the wiki page
            update_result = await update_redmine_wiki_page(
                project_id=project_id,
                wiki_page_title=wiki_title,
                text="# Integration Test Updated\n\nUpdated by integration tests.",
                comments="Updated by integration test",
            )

            if "error" in update_result:
                pytest.fail(f"Failed to update wiki page: {update_result['error']}")

            assert update_result["title"] == wiki_title
            assert "Updated" in update_result["text"]
            assert update_result["version"] >= 2  # Version should increment

            # 4. Delete the wiki page
            delete_result = await delete_redmine_wiki_page(
                project_id=project_id,
                wiki_page_title=wiki_title,
            )

            if "error" in delete_result:
                pytest.fail(f"Failed to delete wiki page: {delete_result['error']}")

            assert delete_result["success"] is True
            assert delete_result["title"] == wiki_title

            # 5. Verify the page was deleted
            verify_result = await get_redmine_wiki_page(
                project_id=project_id,
                wiki_page_title=wiki_title,
            )
            assert "error" in verify_result
            assert "not found" in verify_result["error"].lower()

        except Exception as e:
            pytest.fail(f"Integration test failed: {e}")
        finally:
            # Clean up: attempt to delete the wiki page if it still exists
            try:
                await delete_redmine_wiki_page(
                    project_id=project_id,
                    wiki_page_title=wiki_title,
                )
            except Exception:
                pass  # Best effort cleanup

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_wiki_page_delete_not_found_integration(self):
        """Integration test for deleting a non-existent wiki page."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import delete_redmine_wiki_page

        # Pick the first available project
        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        project_id = projects[0].identifier
        nonexistent_title = "Nonexistent_Wiki_Page_Delete_Test_99999"

        # Test delete on non-existent page - should return error
        # Note: Redmine's wiki update API has upsert behavior (creates if not exists),
        # so we only test delete for "not found" errors
        delete_result = await delete_redmine_wiki_page(
            project_id=project_id,
            wiki_page_title=nonexistent_title,
        )
        assert "error" in delete_result
        assert "not found" in delete_result["error"].lower()


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
        assert hasattr(app, "router")

    @pytest.mark.integration
    def test_mcp_endpoint_exists(self):
        """Test that the MCP endpoint is properly configured."""
        from redmine_mcp_server.main import app

        # Check that routes are configured
        route_paths = [
            route.path for route in app.router.routes if hasattr(route, "path")
        ]

        # Should have the MCP endpoint (replaced SSE)
        assert (
            "/mcp" in route_paths
        ), f"MCP endpoint not found. Available routes: {route_paths}"

    @pytest.mark.integration
    def test_health_endpoint_exists(self):
        """Test that the health check endpoint is configured."""
        from redmine_mcp_server.main import app

        route_paths = [
            route.path for route in app.router.routes if hasattr(route, "path")
        ]

        assert (
            "/health" in route_paths
        ), f"Health endpoint not found. Available routes: {route_paths}"


class TestListRedmineIssuesIntegration:
    """Integration tests for list_redmine_issues tool."""

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_by_project(self):
        """Test listing issues filtered by project_id."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        project_id = projects[0].id
        result = await list_redmine_issues(project_id=project_id)

        assert isinstance(result, list)
        # All returned issues should belong to the requested project
        for issue in result:
            if "error" in issue:
                pytest.fail(f"API error: {issue['error']}")
            assert issue["project"]["id"] == project_id

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_by_string_identifier(self):
        """Test listing issues using a string project identifier."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        identifier = projects[0].identifier
        result = await list_redmine_issues(project_id=identifier)

        assert isinstance(result, list)
        # Should not return errors
        for issue in result:
            assert "error" not in issue

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_no_filters(self):
        """Test listing issues without any filters returns results."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        result = await list_redmine_issues()

        assert isinstance(result, list)

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_with_limit(self):
        """Test that limit parameter caps the result count."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        result = await list_redmine_issues(limit=3)

        assert isinstance(result, list)
        assert len(result) <= 3

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_pagination(self):
        """Test pagination with offset returns different results."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        page1 = await list_redmine_issues(limit=5, offset=0)
        page2 = await list_redmine_issues(limit=5, offset=5)

        assert isinstance(page1, list)
        assert isinstance(page2, list)

        # If both pages have results, their IDs should not overlap
        if page1 and page2:
            page1_ids = {issue["id"] for issue in page1 if "id" in issue}
            page2_ids = {issue["id"] for issue in page2 if "id" in issue}
            assert page1_ids.isdisjoint(page2_ids), "Pages should not overlap"

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_with_pagination_info(self):
        """Test include_pagination_info returns metadata."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        result = await list_redmine_issues(
            limit=5, offset=0, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result
        assert isinstance(result["issues"], list)

        pagination = result["pagination"]
        assert "total" in pagination
        assert "limit" in pagination
        assert "offset" in pagination
        assert "has_next" in pagination
        assert "has_previous" in pagination
        assert pagination["limit"] == 5
        assert pagination["offset"] == 0
        assert pagination["has_previous"] is False

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_with_status_filter(self):
        """Test filtering by status_id."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        # status_id=1 is typically "New" in Redmine
        result = await list_redmine_issues(status_id=1, limit=10)

        assert isinstance(result, list)
        for issue in result:
            if "error" not in issue:
                assert issue["status"]["id"] == 1

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_with_sort(self):
        """Test sorting issues by updated_on descending."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        result = await list_redmine_issues(sort="updated_on:desc", limit=10)

        assert isinstance(result, list)
        # Verify ordering: each updated_on should be >= the next
        dates = [
            issue["updated_on"]
            for issue in result
            if "updated_on" in issue and issue["updated_on"]
        ]
        assert dates == sorted(dates, reverse=True)

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_field_selection(self):
        """Test field selection returns only requested fields."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        result = await list_redmine_issues(limit=5, fields=["id", "subject", "status"])

        assert isinstance(result, list)
        for issue in result:
            if "error" not in issue:
                assert "id" in issue
                assert "subject" in issue
                assert "status" in issue
                assert "description" not in issue
                assert "author" not in issue

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_combined_project_and_status(self):
        """Test combining project_id and status_id filters."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        project_id = projects[0].id
        # status_id=1 is typically "New"
        result = await list_redmine_issues(project_id=project_id, status_id=1, limit=10)

        assert isinstance(result, list)
        for issue in result:
            if "error" in issue:
                pytest.fail(f"API error: {issue['error']}")
            assert issue["project"]["id"] == project_id
            assert issue["status"]["id"] == 1

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_combined_filters_with_sort_and_pagination(self):
        """Test multiple filters combined with sort and pagination info."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        project_id = projects[0].id
        result = await list_redmine_issues(
            project_id=project_id,
            status_id=1,
            sort="updated_on:desc",
            limit=5,
            offset=0,
            include_pagination_info=True,
        )

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result

        for issue in result["issues"]:
            assert issue["project"]["id"] == project_id
            assert issue["status"]["id"] == 1

        # Verify sort order
        dates = [
            issue["updated_on"] for issue in result["issues"] if issue.get("updated_on")
        ]
        assert dates == sorted(dates, reverse=True)

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_combined_filters_with_fields(self):
        """Test combined filters with field selection."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        project_id = projects[0].id
        result = await list_redmine_issues(
            project_id=project_id,
            status_id=1,
            limit=5,
            fields=["id", "subject", "status", "project"],
        )

        assert isinstance(result, list)
        for issue in result:
            assert "id" in issue
            assert "subject" in issue
            assert "status" in issue
            assert "project" in issue
            assert "description" not in issue
            assert "author" not in issue
            assert issue["project"]["id"] == project_id
            assert issue["status"]["id"] == 1

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_issue_structure(self):
        """Test that returned issues have expected field structure."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        result = await list_redmine_issues(limit=1)

        assert isinstance(result, list)
        if not result:
            pytest.skip("No issues found for testing")

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
        assert "id" in issue["project"]
        assert "name" in issue["project"]

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_issues_assigned_to_me(self):
        """Test filtering by assigned_to_id='me'."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_issues

        result = await list_redmine_issues(assigned_to_id="me", limit=10)

        assert isinstance(result, list)
        # Should not return errors
        for issue in result:
            assert "error" not in issue

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_my_issues_backward_compatible(self):
        """Test list_my_redmine_issues still works as a wrapper."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import (
            list_redmine_issues,
            list_my_redmine_issues,
        )

        # Both should return the same results
        new_result = await list_redmine_issues(assigned_to_id="me", limit=10)
        old_result = await list_my_redmine_issues(limit=10)

        assert isinstance(new_result, list)
        assert isinstance(old_result, list)

        # Same issue IDs should be returned
        new_ids = {issue["id"] for issue in new_result if "id" in issue}
        old_ids = {issue["id"] for issue in old_result if "id" in issue}
        assert new_ids == old_ids


@pytest.mark.integration
class TestEnvironmentConfiguration:
    """Test environment configuration and setup."""

    def test_environment_variables_loaded(self):
        """Test that environment variables are properly loaded."""
        from redmine_mcp_server.redmine_handler import (
            REDMINE_URL,
            REDMINE_USERNAME,
            REDMINE_API_KEY,
        )

        if REDMINE_URL is None:
            pytest.skip("REDMINE_URL not configured")

        # At least REDMINE_URL should be set for the server to work
        assert REDMINE_URL is not None, "REDMINE_URL should be configured"

        # Either username or API key should be set
        has_username = REDMINE_USERNAME is not None
        has_api_key = REDMINE_API_KEY is not None

        assert (
            has_username or has_api_key
        ), "Either REDMINE_USERNAME or REDMINE_API_KEY should be configured"

    def test_redmine_client_initialization(self):
        """Test that Redmine client is properly initialized."""
        from redmine_mcp_server.redmine_handler import redmine

        if redmine is None:
            pytest.skip(
                "Redmine client not initialized - check your .env configuration"
            )

        # Test that the client has expected attributes
        assert hasattr(redmine, "project")
        assert hasattr(redmine, "issue")


class TestListRedmineVersionsIntegration:
    """Integration tests for list_redmine_versions tool."""

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_versions_by_project_id(self):
        """Test listing versions for a project by numeric ID."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_versions

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        project_id = projects[0].id
        result = await list_redmine_versions(project_id=project_id)

        assert isinstance(result, list)
        for version in result:
            if "error" in version:
                pytest.fail(f"API error: {version['error']}")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_versions_by_string_identifier(self):
        """Test listing versions using a string project identifier."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_versions

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        identifier = projects[0].identifier
        result = await list_redmine_versions(project_id=identifier)

        assert isinstance(result, list)
        for version in result:
            assert "error" not in version

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_versions_structure(self):
        """Test that returned version dicts have expected keys."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_versions

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        result = await list_redmine_versions(project_id=projects[0].id)

        assert isinstance(result, list)
        if not result:
            pytest.skip("No versions found in first project")

        version = result[0]
        expected_keys = {
            "id",
            "name",
            "description",
            "status",
            "due_date",
            "sharing",
            "wiki_page_title",
            "project",
            "created_on",
            "updated_on",
        }
        assert set(version.keys()) == expected_keys
        assert isinstance(version["id"], int)
        assert isinstance(version["name"], str)
        assert version["status"] in ("open", "locked", "closed")

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_versions_filter_open(self):
        """Test filtering versions by open status."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_versions

        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available for testing")

        result = await list_redmine_versions(
            project_id=projects[0].id, status_filter="open"
        )

        assert isinstance(result, list)
        for version in result:
            assert "error" not in version
            assert version["status"] == "open"

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_versions_invalid_status_filter(self):
        """Test that invalid status_filter returns error without API call."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_versions

        result = await list_redmine_versions(project_id=1, status_filter="invalid")

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]
        assert "invalid" in result[0]["error"].lower()

    @pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_versions_nonexistent_project(self):
        """Test error handling for a project that doesn't exist."""
        if redmine is None:
            pytest.skip("Redmine client not initialized")

        from redmine_mcp_server.redmine_handler import list_redmine_versions

        result = await list_redmine_versions(project_id=999999)

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-m", "integration", "--tb=short"])
