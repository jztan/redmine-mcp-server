"""
Test cases for list_redmine_versions tool.

TDD RED phase: Tests written before implementation.
Follows 4 TDD cycles from tdd-plan-list-redmine-versions.md.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date, datetime
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _version_to_dict,
    list_redmine_versions,
)


def create_mock_version(
    version_id=1,
    name="v1.0",
    description="Test version",
    status="open",
    due_date=date(2026, 3, 1),
    sharing="none",
    wiki_page_title="",
    project_id=1,
    project_name="Test Project",
):
    """Create a mock version with sensible defaults."""
    mock_version = Mock()
    mock_version.id = version_id
    mock_version.name = name
    mock_version.description = description
    mock_version.status = status
    mock_version.due_date = due_date
    mock_version.sharing = sharing
    mock_version.wiki_page_title = wiki_page_title
    mock_project = Mock()
    mock_project.id = project_id
    mock_project.name = project_name
    mock_version.project = mock_project
    mock_version.created_on = datetime(2026, 1, 1, 10, 0, 0)
    mock_version.updated_on = datetime(2026, 2, 1, 14, 30, 0)
    return mock_version


# ── Cycle 1: _version_to_dict() helper ──────────────────────────────


class TestVersionToDict:
    """Test cases for _version_to_dict helper."""

    def test_full_version_all_fields(self):
        """Test conversion with all fields populated."""
        mock_version = Mock()
        mock_version.id = 1
        mock_version.name = "v1.0"
        mock_version.description = "First release"
        mock_version.status = "open"
        mock_version.due_date = date(2026, 3, 1)
        mock_version.sharing = "none"
        mock_version.wiki_page_title = "Release_v1"
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_version.project = mock_project
        mock_version.created_on = datetime(2026, 1, 1, 10, 0, 0)
        mock_version.updated_on = datetime(2026, 2, 1, 14, 30, 0)

        result = _version_to_dict(mock_version)

        assert result["id"] == 1
        assert result["name"] == "v1.0"
        assert result["description"] == "First release"
        assert result["status"] == "open"
        assert result["due_date"] == "2026-03-01"
        assert result["sharing"] == "none"
        assert result["wiki_page_title"] == "Release_v1"
        assert result["project"] == {"id": 1, "name": "Test Project"}
        assert result["created_on"] == "2026-01-01T10:00:00"
        assert result["updated_on"] == "2026-02-01T14:30:00"

    def test_none_due_date(self):
        """Test that None due_date is preserved as None."""
        mock_version = create_mock_version(due_date=None)

        result = _version_to_dict(mock_version)

        assert result["due_date"] is None

    def test_none_project(self):
        """Test that missing project returns None."""
        mock_version = create_mock_version()
        mock_version.project = None

        result = _version_to_dict(mock_version)

        assert result["project"] is None

    def test_missing_optional_fields(self):
        """Test conversion when optional attributes are absent."""
        mock_version = Mock(spec=[])  # Empty spec, no attributes
        mock_version.id = 5
        mock_version.name = "v2.0"
        # All other attributes missing (getattr should return defaults)

        result = _version_to_dict(mock_version)

        assert result["id"] == 5
        assert result["name"] == "v2.0"
        assert result["description"] == ""
        assert result["status"] == ""
        assert result["due_date"] is None
        assert result["sharing"] == ""
        assert result["wiki_page_title"] == ""
        assert result["project"] is None
        assert result["created_on"] is None
        assert result["updated_on"] is None

    def test_status_is_plain_string(self):
        """Test that status is returned as a plain string, not a dict."""
        mock_version = create_mock_version(status="closed")

        result = _version_to_dict(mock_version)

        assert result["status"] == "closed"
        assert isinstance(result["status"], str)


# ── Cycle 2: list_redmine_versions() basic functionality ────────────


class TestListRedmineVersions:
    """Test cases for list_redmine_versions tool."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_list_versions_by_project_id(self, mock_redmine):
        """Test listing versions for a project by numeric ID."""
        mock_versions = [
            create_mock_version(version_id=1, name="v1.0"),
            create_mock_version(version_id=2, name="v2.0"),
        ]
        mock_redmine.version.filter.return_value = mock_versions

        result = await list_redmine_versions(project_id=1)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "v1.0"
        assert result[1]["name"] == "v2.0"
        mock_redmine.version.filter.assert_called_once_with(project_id=1)

    @pytest.mark.asyncio
    async def test_list_versions_by_string_identifier(self, mock_redmine):
        """Test listing versions using string project identifier."""
        mock_versions = [create_mock_version()]
        mock_redmine.version.filter.return_value = mock_versions

        result = await list_redmine_versions(project_id="my-project")

        mock_redmine.version.filter.assert_called_once_with(project_id="my-project")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_versions_empty_result(self, mock_redmine):
        """Test listing versions when project has none."""
        mock_redmine.version.filter.return_value = []

        result = await list_redmine_versions(project_id=1)

        assert result == []

    @pytest.mark.asyncio
    async def test_version_dict_structure(self, mock_redmine):
        """Test that returned dicts have expected keys."""
        mock_versions = [create_mock_version(version_id=1, name="v1.0", status="open")]
        mock_redmine.version.filter.return_value = mock_versions

        result = await list_redmine_versions(project_id=1)

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

    # ── Cycle 3: Status filtering ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_filter_open_versions(self, mock_redmine):
        """Test filtering to only open versions."""
        mock_versions = [
            create_mock_version(version_id=1, name="v1.0", status="open"),
            create_mock_version(version_id=2, name="v2.0", status="closed"),
            create_mock_version(version_id=3, name="v3.0", status="open"),
        ]
        mock_redmine.version.filter.return_value = mock_versions

        result = await list_redmine_versions(project_id=1, status_filter="open")

        assert len(result) == 2
        assert all(v["status"] == "open" for v in result)

    @pytest.mark.asyncio
    async def test_filter_closed_versions(self, mock_redmine):
        """Test filtering to only closed versions."""
        mock_versions = [
            create_mock_version(version_id=1, status="open"),
            create_mock_version(version_id=2, status="closed"),
        ]
        mock_redmine.version.filter.return_value = mock_versions

        result = await list_redmine_versions(project_id=1, status_filter="closed")

        assert len(result) == 1
        assert result[0]["status"] == "closed"

    @pytest.mark.asyncio
    async def test_filter_locked_versions(self, mock_redmine):
        """Test filtering to only locked versions."""
        mock_versions = [
            create_mock_version(version_id=1, status="open"),
            create_mock_version(version_id=2, status="locked"),
        ]
        mock_redmine.version.filter.return_value = mock_versions

        result = await list_redmine_versions(project_id=1, status_filter="locked")

        assert len(result) == 1
        assert result[0]["status"] == "locked"

    @pytest.mark.asyncio
    async def test_no_status_filter_returns_all(self, mock_redmine):
        """Test that None status_filter returns all versions."""
        mock_versions = [
            create_mock_version(version_id=1, status="open"),
            create_mock_version(version_id=2, status="closed"),
            create_mock_version(version_id=3, status="locked"),
        ]
        mock_redmine.version.filter.return_value = mock_versions

        result = await list_redmine_versions(project_id=1)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_invalid_status_filter_returns_error(self, mock_redmine):
        """Test that invalid status_filter returns error dict."""
        result = await list_redmine_versions(project_id=1, status_filter="invalid")

        assert len(result) == 1
        assert "error" in result[0]
        assert "invalid" in result[0]["error"].lower()

    # ── Cycle 4: Error handling ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_client_returns_error(self):
        """Test error when Redmine client is not initialized."""
        with patch("redmine_mcp_server.redmine_handler.redmine", None):
            result = await list_redmine_versions(project_id=1)

        assert isinstance(result, list)
        assert result[0]["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    async def test_api_error_returns_error(self, mock_redmine):
        """Test error handling when API call fails."""
        mock_redmine.version.filter.side_effect = Exception("Connection refused")

        result = await list_redmine_versions(project_id=1)

        assert isinstance(result, list)
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_project_not_found_error(self, mock_redmine):
        """Test error handling when project doesn't exist."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.version.filter.side_effect = ResourceNotFoundError()

        result = await list_redmine_versions(project_id=999)

        assert isinstance(result, list)
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_forbidden_error(self, mock_redmine):
        """Test error handling when user lacks permission."""
        from redminelib.exceptions import ForbiddenError

        mock_redmine.version.filter.side_effect = ForbiddenError()

        result = await list_redmine_versions(project_id=1)

        assert isinstance(result, list)
        assert "error" in result[0]
