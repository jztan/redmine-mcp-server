"""Unit tests for discovery/enumeration tools.

Covers:
    - list_redmine_trackers
    - list_redmine_issue_statuses
    - list_redmine_issue_priorities
    - list_redmine_users
    - get_current_user
    - list_redmine_queries
"""

import os
import sys

import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    get_current_user,
    list_redmine_issue_priorities,
    list_redmine_issue_statuses,
    list_redmine_queries,
    list_redmine_trackers,
    list_redmine_users,
)


def _mock_obj(**attrs):
    """Make a Mock that only exposes the attributes we pass in (no magic
    auto-generated ones), so getattr(..., default) fallbacks work."""
    m = Mock(spec=list(attrs.keys()))
    for key, value in attrs.items():
        setattr(m, key, value)
    return m


# ---------------------------------------------------------------------------
# list_redmine_trackers
# ---------------------------------------------------------------------------


class TestListRedmineTrackers:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_returns_trackers(self, mock_redmine):
        mock_redmine.tracker.all.return_value = [
            _mock_obj(id=1, name="Bug", description=""),
            _mock_obj(id=2, name="Feature", description="New feature requests"),
            _mock_obj(id=3, name="Support", description=""),
        ]

        result = await list_redmine_trackers()

        assert result == [
            {"id": 1, "name": "Bug", "description": ""},
            {"id": 2, "name": "Feature", "description": "New feature requests"},
            {"id": 3, "name": "Support", "description": ""},
        ]
        mock_redmine.tracker.all.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_empty(self, mock_redmine):
        mock_redmine.tracker.all.return_value = []
        assert await list_redmine_trackers() == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_auth_error(self, mock_redmine):
        from redminelib.exceptions import AuthError

        mock_redmine.tracker.all.side_effect = AuthError()
        result = await list_redmine_trackers()
        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# list_redmine_issue_statuses
# ---------------------------------------------------------------------------


class TestListRedmineIssueStatuses:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_returns_statuses(self, mock_redmine):
        mock_redmine.issue_status.all.return_value = [
            _mock_obj(id=1, name="New", is_closed=False),
            _mock_obj(id=2, name="In Progress", is_closed=False),
            _mock_obj(id=5, name="Closed", is_closed=True),
        ]

        result = await list_redmine_issue_statuses()

        assert result == [
            {"id": 1, "name": "New", "is_closed": False},
            {"id": 2, "name": "In Progress", "is_closed": False},
            {"id": 5, "name": "Closed", "is_closed": True},
        ]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_is_closed_missing_defaults_false(self, mock_redmine):
        """When a status object doesn't expose is_closed, we default to False."""
        mock_redmine.issue_status.all.return_value = [
            _mock_obj(id=1, name="New"),
        ]

        result = await list_redmine_issue_statuses()
        assert result[0]["is_closed"] is False

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.issue_status.all.side_effect = ForbiddenError()
        result = await list_redmine_issue_statuses()
        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# list_redmine_issue_priorities
# ---------------------------------------------------------------------------


