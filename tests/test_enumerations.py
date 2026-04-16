"""Test cases for enumeration/lookup tools."""

import pytest
from unittest.mock import Mock, patch

from redmine_mcp_server.redmine_handler import list_time_entry_activities


class TestListTimeEntryActivities:
    """Test cases for list_time_entry_activities tool."""

    @pytest.fixture
    def mock_redmine(self):
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def _make_activity(self, id, name, active=True, is_default=False):
        m = Mock()
        m.id = id
        m.name = name
        m.active = active
        m.is_default = is_default
        return m

    @pytest.mark.asyncio
    async def test_list_activities_success(self, mock_redmine):
        mock_redmine.enumeration.filter.return_value = [
            self._make_activity(4, "Development"),
            self._make_activity(5, "Design"),
            self._make_activity(6, "Testing"),
        ]
        result = await list_time_entry_activities()
        assert len(result) == 3
        assert result[0]["id"] == 4
        assert result[0]["name"] == "Development"
        mock_redmine.enumeration.filter.assert_called_once_with(
            resource="time_entry_activities"
        )

    @pytest.mark.asyncio
    async def test_list_activities_empty(self, mock_redmine):
        mock_redmine.enumeration.filter.return_value = []
        result = await list_time_entry_activities()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_activities_field_structure(self, mock_redmine):
        mock_redmine.enumeration.filter.return_value = [
            self._make_activity(4, "Development", active=True, is_default=True),
        ]
        result = await list_time_entry_activities()
        activity = result[0]
        assert set(activity.keys()) == {"id", "name", "active", "is_default"}
        assert activity["active"] is True
        assert activity["is_default"] is True

    @pytest.mark.asyncio
    async def test_list_activities_client_not_initialized(self, mock_redmine):
        mock_redmine.enumeration.filter.side_effect = RuntimeError(
            "No Redmine authentication available."
        )
        result = await list_time_entry_activities()
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_list_activities_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.enumeration.filter.side_effect = ForbiddenError()
        result = await list_time_entry_activities()
        assert len(result) == 1
        assert "error" in result[0]


class TestListTimeEntryActivitiesProjectScoped:
    """Test cases for list_time_entry_activities with project_id."""

    def _make_activity(self, id, name, active=True, is_default=False):
        m = Mock()
        m.id = id
        m.name = name
        m.active = active
        m.is_default = is_default
        return m

    @pytest.mark.asyncio
    async def test_project_scoped_returns_activities(self):
        mock_client = Mock()
        mock_project = Mock()
        mock_project.time_entry_activities = [
            self._make_activity(9, "Development"),
            self._make_activity(10, "Design"),
        ]
        mock_client.project.get.return_value = mock_project

        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            return_value=mock_client,
        ):
            result = await list_time_entry_activities(project_id="my-project")

        assert isinstance(result, dict)
        assert result["project_id"] == "my-project"
        assert len(result["activities"]) == 2
        assert result["activities"][0] == {
            "id": 9, "name": "Development", "active": True, "is_default": False
        }
        assert result["activities"][1] == {
            "id": 10, "name": "Design", "active": True, "is_default": False
        }
        assert "note" not in result
        mock_client.project.get.assert_called_once_with(
            "my-project", include="time_entry_activities"
        )

    @pytest.mark.asyncio
    async def test_project_scoped_empty_includes_note(self):
        mock_client = Mock()
        mock_project = Mock()
        mock_project.time_entry_activities = []
        mock_client.project.get.return_value = mock_project

        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            return_value=mock_client,
        ):
            result = await list_time_entry_activities(project_id="my-project")

        assert isinstance(result, dict)
        assert result["project_id"] == "my-project"
        assert result["activities"] == []
        assert "note" in result
        assert "list_time_entry_activities" in result["note"]

    @pytest.mark.asyncio
    async def test_project_scoped_numeric_id(self):
        mock_client = Mock()
        mock_project = Mock()
        mock_project.time_entry_activities = [
            self._make_activity(9, "Development"),
        ]
        mock_client.project.get.return_value = mock_project

        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            return_value=mock_client,
        ):
            result = await list_time_entry_activities(project_id=42)

        assert result["project_id"] == 42
        assert len(result["activities"]) == 1
        mock_client.project.get.assert_called_once_with(
            42, include="time_entry_activities"
        )

    @pytest.mark.asyncio
    async def test_project_scoped_not_found_returns_error(self):
        from redminelib.exceptions import ResourceNotFoundError

        mock_client = Mock()
        mock_client.project.get.side_effect = ResourceNotFoundError()

        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            return_value=mock_client,
        ):
            result = await list_time_entry_activities(project_id="nonexistent")

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_project_scoped_forbidden_returns_error(self):
        from redminelib.exceptions import ForbiddenError

        mock_client = Mock()
        mock_client.project.get.side_effect = ForbiddenError()

        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            return_value=mock_client,
        ):
            result = await list_time_entry_activities(project_id="secret-project")

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_project_scoped_missing_attribute_returns_empty(self):
        """Older Redmine versions may not return time_entry_activities on the
        project object — the getattr fallback should produce an empty list
        with a note rather than raising AttributeError."""
        mock_client = Mock()
        mock_project = Mock(spec=[])  # no attributes at all
        mock_client.project.get.return_value = mock_project

        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            return_value=mock_client,
        ):
            result = await list_time_entry_activities(project_id="old-redmine")

        assert isinstance(result, dict)
        assert result["project_id"] == "old-redmine"
        assert result["activities"] == []
        assert "note" in result
