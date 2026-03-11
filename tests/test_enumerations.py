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