class TestListRedmineIssuePriorities:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_returns_priorities(self, mock_redmine):
        mock_redmine.enumeration.filter.return_value = [
            _mock_obj(id=1, name="Low", active=True, is_default=False),
            _mock_obj(id=2, name="Normal", active=True, is_default=True),
            _mock_obj(id=3, name="High", active=True, is_default=False),
        ]

        result = await list_redmine_issue_priorities()

        assert len(result) == 3
        assert result[1] == {
            "id": 2,
            "name": "Normal",
            "active": True,
            "is_default": True,
        }
        # Must use the correct enumeration type
        mock_redmine.enumeration.filter.assert_called_once_with(
            resource="issue_priorities"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_empty(self, mock_redmine):
        mock_redmine.enumeration.filter.return_value = []
        assert await list_redmine_issue_priorities() == []


# ---------------------------------------------------------------------------
# list_redmine_users
# ---------------------------------------------------------------------------


class TestListRedmineUsers:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_basic_list(self, mock_redmine):
        mock_redmine.user.filter.return_value = [
            _mock_obj(
                id=1,
                login="alice",
                firstname="Alice",
                lastname="A",
                mail="a@x.com",
                created_on=None,
            ),
            _mock_obj(
                id=2,
                login="bob",
                firstname="Bob",
                lastname="B",
                mail="b@x.com",
                created_on=None,
            ),
        ]

        result = await list_redmine_users()

        assert len(result) == 2
        assert result[0]["login"] == "alice"
        assert result[1]["login"] == "bob"
        mock_redmine.user.filter.assert_called_once_with(limit=25, offset=0)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_with_name_filter(self, mock_redmine):
        mock_redmine.user.filter.return_value = []
        await list_redmine_users(name="alice")
        mock_redmine.user.filter.assert_called_once_with(
            limit=25, offset=0, name="alice"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_with_group_filter(self, mock_redmine):
        mock_redmine.user.filter.return_value = []
        await list_redmine_users(group_id=7)
        mock_redmine.user.filter.assert_called_once_with(limit=25, offset=0, group_id=7)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_limit_clamped(self, mock_redmine):
        """Limit is clamped to the 1-100 range."""
        mock_redmine.user.filter.return_value = []
        await list_redmine_users(limit=500)
        _, kwargs = mock_redmine.user.filter.call_args
        assert kwargs["limit"] == 100

        mock_redmine.user.filter.reset_mock()
        await list_redmine_users(limit=0)
        _, kwargs = mock_redmine.user.filter.call_args
        assert kwargs["limit"] == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_forbidden(self, mock_redmine):
        """Non-admin users get 403 when listing all users."""
        from redminelib.exceptions import ForbiddenError

        mock_redmine.user.filter.side_effect = ForbiddenError()
        result = await list_redmine_users()
        assert isinstance(result, dict)
        assert "error" in result
        assert "Access denied" in result["error"]


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_returns_current_user(self, mock_redmine):
        mock_redmine.user.get.return_value = _mock_obj(
            id=5,
            login="alice",
            firstname="Alice",
            lastname="A",
            mail="alice@example.com",
            admin=False,
            created_on=None,
            last_login_on=None,
        )

        result = await get_current_user()

        assert result["id"] == 5
        assert result["login"] == "alice"
        assert result["admin"] is False
        mock_redmine.user.get.assert_called_once_with("current")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_admin_user(self, mock_redmine):
        mock_redmine.user.get.return_value = _mock_obj(
            id=1,
            login="admin",
            firstname="Admin",
            lastname="User",
            mail="admin@example.com",
            admin=True,
            created_on=None,
            last_login_on=None,
        )
        result = await get_current_user()
        assert result["admin"] is True

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_auth_error(self, mock_redmine):
        from redminelib.exceptions import AuthError

        mock_redmine.user.get.side_effect = AuthError()
        result = await get_current_user()
        assert "error" in result


# ---------------------------------------------------------------------------
# list_redmine_queries
# ---------------------------------------------------------------------------


class TestListRedmineQueries:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_returns_queries(self, mock_redmine):
        mock_redmine.query.all.return_value = [
            _mock_obj(id=1, name="Open bugs", is_public=True, project_id=10),
            _mock_obj(id=2, name="My tasks", is_public=False, project_id=None),
        ]

        result = await list_redmine_queries()

        assert result == [
            {"id": 1, "name": "Open bugs", "is_public": True, "project_id": 10},
            {"id": 2, "name": "My tasks", "is_public": False, "project_id": None},
        ]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_empty(self, mock_redmine):
        mock_redmine.query.all.return_value = []
        assert await list_redmine_queries() == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_missing_project_id(self, mock_redmine):
        """Some queries have no project scope — project_id should default
        to None."""
        mock_redmine.query.all.return_value = [
            _mock_obj(id=3, name="Cross-project", is_public=True),
        ]
        result = await list_redmine_queries()
        assert result[0]["project_id"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.query.all.side_effect = ForbiddenError()
        result = await list_redmine_queries()
        assert isinstance(result, dict)
        assert "error" in result
