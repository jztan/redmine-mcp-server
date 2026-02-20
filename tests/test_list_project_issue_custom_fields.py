"""
Test cases for list_project_issue_custom_fields tool.
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _custom_field_to_dict,
    list_project_issue_custom_fields,
)


def create_mock_custom_field(
    field_id=6,
    name="Size",
    field_format="list",
    is_required=False,
    multiple=False,
    default_value="M",
    possible_values=None,
    trackers=None,
):
    """Create a mock Redmine custom field with sensible defaults."""
    custom_field = Mock()
    custom_field.id = field_id
    custom_field.name = name
    custom_field.field_format = field_format
    custom_field.is_required = is_required
    custom_field.multiple = multiple
    custom_field.default_value = default_value
    custom_field.possible_values = (
        possible_values
        if possible_values is not None
        else [{"value": "S"}, {"value": "M"}]
    )
    custom_field.trackers = trackers if trackers is not None else []
    return custom_field


class TestCustomFieldToDict:
    """Unit tests for _custom_field_to_dict helper."""

    def test_serializes_expected_fields(self):
        """Helper should serialize metadata, values, and tracker bindings."""
        bug_tracker = Mock()
        bug_tracker.id = 5
        bug_tracker.name = "Bug"

        custom_field = create_mock_custom_field(trackers=[bug_tracker])
        result = _custom_field_to_dict(custom_field)

        assert result["id"] == 6
        assert result["name"] == "Size"
        assert result["field_format"] == "list"
        assert result["is_required"] is False
        assert result["multiple"] is False
        assert result["default_value"] == "M"
        assert result["possible_values"] == ["S", "M"]
        assert result["trackers"] == [{"id": 5, "name": "Bug"}]


class TestListProjectIssueCustomFields:
    """Unit tests for list_project_issue_custom_fields tool."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_list_project_issue_custom_fields_success(self, mock_redmine):
        """Returns project custom fields with metadata."""
        custom_field = create_mock_custom_field()
        project = Mock()
        project.issue_custom_fields = [custom_field]
        mock_redmine.project.get.return_value = project

        result = await list_project_issue_custom_fields(project_id=41)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == 6
        assert result[0]["name"] == "Size"
        assert result[0]["possible_values"] == ["S", "M"]
        mock_redmine.project.get.assert_called_once_with(
            41, include="issue_custom_fields"
        )

    @pytest.mark.asyncio
    async def test_list_project_issue_custom_fields_filters_by_tracker(
        self, mock_redmine
    ):
        """Tracker filtering keeps matching and global (unrestricted) custom fields."""
        tracker_bug = Mock()
        tracker_bug.id = 5
        tracker_bug.name = "Bug"

        tracker_feature = Mock()
        tracker_feature.id = 7
        tracker_feature.name = "Feature"

        for_bug = create_mock_custom_field(
            field_id=10, name="Bug-only", trackers=[tracker_bug]
        )
        for_feature = create_mock_custom_field(
            field_id=11, name="Feature-only", trackers=[tracker_feature]
        )
        global_field = create_mock_custom_field(field_id=12, name="Global", trackers=[])

        project = Mock()
        project.issue_custom_fields = [for_bug, for_feature, global_field]
        mock_redmine.project.get.return_value = project

        result = await list_project_issue_custom_fields(project_id=41, tracker_id=5)

        assert len(result) == 2
        assert {field["id"] for field in result} == {10, 12}

    @pytest.mark.asyncio
    async def test_list_project_issue_custom_fields_accepts_string_tracker_id(
        self, mock_redmine
    ):
        """String tracker IDs are accepted when parseable as integers."""
        tracker_bug = Mock()
        tracker_bug.id = 5
        tracker_bug.name = "Bug"

        field = create_mock_custom_field(field_id=10, trackers=[tracker_bug])
        project = Mock()
        project.issue_custom_fields = [field]
        mock_redmine.project.get.return_value = project

        result = await list_project_issue_custom_fields(
            project_id="pipeline", tracker_id="5"
        )

        assert len(result) == 1
        assert result[0]["id"] == 10
        mock_redmine.project.get.assert_called_once_with(
            "pipeline", include="issue_custom_fields"
        )

    @pytest.mark.asyncio
    async def test_list_project_issue_custom_fields_invalid_tracker_id(
        self, mock_redmine
    ):
        """Invalid tracker IDs should return a clear validation error."""
        result = await list_project_issue_custom_fields(project_id=41, tracker_id="abc")

        assert len(result) == 1
        assert "error" in result[0]
        assert "Invalid tracker_id" in result[0]["error"]
        mock_redmine.project.get.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_list_project_issue_custom_fields_no_client(self):
        """Returns initialization error when Redmine client is unavailable."""
        result = await list_project_issue_custom_fields(project_id=41)
        assert result == [{"error": "Redmine client not initialized."}]

    @pytest.mark.asyncio
    async def test_list_project_issue_custom_fields_error(self, mock_redmine):
        """API errors are returned in standard error format."""
        mock_redmine.project.get.side_effect = Exception("Boom")

        result = await list_project_issue_custom_fields(project_id=41)

        assert len(result) == 1
        assert "error" in result[0]
