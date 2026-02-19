"""
Test cases for redmine_handler.py MCP tools.

This module contains unit tests for the Redmine MCP server tools,
including tests for project listing and issue retrieval functionality.
"""

import os
import sys
import uuid

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock, mock_open

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    get_redmine_issue,
    list_redmine_projects,
    summarize_project_status,
    _analyze_issues,
)
from redminelib.exceptions import ResourceNotFoundError  # noqa: E402


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

        # Mock custom fields (e.g., Agile plugin "Size")
        custom_field = Mock()
        custom_field.id = 12
        custom_field.name = "Size"
        custom_field.value = "S"
        mock_issue.custom_fields = [custom_field]

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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_issue_success(
        self, mock_redmine, mock_issue_with_comments
    ):
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
        mock_redmine.issue.get.assert_called_once_with(
            123, include="journals,attachments"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_issue_general_error(self, mock_redmine):
        """Test general error handling in issue retrieval."""
        # Setup
        mock_redmine.issue.get.side_effect = Exception("Connection error")

        # Execute
        result = await get_redmine_issue(123)

        # Verify
        assert result is not None
        assert "error" in result
        # New error format includes operation and error message
        assert "fetching issue 123" in result["error"]
        assert "Connection error" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_get_redmine_issue_no_client(self):
        """Test issue retrieval when Redmine client is not initialized."""
        # Execute
        result = await get_redmine_issue(123)

        # Verify
        assert result is not None
        assert "error" in result
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_issue_no_assigned_to(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test issue retrieval when issue has no assigned_to field."""
        # Setup - remove assigned_to attribute
        delattr(mock_redmine_issue, "assigned_to")
        mock_redmine.issue.get.return_value = mock_redmine_issue

        # Execute
        result = await get_redmine_issue(123)

        # Verify
        assert result is not None
        assert result["assigned_to"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_issue_without_journals(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test opting out of journal retrieval."""
        mock_redmine.issue.get.return_value = mock_redmine_issue

        result = await get_redmine_issue(123, include_journals=False)

        assert "journals" not in result
        assert isinstance(result.get("attachments"), list)
        mock_redmine.issue.get.assert_called_once_with(123, include="attachments")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_issue_without_attachments(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test opting out of attachment retrieval."""
        mock_redmine.issue.get.return_value = mock_redmine_issue

        result = await get_redmine_issue(123, include_attachments=False)

        assert "attachments" not in result
        mock_redmine.issue.get.assert_called_once_with(123, include="journals")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_issue_without_custom_fields(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test opting out of custom field serialization."""
        mock_redmine.issue.get.return_value = mock_redmine_issue

        result = await get_redmine_issue(
            123,
            include_journals=False,
            include_attachments=False,
            include_custom_fields=False,
        )

        assert "custom_fields" not in result
        mock_redmine.issue.get.assert_called_once_with(123)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_issue_includes_custom_fields(
        self, mock_redmine, mock_redmine_issue
    ):
        """Custom fields are included by default in issue output."""
        mock_redmine.issue.get.return_value = mock_redmine_issue

        result = await get_redmine_issue(
            123, include_journals=False, include_attachments=False
        )

        assert "custom_fields" in result
        assert result["custom_fields"][0]["id"] == 12
        assert result["custom_fields"][0]["name"] == "Size"
        assert result["custom_fields"][0]["value"] == "S"
        mock_redmine.issue.get.assert_called_once_with(123)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_redmine_projects_success(
        self, mock_redmine, mock_redmine_projects
    ):
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
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
        # New error format includes operation and error message
        assert "listing projects" in result[0]["error"]
        assert "Connection error" in result[0]["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_success(self, mock_redmine, mock_redmine_issue):
        """Test successful issue creation."""
        mock_redmine.issue.create.return_value = mock_redmine_issue

        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(
            1, "Test Issue Subject", "Test issue description"
        )

        assert result is not None
        assert result["id"] == 123
        mock_redmine.issue.create.assert_called_once_with(
            project_id=1,
            subject="Test Issue Subject",
            description="Test issue description",
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_fields_json_string(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test create issue with MCP-style serialized fields payload."""
        mock_redmine.issue.create.return_value = mock_redmine_issue

        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(
            1,
            "Test Issue Subject",
            "Test issue description",
            fields='{"priority_id": 4, "tracker_id": 5}',
        )

        assert result is not None
        assert result["id"] == 123
        mock_redmine.issue.create.assert_called_once_with(
            project_id=1,
            subject="Test Issue Subject",
            description="Test issue description",
            priority_id=4,
            tracker_id=5,
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_extra_fields_object(
        self, mock_redmine, mock_redmine_issue
    ):
        """Extra fields payload is flattened into Redmine create attributes."""
        mock_redmine.issue.create.return_value = mock_redmine_issue

        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(
            1,
            "Test Issue Subject",
            "Test issue description",
            extra_fields={"priority_id": 4, "tracker_id": 5},
        )

        assert result is not None
        assert result["id"] == 123
        mock_redmine.issue.create.assert_called_once_with(
            project_id=1,
            subject="Test Issue Subject",
            description="Test issue description",
            priority_id=4,
            tracker_id=5,
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_extra_fields_string(
        self, mock_redmine, mock_redmine_issue
    ):
        """Serialized extra_fields payload is supported."""
        mock_redmine.issue.create.return_value = mock_redmine_issue

        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(
            1,
            "Test Issue Subject",
            "Test issue description",
            extra_fields='{"priority_id": 4, "tracker_id": 5}',
        )

        assert result is not None
        assert result["id"] == 123
        mock_redmine.issue.create.assert_called_once_with(
            project_id=1,
            subject="Test Issue Subject",
            description="Test issue description",
            priority_id=4,
            tracker_id=5,
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_invalid_fields_payload(self, mock_redmine):
        """Test invalid serialized fields payload handling."""
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(1, "A", "B", fields="this is not valid")

        assert "error" in result
        assert "Invalid fields payload" in result["error"]
        mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_invalid_extra_fields_payload(self, mock_redmine):
        """Invalid serialized extra_fields payload returns a clear error."""
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(
            1, "A", "B", extra_fields="this is not valid"
        )

        assert "error" in result
        assert "Invalid extra_fields payload" in result["error"]
        mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_autofill_disabled_by_default(
        self, mock_redmine
    ):
        """Validation error should not trigger retry when autofill is disabled."""
        from redminelib.exceptions import ValidationError
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        mock_redmine.issue.create.side_effect = ValidationError(
            "Project Category cannot be blank"
        )

        with patch.dict(
            os.environ,
            {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "false"},
            clear=False,
        ):
            result = await create_redmine_issue(
                41, "Autofill test", "Autofill description"
            )

        assert "error" in result
        mock_redmine.issue.create.assert_called_once()
        mock_redmine.project.get.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_autofills_required_custom_fields(
        self, mock_redmine, mock_redmine_issue
    ):
        """Retry create issue with auto-filled required custom fields."""
        from redminelib.exceptions import ValidationError
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        project_field = Mock()
        project_field.id = 6
        project_field.name = "Project Category"
        project_field.possible_values = [{"value": "Any"}, {"value": "Foo"}]
        project_field.default_value = "Foo"

        os_field = Mock()
        os_field.id = 4
        os_field.name = "Operating System"
        os_field.possible_values = [{"value": "All"}, {"value": "Linux"}]
        os_field.default_value = "Linux"

        mock_project = Mock()
        mock_project.issue_custom_fields = [project_field, os_field]
        mock_redmine.project.get.return_value = mock_project

        mock_redmine.issue.create.side_effect = [
            ValidationError(
                "Project Category cannot be blank, Operating System cannot be blank"
            ),
            mock_redmine_issue,
        ]

        with patch.dict(
            os.environ, {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true"}, clear=False
        ):
            result = await create_redmine_issue(
                41,
                "Autofill test",
                "Autofill description",
                fields='{"tracker_id": 5, "priority_id": 4}',
            )

        assert result["id"] == 123
        assert mock_redmine.issue.create.call_count == 2
        mock_redmine.project.get.assert_called_once_with(
            41, include="issue_custom_fields"
        )

        second_call_kwargs = mock_redmine.issue.create.call_args_list[1].kwargs
        assert second_call_kwargs["tracker_id"] == 5
        assert second_call_kwargs["priority_id"] == 4
        assert {"id": 6, "value": "Foo"} in second_call_kwargs["custom_fields"]
        assert {"id": 4, "value": "Linux"} in second_call_kwargs["custom_fields"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_autofills_blank_existing_custom_field(
        self, mock_redmine, mock_redmine_issue
    ):
        """Retry should replace blank values for already-present custom fields."""
        from redminelib.exceptions import ValidationError
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        project_field = Mock()
        project_field.id = 6
        project_field.name = "Project Category"
        project_field.possible_values = [{"value": "Any"}, {"value": "Foo"}]
        project_field.default_value = "Foo"

        mock_project = Mock()
        mock_project.issue_custom_fields = [project_field]
        mock_redmine.project.get.return_value = mock_project

        mock_redmine.issue.create.side_effect = [
            ValidationError("Project Category cannot be blank"),
            mock_redmine_issue,
        ]

        with patch.dict(
            os.environ, {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true"}, clear=False
        ):
            result = await create_redmine_issue(
                41,
                "Autofill test",
                "Autofill description",
                fields='{"tracker_id": 5, "custom_fields": [{"id": 6, "value": ""}]}',
            )

        assert result["id"] == 123
        assert mock_redmine.issue.create.call_count == 2
        second_call_kwargs = mock_redmine.issue.create.call_args_list[1].kwargs

        matching_values = [
            entry["value"]
            for entry in second_call_kwargs["custom_fields"]
            if entry.get("id") == 6
        ]
        assert matching_values == ["Foo"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_autofill_preserves_list_default_value(
        self, mock_redmine, mock_redmine_issue
    ):
        """Retry should preserve list default values without stringifying them."""
        from redminelib.exceptions import ValidationError
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        components_field = Mock()
        components_field.id = 8
        components_field.name = "Components"
        components_field.possible_values = [{"value": "A"}, {"value": "B"}]
        components_field.default_value = ["A"]

        mock_project = Mock()
        mock_project.issue_custom_fields = [components_field]
        mock_redmine.project.get.return_value = mock_project

        mock_redmine.issue.create.side_effect = [
            ValidationError("Components cannot be blank"),
            mock_redmine_issue,
        ]

        with patch.dict(
            os.environ, {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true"}, clear=False
        ):
            result = await create_redmine_issue(
                41,
                "Autofill test",
                "Autofill description",
                fields='{"tracker_id": 5}',
            )

        assert result["id"] == 123
        assert mock_redmine.issue.create.call_count == 2
        second_call_kwargs = mock_redmine.issue.create.call_args_list[1].kwargs

        matching_values = [
            entry["value"]
            for entry in second_call_kwargs["custom_fields"]
            if entry.get("id") == 8
        ]
        assert matching_values == [["A"]]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_autofills_invalid_list_value(
        self, mock_redmine, mock_redmine_issue
    ):
        """Retry should replace invalid list values when validation flags inclusion."""
        from redminelib.exceptions import ValidationError
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        rise_project_field = Mock()
        rise_project_field.id = 6
        rise_project_field.name = "RISE Project"
        rise_project_field.possible_values = [{"value": "Any"}, {"value": "ShowX"}]
        rise_project_field.default_value = "Any"

        mock_project = Mock()
        mock_project.issue_custom_fields = [rise_project_field]
        mock_redmine.project.get.return_value = mock_project

        mock_redmine.issue.create.side_effect = [
            ValidationError("RISE Project is not included in the list"),
            mock_redmine_issue,
        ]

        with patch.dict(
            os.environ, {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true"}, clear=False
        ):
            result = await create_redmine_issue(
                99,
                "Autofill test",
                "Autofill description",
                fields=(
                    '{"tracker_id": 5, "custom_fields": '
                    '[{"id": 6, "value": "any"}]}'
                ),
            )

        assert result["id"] == 123
        assert mock_redmine.issue.create.call_count == 2
        second_call_kwargs = mock_redmine.issue.create.call_args_list[1].kwargs

        matching_values = [
            entry["value"]
            for entry in second_call_kwargs["custom_fields"]
            if entry.get("id") == 6
        ]
        assert matching_values == ["Any"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_redmine_issue_error(self, mock_redmine):
        """Test error during issue creation."""
        mock_redmine.issue.create.side_effect = Exception("Boom")

        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(1, "A", "B")
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_create_redmine_issue_no_client(self):
        """Test issue creation when client is not initialized."""
        from redmine_mcp_server.redmine_handler import create_redmine_issue

        result = await create_redmine_issue(1, "A")
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_success(self, mock_redmine, mock_redmine_issue):
        """Test successful issue update."""
        mock_redmine.issue.update.return_value = True
        mock_redmine.issue.get.return_value = mock_redmine_issue

        from redmine_mcp_server.redmine_handler import update_redmine_issue

        result = await update_redmine_issue(123, {"subject": "New"})

        assert result["id"] == 123
        mock_redmine.issue.update.assert_called_once_with(123, subject="New")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_status_name(
        self, mock_redmine, mock_redmine_issue
    ):
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_not_found(self, mock_redmine):
        """Test update when issue not found."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue.update.side_effect = ResourceNotFoundError()

        from redmine_mcp_server.redmine_handler import update_redmine_issue

        result = await update_redmine_issue(999, {"subject": "X"})

        assert result["error"] == "Issue 999 not found."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_update_redmine_issue_no_client(self):
        """Test update when client not initialized."""
        from redmine_mcp_server.redmine_handler import update_redmine_issue

        result = await update_redmine_issue(1, {"subject": "X"})
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_autofill_disabled_by_default(self, mock_redmine):
        """Validation error should not trigger update retry when autofill is disabled."""
        from redminelib.exceptions import ValidationError
        from redmine_mcp_server.redmine_handler import update_redmine_issue

        mock_redmine.issue.update.side_effect = ValidationError("Location cannot be blank")

        with patch.dict(
            os.environ,
            {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "false"},
            clear=False,
        ):
            result = await update_redmine_issue(123, {"subject": "New"})

        assert "error" in result
        mock_redmine.issue.update.assert_called_once_with(123, subject="New")
        mock_redmine.project.get.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_autofills_required_custom_fields(
        self, mock_redmine, mock_redmine_issue
    ):
        """Retry update with auto-filled required custom fields."""
        from redminelib.exceptions import ValidationError
        from redmine_mcp_server.redmine_handler import update_redmine_issue

        location_field = Mock()
        location_field.id = 8
        location_field.name = "Location"
        location_field.possible_values = [{"value": "Any"}, {"value": "Berlin"}]
        location_field.default_value = "Any"

        mock_project = Mock()
        mock_project.issue_custom_fields = [location_field]
        mock_redmine.project.get.return_value = mock_project

        issue_for_project_lookup = Mock()
        issue_for_project_lookup.project = Mock(id=41, name="Flatline")

        mock_redmine.issue.update.side_effect = [
            ValidationError("Location cannot be blank"),
            None,
        ]
        mock_redmine.issue.get.side_effect = [issue_for_project_lookup, mock_redmine_issue]

        with patch.dict(
            os.environ, {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true"}, clear=False
        ):
            result = await update_redmine_issue(123, {"subject": "New"})

        assert result["id"] == 123
        assert mock_redmine.issue.update.call_count == 2
        mock_redmine.project.get.assert_called_once_with(41, include="issue_custom_fields")

        second_call_kwargs = mock_redmine.issue.update.call_args_list[1].kwargs
        assert second_call_kwargs["subject"] == "New"
        assert {"id": 8, "value": "Any"} in second_call_kwargs["custom_fields"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_maps_named_custom_field(
        self, mock_redmine, mock_redmine_issue
    ):
        """Named custom fields are mapped to custom_fields payload entries."""
        from redmine_mcp_server.redmine_handler import update_redmine_issue

        issue_for_project_lookup = Mock()
        issue_for_project_lookup.project = Mock(id=41, name="Flatline")
        mock_redmine.issue.get.side_effect = [issue_for_project_lookup, mock_redmine_issue]

        size_custom_field = Mock()
        size_custom_field.id = 6
        size_custom_field.name = "Size"
        size_custom_field.possible_values = ["S", "M", "L"]
        project = Mock()
        project.issue_custom_fields = [size_custom_field]
        mock_redmine.project.get.return_value = project

        result = await update_redmine_issue(123, {"size": "S", "notes": "size set"})

        assert result["id"] == 123
        assert "custom_fields" in result
        mock_redmine.project.get.assert_called_once_with(41, include="issue_custom_fields")
        mock_redmine.issue.update.assert_called_once()
        update_kwargs = mock_redmine.issue.update.call_args.kwargs
        assert update_kwargs["notes"] == "size set"
        assert update_kwargs["custom_fields"] == [{"id": 6, "value": "S"}]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_merges_custom_fields(
        self, mock_redmine, mock_redmine_issue
    ):
        """Named custom fields are merged with explicit custom_fields."""
        from redmine_mcp_server.redmine_handler import update_redmine_issue

        issue_for_project_lookup = Mock()
        issue_for_project_lookup.project = Mock(id=41, name="Flatline")
        mock_redmine.issue.get.side_effect = [issue_for_project_lookup, mock_redmine_issue]

        size_custom_field = Mock()
        size_custom_field.id = 6
        size_custom_field.name = "Size"
        size_custom_field.possible_values = ["S", "M", "L"]
        project = Mock()
        project.issue_custom_fields = [size_custom_field]
        mock_redmine.project.get.return_value = project

        await update_redmine_issue(
            123,
            {
                "size": "M",
                "custom_fields": [{"id": 99, "value": "Preserved"}],
            },
        )

        update_kwargs = mock_redmine.issue.update.call_args.kwargs
        assert {"id": 99, "value": "Preserved"} in update_kwargs["custom_fields"]
        assert {"id": 6, "value": "M"} in update_kwargs["custom_fields"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_redmine_issue_invalid_named_custom_field_value(
        self, mock_redmine
    ):
        """Invalid named custom-field values return an error and do not update."""
        from redmine_mcp_server.redmine_handler import update_redmine_issue

        issue_for_project_lookup = Mock()
        issue_for_project_lookup.project = Mock(id=41, name="Flatline")
        mock_redmine.issue.get.return_value = issue_for_project_lookup

        size_custom_field = Mock()
        size_custom_field.id = 6
        size_custom_field.name = "Size"
        size_custom_field.possible_values = ["S", "M", "L"]
        project = Mock()
        project.issue_custom_fields = [size_custom_field]
        mock_redmine.project.get.return_value = project

        result = await update_redmine_issue(123, {"size": "XXL"})

        assert "error" in result
        assert "Invalid value 'XXL' for custom field 'Size'" in result["error"]
        mock_redmine.issue.update.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_redmine_issues_success(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test listing issues assigned to current user."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue]

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert result[0]["id"] == 123
        mock_redmine.issue.filter.assert_called_once_with(
            assigned_to_id="me", offset=0, limit=25
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_redmine_issues_empty(self, mock_redmine):
        """Test listing issues when none exist."""
        mock_redmine.issue.filter.return_value = []

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_redmine_issues_error(self, mock_redmine):
        """Test error handling when listing issues."""
        mock_redmine.issue.filter.side_effect = Exception("Boom")

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert "error" in result[0]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_list_my_redmine_issues_no_client(self):
        """Test listing issues when client is not initialized."""
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert result[0]["error"] == "Redmine client not initialized."

    # Pagination Test Cases
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_issues_with_limit_basic(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test basic limit functionality."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 5

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(limit=5)

        assert isinstance(result, list)
        assert len(result) == 5
        mock_redmine.issue.filter.assert_called_once_with(
            assigned_to_id="me", offset=0, limit=5
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_issues_with_offset(self, mock_redmine, mock_redmine_issue):
        """Test offset pagination."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 10

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(limit=10, offset=25)

        assert isinstance(result, list)
        assert len(result) == 10
        mock_redmine.issue.filter.assert_called_once_with(
            assigned_to_id="me", offset=25, limit=10
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_issues_with_metadata(self, mock_redmine, mock_redmine_issue):
        """Test pagination metadata response."""
        # Create mock ResourceSet that behaves like a list when converted
        mock_resource_set = Mock()
        mock_resource_set.__iter__ = Mock(return_value=iter([mock_redmine_issue] * 10))
        mock_resource_set.total_count = 150

        # Make filter() return our mock ResourceSet
        mock_redmine.issue.filter.return_value = mock_resource_set

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(
            limit=10, offset=25, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result
        assert len(result["issues"]) == 10
        assert result["pagination"]["total"] == 150
        assert result["pagination"]["limit"] == 10
        assert result["pagination"]["offset"] == 25
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_previous"] is True
        assert result["pagination"]["next_offset"] == 35

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
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
        mock_redmine.issue.filter.assert_called_with(
            assigned_to_id="me", offset=0, limit=100
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_issues_default_limit(self, mock_redmine, mock_redmine_issue):
        """Test default limit behavior."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 25

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues()

        assert isinstance(result, list)
        assert len(result) == 25
        mock_redmine.issue.filter.assert_called_once_with(
            assigned_to_id="me", offset=0, limit=25
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_issues_limit_with_filters(
        self, mock_redmine, mock_redmine_issue
    ):
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_issues_pagination_navigation(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test next/previous logic."""
        # Create mock ResourceSet that behaves like a list when converted
        mock_resource_set = Mock()
        mock_resource_set.__iter__ = Mock(return_value=iter([mock_redmine_issue] * 10))
        mock_resource_set.total_count = 100

        # Make filter() return our mock ResourceSet
        mock_redmine.issue.filter.return_value = mock_resource_set

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        # Test middle page
        result = await list_my_redmine_issues(
            limit=10, offset=25, include_pagination_info=True
        )
        pagination = result["pagination"]
        assert pagination["has_next"] is True
        assert pagination["has_previous"] is True
        assert pagination["next_offset"] == 35
        assert pagination["previous_offset"] == 15

        # Test first page
        result = await list_my_redmine_issues(
            limit=10, offset=0, include_pagination_info=True
        )
        pagination = result["pagination"]
        assert pagination["has_previous"] is False
        assert pagination["previous_offset"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_my_issues_parameter_validation(
        self, mock_redmine, mock_redmine_issue
    ):
        """Test input validation and sanitization."""
        mock_redmine.issue.filter.return_value = [mock_redmine_issue] * 10

        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        # Test string limit conversion
        await list_my_redmine_issues(limit="10")
        mock_redmine.issue.filter.assert_called_with(
            assigned_to_id="me", offset=0, limit=10
        )

        # Test invalid limit type
        mock_redmine.issue.filter.reset_mock()
        await list_my_redmine_issues(limit="invalid")
        mock_redmine.issue.filter.assert_called_with(
            assigned_to_id="me", offset=0, limit=25
        )  # default

        # Test negative offset (should reset to 0)
        mock_redmine.issue.filter.reset_mock()
        await list_my_redmine_issues(offset=-10)
        mock_redmine.issue.filter.assert_called_with(
            assigned_to_id="me", offset=0, limit=25
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_get_redmine_attachment_download_url_success(
        self, mock_cleanup, mock_redmine
    ):
        """Test successful URL generation with secure implementation."""
        # Mock setup
        mock_attachment = MagicMock()
        mock_attachment.filename = "test.pdf"
        mock_attachment.content_type = "application/pdf"
        mock_attachment.download = MagicMock(return_value="/tmp/test_download")

        mock_redmine.attachment.get.return_value = mock_attachment

        with patch("uuid.uuid4", return_value=MagicMock(spec=uuid.UUID)) as mock_uuid:
            mock_uuid.return_value.__str__ = MagicMock(return_value="test-uuid-123")
            with patch("builtins.open", mock_open()):
                with patch("pathlib.Path.mkdir"):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 1024
                        with patch("os.rename"):
                            with patch("json.dump"):
                                from redmine_mcp_server.redmine_handler import (
                                    get_redmine_attachment_download_url,
                                )

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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_redmine_attachment_download_url_not_found(self, mock_redmine):
        """Test handling of non-existent attachment ID."""
        mock_redmine.attachment.get.side_effect = ResourceNotFoundError()

        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
        )

        result = await get_redmine_attachment_download_url(999)

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_search_redmine_issues_success(
        self, mock_redmine, mock_redmine_issue
    ):
        """Search issues successfully."""
        mock_redmine.issue.search.return_value = [mock_redmine_issue]

        from redmine_mcp_server.redmine_handler import search_redmine_issues

        result = await search_redmine_issues("test")

        assert isinstance(result, list)
        assert result[0]["id"] == 123
        mock_redmine.issue.search.assert_called_once_with("test", offset=0, limit=25)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_search_redmine_issues_empty(self, mock_redmine):
        """Search issues with no matches."""
        mock_redmine.issue.search.return_value = []

        from redmine_mcp_server.redmine_handler import search_redmine_issues

        result = await search_redmine_issues("none")

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_search_redmine_issues_error(self, mock_redmine):
        """General search error handling."""
        mock_redmine.issue.search.side_effect = Exception("boom")

        from redmine_mcp_server.redmine_handler import search_redmine_issues

        result = await search_redmine_issues("a")

        # Error now returns a dict, not a list
        assert isinstance(result, dict)
        assert "error" in result
        assert "searching issues" in result["error"]
        assert "boom" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_summarize_project_status_success(
        self, mock_redmine, mock_project, mock_issues_list
    ):
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
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_summarize_project_status_project_not_found(self, mock_redmine):
        """Test project status summarization with non-existent project."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.project.get.side_effect = ResourceNotFoundError()

        result = await summarize_project_status(999, 30)

        assert result["error"] == "Project 999 not found."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_summarize_project_status_no_client(self):
        """Test project status summarization with no Redmine client."""
        result = await summarize_project_status(1, 30)

        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_summarize_project_status_custom_days(
        self, mock_redmine, mock_project
    ):
        """Test project status summarization with custom days parameter."""
        mock_redmine.project.get.return_value = mock_project
        mock_redmine.issue.filter.return_value = []

        result = await summarize_project_status(1, 7)

        assert result["analysis_period"]["days"] == 7

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_summarize_project_status_exception_handling(
        self, mock_redmine, mock_project
    ):
        """Test project status summarization exception handling."""
        mock_redmine.project.get.return_value = mock_project
        mock_redmine.issue.filter.side_effect = Exception("API Error")

        result = await summarize_project_status(1, 30)

        # New error format includes operation and error message
        assert "error" in result
        assert "summarizing project 1" in result["error"]
        assert "API Error" in result["error"]

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"ATTACHMENTS_DIR": "./test_attachments"})
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

    @pytest.mark.asyncio
    async def test_cleanup_attachment_files_exception(self):
        """Test exception handling in cleanup_attachment_files."""
        from redmine_mcp_server.redmine_handler import cleanup_attachment_files
        from redmine_mcp_server.file_manager import AttachmentFileManager

        with patch.object(
            AttachmentFileManager,
            "cleanup_expired_files",
            side_effect=Exception("Cleanup error"),
        ):
            result = await cleanup_attachment_files()

        assert "error" in result
        assert "An error occurred during cleanup" in result["error"]


@pytest.mark.unit
class TestAttachmentErrorRecovery:
    """Tests for attachment download error recovery paths."""

    @pytest.mark.asyncio
    @patch(
        "redmine_mcp_server.redmine_handler._ensure_cleanup_started",
        new_callable=AsyncMock,
    )
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_attachment_file_move_failure(
        self, mock_redmine, mock_cleanup, tmp_path
    ):
        """Test OSError recovery during file move."""
        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
        )

        # Mock attachment with download method
        mock_attachment = MagicMock()
        mock_attachment.id = 123
        mock_attachment.filename = "test.txt"
        mock_attachment.filesize = 100
        mock_attachment.content_type = "text/plain"

        # Mock download to create a temp file
        temp_file = tmp_path / "test.txt"
        temp_file.write_bytes(b"test content")
        mock_attachment.download.return_value = str(temp_file)

        mock_redmine.attachment.get.return_value = mock_attachment

        # Patch os.rename to fail
        with patch("os.rename", side_effect=OSError("Permission denied")):
            with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(tmp_path)}):
                result = await get_redmine_attachment_download_url(123)

        # Should return error dict
        assert "error" in result
        assert "Failed to store attachment" in result["error"]

    @pytest.mark.asyncio
    @patch(
        "redmine_mcp_server.redmine_handler._ensure_cleanup_started",
        new_callable=AsyncMock,
    )
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_attachment_metadata_write_failure(
        self, mock_redmine, mock_cleanup, tmp_path
    ):
        """Test IOError recovery during metadata write."""
        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
        )

        # Create attachments directory
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        # Mock attachment
        mock_attachment = MagicMock()
        mock_attachment.id = 456
        mock_attachment.filename = "doc.pdf"
        mock_attachment.filesize = 1000
        mock_attachment.content_type = "application/pdf"

        # Mock download to create a temp file
        temp_file = attachments_dir / "doc.pdf"
        temp_file.write_bytes(b"pdf content")
        mock_attachment.download.return_value = str(temp_file)

        mock_redmine.attachment.get.return_value = mock_attachment

        # Wrap os.rename to fail specifically on metadata file moves
        original_rename = os.rename

        def selective_rename(src, dst):
            """Allow normal file moves, but fail on metadata JSON files."""
            dst_str = os.fspath(dst)
            if dst_str.endswith(".json"):
                raise OSError("Disk full")
            return original_rename(src, dst)

        with patch("os.rename", side_effect=selective_rename):
            with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(attachments_dir)}):
                result = await get_redmine_attachment_download_url(456)

        # Should return error dict
        assert "error" in result
        assert "Failed to save metadata" in result["error"]


class TestHelperFunctionEdgeCases:
    """Test edge cases for helper functions to improve coverage."""

    def test_journals_to_list_none_journals(self):
        """Test _journals_to_list with None journals attribute (line 684-685)."""
        from redmine_mcp_server.redmine_handler import _journals_to_list

        mock_issue = Mock()
        mock_issue.journals = None
        result = _journals_to_list(mock_issue)
        assert result == []

    def test_journals_to_list_empty_notes_filtered(self):
        """Test _journals_to_list filters out journals with empty notes (line 695-696)."""
        from redmine_mcp_server.redmine_handler import _journals_to_list

        mock_issue = Mock()
        mock_journal = Mock()
        mock_journal.notes = ""  # Empty notes
        mock_journal.id = 1
        mock_issue.journals = [mock_journal]
        result = _journals_to_list(mock_issue)
        assert result == []  # Filtered out

    def test_journals_to_list_whitespace_notes_filtered(self):
        """Test _journals_to_list filters journals with whitespace-only notes."""
        from redmine_mcp_server.redmine_handler import _journals_to_list

        mock_issue = Mock()
        mock_journal = Mock()
        mock_journal.notes = "   "  # Whitespace only - still falsy when stripped
        mock_journal.id = 1
        mock_issue.journals = [mock_journal]
        # Note: The code uses `if not notes:` which won't filter whitespace
        # but empty string will be filtered
        result = _journals_to_list(mock_issue)
        # Whitespace is truthy, so it won't be filtered
        assert len(result) == 1

    def test_attachments_to_list_none_attachments(self):
        """Test _attachments_to_list with None attachments (line 723-724)."""
        from redmine_mcp_server.redmine_handler import _attachments_to_list

        mock_issue = Mock()
        mock_issue.attachments = None
        result = _attachments_to_list(mock_issue)
        assert result == []

    def test_attachments_to_list_not_iterable(self):
        """Test _attachments_to_list with non-iterable value (line 729-730)."""
        from redmine_mcp_server.redmine_handler import _attachments_to_list

        mock_issue = Mock()
        # Make attachments non-iterable by setting it to an integer
        mock_issue.attachments = 123
        result = _attachments_to_list(mock_issue)
        assert result == []

    def test_resource_to_dict_name_fallback(self):
        """Test _resource_to_dict uses name when no subject/title (line 537-538)."""
        from redmine_mcp_server.redmine_handler import _resource_to_dict

        # Create a mock with only 'name' attribute (no subject or title)
        mock_resource = Mock(spec=["id", "name"])
        mock_resource.id = 1
        mock_resource.name = "Test Resource Name"

        result = _resource_to_dict(mock_resource, "custom_type")
        assert result["title"] == "Test Resource Name"
        assert result["type"] == "custom_type"

    def test_resource_to_dict_project_id_without_project(self):
        """Test _resource_to_dict with project_id but no project object (line 551-553)."""
        from redmine_mcp_server.redmine_handler import _resource_to_dict

        # Create mock with project_id but no project attribute
        mock_resource = Mock(spec=["id", "subject", "project_id"])
        mock_resource.id = 1
        mock_resource.subject = "Test Subject"
        mock_resource.project_id = 456

        result = _resource_to_dict(mock_resource, "issues")
        assert result["project_id"] == 456
        assert result["project"] is None


class TestGetRedmineIssueNoIncludes:
    """Test get_redmine_issue with both includes disabled (line 795)."""

    @pytest.fixture
    def mock_basic_issue(self):
        """Create a basic mock issue without journals/attachments."""
        from datetime import datetime

        mock_issue = Mock()
        mock_issue.id = 123
        mock_issue.subject = "Test Issue"
        mock_issue.description = "Description"

        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Project"
        mock_issue.project = mock_project

        mock_status = Mock()
        mock_status.id = 1
        mock_status.name = "New"
        mock_issue.status = mock_status

        mock_priority = Mock()
        mock_priority.id = 2
        mock_priority.name = "Normal"
        mock_issue.priority = mock_priority

        mock_author = Mock()
        mock_author.id = 1
        mock_author.name = "Author"
        mock_issue.author = mock_author

        mock_issue.assigned_to = None
        mock_issue.created_on = datetime(2025, 1, 1)
        mock_issue.updated_on = datetime(2025, 1, 2)

        return mock_issue

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_issue_both_includes_false(self, mock_redmine, mock_basic_issue):
        """Test issue fetch with both include_journals=False and include_attachments=False."""
        mock_redmine.issue.get.return_value = mock_basic_issue

        result = await get_redmine_issue(
            123, include_journals=False, include_attachments=False
        )

        # Verify called WITHOUT include parameter
        mock_redmine.issue.get.assert_called_once_with(123)
        assert result["id"] == 123
        assert "journals" not in result
        assert "attachments" not in result


class TestListMyIssuesEdgeCases:
    """Test edge cases for list_my_redmine_issues (lines 893, 926, 987-997)."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_wrapped_filters_parameter(self, mock_redmine):
        """Handle MCP wrapping filters in nested dict (line 893)."""
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        mock_resource_set = Mock()
        mock_resource_set.__iter__ = Mock(return_value=iter([]))
        mock_redmine.issue.filter.return_value = mock_resource_set

        # Call with wrapped filters - MCP sometimes wraps params
        await list_my_redmine_issues(filters={"filters": {"status_id": 1}})

        # Verify filter was called (status_id should be extracted)
        mock_redmine.issue.filter.assert_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_limit_zero_with_pagination_info(self, mock_redmine):
        """limit=0 with include_pagination_info returns structured empty result (line 926)."""
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues

        result = await list_my_redmine_issues(
            limit=0, offset=0, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert "issues" in result
        assert "pagination" in result
        assert result["issues"] == []
        assert result["pagination"]["total"] == 0
        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_total_count_exception_full_page(self, mock_redmine):
        """When total count query fails, estimate from result size - full page (line 987-994)."""
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues
        from datetime import datetime

        # Create mock issues for a full page
        mock_issues = []
        for i in range(25):
            issue = Mock()
            issue.id = i
            issue.subject = f"Issue {i}"
            issue.description = ""
            issue.project = Mock(id=1, name="Project")
            issue.status = Mock(id=1, name="New")
            issue.priority = Mock(id=2, name="Normal")
            issue.author = Mock(id=1, name="Author")
            issue.assigned_to = None
            issue.created_on = datetime(2025, 1, 1)
            issue.updated_on = datetime(2025, 1, 1)
            mock_issues.append(issue)

        # First call returns issues, second call for count raises exception
        first_call = Mock()
        first_call.__iter__ = Mock(return_value=iter(mock_issues))

        second_call = Mock()
        second_call.__iter__ = Mock(return_value=iter([]))

        # Make total_count raise an exception
        type(second_call).total_count = property(
            lambda self: (_ for _ in ()).throw(Exception("API Error"))
        )

        mock_redmine.issue.filter.side_effect = [first_call, second_call]

        result = await list_my_redmine_issues(
            limit=25, offset=0, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert "pagination" in result
        # Full page: estimate is offset + len + 1 = 0 + 25 + 1 = 26
        assert result["pagination"]["total"] == 26

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_total_count_exception_partial_page(self, mock_redmine):
        """When total count query fails, estimate from result size - partial page (line 996-997)."""
        from redmine_mcp_server.redmine_handler import list_my_redmine_issues
        from datetime import datetime

        # Create mock issues for a partial page (less than limit)
        mock_issues = []
        for i in range(10):  # Only 10 issues, less than limit of 25
            issue = Mock()
            issue.id = i
            issue.subject = f"Issue {i}"
            issue.description = ""
            issue.project = Mock(id=1, name="Project")
            issue.status = Mock(id=1, name="New")
            issue.priority = Mock(id=2, name="Normal")
            issue.author = Mock(id=1, name="Author")
            issue.assigned_to = None
            issue.created_on = datetime(2025, 1, 1)
            issue.updated_on = datetime(2025, 1, 1)
            mock_issues.append(issue)

        first_call = Mock()
        first_call.__iter__ = Mock(return_value=iter(mock_issues))

        second_call = Mock()
        second_call.__iter__ = Mock(return_value=iter([]))
        type(second_call).total_count = property(
            lambda self: (_ for _ in ()).throw(Exception("API Error"))
        )

        mock_redmine.issue.filter.side_effect = [first_call, second_call]

        result = await list_my_redmine_issues(
            limit=25, offset=5, include_pagination_info=True
        )

        assert isinstance(result, dict)
        assert "pagination" in result
        # Partial page: estimate is offset + len = 5 + 10 = 15
        assert result["pagination"]["total"] == 15


class TestErrorHandlerEdgeCases:
    """Test edge cases for _handle_redmine_error (line 443)."""

    def test_resource_not_found_without_resource_id(self):
        """ResourceNotFoundError without resource_id uses generic message (line 443)."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import ResourceNotFoundError

        result = _handle_redmine_error(
            ResourceNotFoundError(),
            "fetching resource",
            context={"resource_type": "issue"},  # No resource_id key
        )
        assert result["error"] == "Requested issue not found."

    def test_resource_not_found_with_resource_id(self):
        """ResourceNotFoundError with resource_id includes ID in message (line 442)."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import ResourceNotFoundError

        result = _handle_redmine_error(
            ResourceNotFoundError(),
            "fetching resource",
            context={"resource_type": "issue", "resource_id": 123},
        )
        assert result["error"] == "Issue 123 not found."


class TestSearchEntireRedmineValidation:
    """Test validation logic in search_entire_redmine (lines 1567, 1574, 1606)."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_invalid_resources_fallback_to_defaults(self, mock_redmine):
        """Invalid resource types fall back to allowed_types (line 1567)."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = {}

        await search_entire_redmine("test query", resources=["invalid_type", "another_bad"])

        # Should have called search with default allowed types
        mock_redmine.search.assert_called_once()
        call_args = mock_redmine.search.call_args
        # Resources should be the defaults: ["issues", "wiki_pages"]
        assert set(call_args[1]["resources"]) == {"issues", "wiki_pages"}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_limit_zero_resets_to_100(self, mock_redmine):
        """limit <= 0 resets to 100 (line 1574)."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = {}

        await search_entire_redmine("test query", limit=0)

        mock_redmine.search.assert_called_once()
        call_args = mock_redmine.search.call_args
        assert call_args[1]["limit"] == 100

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_limit_negative_resets_to_100(self, mock_redmine):
        """Negative limit resets to 100 (line 1574)."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = {}

        await search_entire_redmine("test query", limit=-10)

        mock_redmine.search.assert_called_once()
        call_args = mock_redmine.search.call_args
        assert call_args[1]["limit"] == 100

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_unknown_resource_type_skipped(self, mock_redmine):
        """Unknown resource_type in results is skipped (line 1606)."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        # Return results with an unknown type that's not in allowed_types
        mock_news = Mock()
        mock_news.id = 1
        mock_news.title = "News Item"

        mock_redmine.search.return_value = {
            "news": [mock_news],  # Not in allowed_types
            "issues": [],
        }

        result = await search_entire_redmine("test query")

        # "news" should not be in results_by_type
        assert "news" not in result["results_by_type"]
        assert result["total_count"] == 0


class TestUpdateIssueStatusHandling:
    """Test status handling in update_redmine_issue (lines 1249-1250)."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_status_lookup_exception_continues(self, mock_redmine):
        """Status lookup exception is logged and update continues (line 1249-1250)."""
        from redmine_mcp_server.redmine_handler import update_redmine_issue
        from datetime import datetime

        # Make status lookup fail
        mock_redmine.issue_status.all.side_effect = Exception("API Error")

        # But update should still work
        mock_updated_issue = Mock()
        mock_updated_issue.id = 123
        mock_updated_issue.subject = "Updated Issue"
        mock_updated_issue.description = "Description"
        mock_updated_issue.project = Mock(id=1, name="Project")
        mock_updated_issue.status = Mock(id=2, name="In Progress")
        mock_updated_issue.priority = Mock(id=2, name="Normal")
        mock_updated_issue.author = Mock(id=1, name="Author")
        mock_updated_issue.assigned_to = None
        mock_updated_issue.created_on = datetime(2025, 1, 1)
        mock_updated_issue.updated_on = datetime(2025, 1, 2)

        mock_redmine.issue.update.return_value = None
        mock_redmine.issue.get.return_value = mock_updated_issue

        # Call with status_name - should fail to resolve but continue
        result = await update_redmine_issue(
            123, {"status_name": "Closed", "notes": "Test note"}
        )

        # Should not fail - just skip status resolution
        assert "error" not in result
        assert result["id"] == 123


class TestAttachmentDownloadEdgeCases:
    """Test edge cases for get_redmine_attachment_download_url (line 1380)."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_attachment_download_no_client(self):
        """Test attachment download with no Redmine client (line 1286)."""
        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
        )

        result = await get_redmine_attachment_download_url(123)
        assert result == {"error": "Redmine client not initialized."}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_public_host_0000_converts_to_localhost(self, mock_redmine, tmp_path):
        """PUBLIC_HOST=0.0.0.0 converts to localhost in URL (line 1380)."""
        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
        )

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        # Create a temp file to simulate downloaded attachment
        temp_file = attachments_dir / "test_file.txt"
        temp_file.write_text("test content")

        mock_attachment = Mock()
        mock_attachment.id = 789
        mock_attachment.filename = "test_file.txt"
        mock_attachment.content_type = "text/plain"
        mock_attachment.download.return_value = str(temp_file)

        mock_redmine.attachment.get.return_value = mock_attachment

        # Set PUBLIC_HOST to 0.0.0.0
        with patch.dict(
            os.environ,
            {
                "ATTACHMENTS_DIR": str(attachments_dir),
                "PUBLIC_HOST": "0.0.0.0",
                "PUBLIC_PORT": "9000",
            },
        ):
            result = await get_redmine_attachment_download_url(789)

        # URL should use localhost, not 0.0.0.0
        assert "error" not in result
        assert "localhost" in result["download_url"]
        assert "0.0.0.0" not in result["download_url"]
        assert ":9000" in result["download_url"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_file_rename_error_with_cleanup_failure(self, mock_redmine, tmp_path):
        """File rename error with cleanup also failing (lines 1332-1333)."""
        from pathlib import Path
        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
        )

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        temp_file = attachments_dir / "test_file.txt"
        temp_file.write_text("test content")

        mock_attachment = Mock()
        mock_attachment.id = 999
        mock_attachment.filename = "test_file.txt"
        mock_attachment.content_type = "text/plain"
        mock_attachment.download.return_value = str(temp_file)

        mock_redmine.attachment.get.return_value = mock_attachment

        # Make rename fail
        original_rename = os.rename
        rename_call_count = [0]

        def failing_rename(src, dst):
            rename_call_count[0] += 1
            if rename_call_count[0] == 1:
                # First rename (to temp) succeeds
                return original_rename(src, dst)
            # Second rename fails
            raise OSError("Disk full")

        # Make unlink also fail during cleanup
        def failing_unlink(self, *args, **kwargs):
            raise OSError("Cannot delete file")

        with patch("os.rename", side_effect=failing_rename):
            with patch.object(Path, "unlink", failing_unlink):
                with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(attachments_dir)}):
                    result = await get_redmine_attachment_download_url(999)

        # Should still return error even if cleanup fails
        assert "error" in result
        assert "Failed to store attachment" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_metadata_write_error_with_cleanup_failure(
        self, mock_redmine, tmp_path
    ):
        """Metadata write error with cleanup also failing (lines 1369-1370)."""
        from pathlib import Path
        from redmine_mcp_server.redmine_handler import (
            get_redmine_attachment_download_url,
        )

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        temp_file = attachments_dir / "test_file.txt"
        temp_file.write_text("test content")

        mock_attachment = Mock()
        mock_attachment.id = 888
        mock_attachment.filename = "test_file.txt"
        mock_attachment.content_type = "text/plain"
        mock_attachment.download.return_value = str(temp_file)

        mock_redmine.attachment.get.return_value = mock_attachment

        # Make json.dump fail and cleanup also fail
        def failing_unlink(self, *args, **kwargs):
            raise OSError("Cannot delete file")

        original_rename = os.rename
        rename_count = [0]

        def selective_rename(src, dst):
            rename_count[0] += 1
            dst_str = str(dst)
            if dst_str.endswith(".json"):
                raise OSError("Cannot write metadata")
            return original_rename(src, dst)

        with patch("os.rename", side_effect=selective_rename):
            with patch.object(Path, "unlink", failing_unlink):
                with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(attachments_dir)}):
                    result = await get_redmine_attachment_download_url(888)

        # Should still return error even if cleanup fails
        assert "error" in result
        assert "Failed to save metadata" in result["error"]


class TestCleanupTaskManager:
    """Test CleanupTaskManager loop behavior (lines 211-232)."""

    @pytest.mark.asyncio
    async def test_cleanup_loop_handles_exception(self):
        """Test cleanup loop handles exceptions and continues (lines 229-232)."""
        import asyncio
        from redmine_mcp_server.redmine_handler import CleanupTaskManager

        # Save real sleep before patching
        real_sleep = asyncio.sleep

        # Make sleep return immediately but still be awaitable
        async def instant_sleep(seconds):
            await real_sleep(0.001)

        manager = CleanupTaskManager()
        manager.enabled = True
        manager.interval_seconds = 0.01

        # Create a mock file manager that raises exception
        mock_file_manager = Mock()
        call_count = [0]

        def cleanup_with_count():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise Exception("Test error")
            return {"cleaned_files": 0, "cleaned_mb": 0}

        mock_file_manager.cleanup_expired_files.side_effect = cleanup_with_count
        manager.manager = mock_file_manager

        with patch("redmine_mcp_server.redmine_handler.asyncio.sleep", instant_sleep):
            loop_task = asyncio.create_task(manager._cleanup_loop())
            await real_sleep(0.05)
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        # Verify cleanup was attempted
        assert mock_file_manager.cleanup_expired_files.called

    @pytest.mark.asyncio
    async def test_cleanup_loop_cancelled_error(self):
        """Test cleanup loop handles CancelledError gracefully (lines 226-228)."""
        import asyncio
        from redmine_mcp_server.redmine_handler import CleanupTaskManager

        manager = CleanupTaskManager()
        manager.enabled = True
        manager.interval_seconds = 10

        mock_file_manager = Mock()
        mock_file_manager.cleanup_expired_files.return_value = {
            "cleaned_files": 0,
            "cleaned_mb": 0,
        }
        manager.manager = mock_file_manager

        # Start the loop - it will hit initial sleep
        loop_task = asyncio.create_task(manager._cleanup_loop())

        # Give it time to start
        await asyncio.sleep(0.01)

        # Cancel it during the initial sleep
        loop_task.cancel()

        # Should raise CancelledError
        with pytest.raises(asyncio.CancelledError):
            await loop_task

    @pytest.mark.asyncio
    async def test_cleanup_loop_logs_cleaned_files(self):
        """Test cleanup loop logs when files are cleaned (lines 214-219)."""
        import asyncio
        from redmine_mcp_server.redmine_handler import CleanupTaskManager

        real_sleep = asyncio.sleep

        async def instant_sleep(seconds):
            await real_sleep(0.001)

        manager = CleanupTaskManager()
        manager.enabled = True
        manager.interval_seconds = 0.01

        mock_file_manager = Mock()
        mock_file_manager.cleanup_expired_files.return_value = {
            "cleaned_files": 5,
            "cleaned_mb": 1.5,
        }
        manager.manager = mock_file_manager

        with patch("redmine_mcp_server.redmine_handler.asyncio.sleep", instant_sleep):
            loop_task = asyncio.create_task(manager._cleanup_loop())
            await real_sleep(0.02)
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        assert mock_file_manager.cleanup_expired_files.called

    @pytest.mark.asyncio
    async def test_cleanup_loop_no_files_to_clean(self):
        """Test cleanup loop handles case with no expired files (lines 220-221)."""
        import asyncio
        from redmine_mcp_server.redmine_handler import CleanupTaskManager

        real_sleep = asyncio.sleep

        async def instant_sleep(seconds):
            await real_sleep(0.001)

        manager = CleanupTaskManager()
        manager.enabled = True
        manager.interval_seconds = 0.01

        mock_file_manager = Mock()
        mock_file_manager.cleanup_expired_files.return_value = {
            "cleaned_files": 0,
            "cleaned_mb": 0,
        }
        manager.manager = mock_file_manager

        with patch("redmine_mcp_server.redmine_handler.asyncio.sleep", instant_sleep):
            loop_task = asyncio.create_task(manager._cleanup_loop())
            await real_sleep(0.02)
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        assert mock_file_manager.cleanup_expired_files.called


class TestServeAttachmentEndpointEdgeCases:
    """Test serve_attachment HTTP endpoint edge cases (lines 332-333, 358)."""

    @pytest.mark.asyncio
    async def test_expired_file_cleanup_oserror_ignored(self, tmp_path):
        """Test OSError during expired file cleanup is ignored (lines 332-333)."""
        from pathlib import Path
        from datetime import datetime, timezone, timedelta
        import json
        import uuid as uuid_module
        from httpx import AsyncClient, ASGITransport
        from redmine_mcp_server.redmine_handler import mcp

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        file_id = str(uuid_module.uuid4())  # Valid UUID
        uuid_dir = attachments_dir / file_id
        uuid_dir.mkdir()

        # Create an expired file
        test_file = uuid_dir / "expired_file.txt"
        test_file.write_text("expired content")

        # Create metadata with expired timestamp
        expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        metadata = {
            "file_id": file_id,
            "original_filename": "expired_file.txt",
            "file_path": str(test_file),
            "expires_at": expires_at.isoformat(),
        }
        metadata_file = uuid_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))

        # Get the underlying Starlette app
        app = mcp.streamable_http_app()

        # Make the unlink fail during cleanup
        original_unlink = Path.unlink

        def selective_unlink(self, *args, **kwargs):
            # Only fail for our test file, not metadata
            if "expired_file.txt" in str(self):
                raise OSError("Cannot delete")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", selective_unlink):
            with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(attachments_dir)}):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(f"/files/{file_id}")

        # Should still return 404 (file expired) even if cleanup OSError occurred
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_datetime_format_in_metadata(self, tmp_path):
        """Test invalid datetime format returns 500 error (line 358)."""
        import json
        import uuid as uuid_module
        from httpx import AsyncClient, ASGITransport
        from redmine_mcp_server.redmine_handler import mcp

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        file_id = str(uuid_module.uuid4())  # Valid UUID
        uuid_dir = attachments_dir / file_id
        uuid_dir.mkdir()

        test_file = uuid_dir / "test_file.txt"
        test_file.write_text("test content")

        # Create metadata with INVALID datetime format
        metadata = {
            "file_id": file_id,
            "original_filename": "test_file.txt",
            "file_path": str(test_file),
            "expires_at": "not-a-valid-datetime",  # Invalid format
        }
        metadata_file = uuid_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))

        app = mcp.streamable_http_app()

        with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(attachments_dir)}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/files/{file_id}")

        # Should return 500 due to invalid datetime format
        assert response.status_code == 500
        assert "Invalid metadata format" in response.text
