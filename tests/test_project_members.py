"""
Test cases for list_project_members tool.

Tests for listing project memberships including users, groups, and roles.
"""

import pytest
from unittest.mock import Mock, patch

from redmine_mcp_server.redmine_handler import (
    list_project_members,
    _membership_to_dict,
)


def make_mock_with_name(id_val, name_val):
    """Helper to create a Mock with a name attribute (not Mock's internal name)."""
    m = Mock()
    m.id = id_val
    m.name = name_val
    return m


class TestMembershipToDict:
    """Test cases for _membership_to_dict helper function."""

    def test_user_membership(self):
        """Test converting a user membership to dict."""
        mock_membership = Mock()
        mock_membership.id = 1
        mock_membership.user = make_mock_with_name(5, "John Doe")
        mock_membership.group = None
        mock_membership.project = make_mock_with_name(10, "Test Project")
        mock_membership.roles = [make_mock_with_name(3, "Developer")]

        result = _membership_to_dict(mock_membership)

        assert result["id"] == 1
        assert result["user"] == {"id": 5, "name": "John Doe"}
        assert result["group"] is None
        assert result["project"] == {"id": 10, "name": "Test Project"}
        assert len(result["roles"]) == 1
        assert result["roles"][0] == {"id": 3, "name": "Developer"}

    def test_group_membership(self):
        """Test converting a group membership to dict."""
        mock_membership = Mock()
        mock_membership.id = 2
        mock_membership.user = None
        mock_membership.group = make_mock_with_name(15, "Dev Team")
        mock_membership.project = make_mock_with_name(10, "Test Project")
        mock_membership.roles = [make_mock_with_name(4, "Manager")]

        result = _membership_to_dict(mock_membership)

        assert result["id"] == 2
        assert result["user"] is None
        assert result["group"] == {"id": 15, "name": "Dev Team"}
        assert result["project"] == {"id": 10, "name": "Test Project"}
        assert len(result["roles"]) == 1
        assert result["roles"][0] == {"id": 4, "name": "Manager"}

    def test_multiple_roles(self):
        """Test membership with multiple roles."""
        mock_membership = Mock()
        mock_membership.id = 3
        mock_membership.user = make_mock_with_name(5, "John Doe")
        mock_membership.group = None
        mock_membership.project = make_mock_with_name(10, "Test Project")
        mock_membership.roles = [
            make_mock_with_name(3, "Developer"),
            make_mock_with_name(4, "Reporter"),
        ]

        result = _membership_to_dict(mock_membership)

        assert len(result["roles"]) == 2
        assert result["roles"][0] == {"id": 3, "name": "Developer"}
        assert result["roles"][1] == {"id": 4, "name": "Reporter"}

    def test_no_roles(self):
        """Test membership with no roles."""
        mock_membership = Mock()
        mock_membership.id = 4
        mock_membership.user = make_mock_with_name(5, "John Doe")
        mock_membership.group = None
        mock_membership.project = make_mock_with_name(10, "Test Project")
        mock_membership.roles = []

        result = _membership_to_dict(mock_membership)

        assert result["roles"] == []

    def test_dict_format_roles(self):
        """Test roles in dict format (some Redmine versions)."""
        mock_membership = Mock()
        mock_membership.id = 5
        mock_membership.user = make_mock_with_name(5, "John Doe")
        mock_membership.group = None
        mock_membership.project = make_mock_with_name(10, "Test Project")
        mock_membership.roles = [{"id": 3, "name": "Developer"}]

        result = _membership_to_dict(mock_membership)

        assert len(result["roles"]) == 1
        assert result["roles"][0] == {"id": 3, "name": "Developer"}

    def test_missing_attributes(self):
        """Test handling of missing attributes."""
        mock_membership = Mock(spec=[])  # Empty spec, no attributes
        mock_membership.id = None
        mock_membership.user = None
        mock_membership.group = None
        mock_membership.project = None
        mock_membership.roles = None

        result = _membership_to_dict(mock_membership)

        assert result["id"] is None
        assert result["user"] is None
        assert result["group"] is None
        assert result["project"] is None
        assert result["roles"] == []


class TestListProjectMembers:
    """Test cases for list_project_members tool."""

    @pytest.fixture
    def mock_redmine(self):
        """Create a mock Redmine client."""
        with patch("redmine_mcp_server.redmine_handler.redmine") as mock:
            yield mock

    def create_mock_membership(
        self, membership_id=1, user_id=5, user_name="John Doe", is_group=False
    ):
        """Create a single mock membership."""
        mock_membership = Mock()
        mock_membership.id = membership_id

        if is_group:
            mock_membership.user = None
            mock_membership.group = make_mock_with_name(user_id, user_name)
        else:
            mock_membership.user = make_mock_with_name(user_id, user_name)
            mock_membership.group = None

        mock_membership.project = make_mock_with_name(10, "Test Project")
        mock_membership.roles = [make_mock_with_name(3, "Developer")]

        return mock_membership

    @pytest.mark.asyncio
    async def test_list_members_by_project_id(self, mock_redmine):
        """Test listing project members by numeric project ID."""
        mock_memberships = [
            self.create_mock_membership(1, 5, "John Doe"),
            self.create_mock_membership(2, 6, "Jane Smith"),
        ]
        mock_redmine.project_membership.filter.return_value = mock_memberships

        result = await list_project_members(project_id=10)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["user"]["name"] == "John Doe"
        assert result[1]["user"]["name"] == "Jane Smith"
        mock_redmine.project_membership.filter.assert_called_once_with(project_id=10)

    @pytest.mark.asyncio
    async def test_list_members_by_project_identifier(self, mock_redmine):
        """Test listing project members by string project identifier."""
        mock_memberships = [self.create_mock_membership(1, 5, "John Doe")]
        mock_redmine.project_membership.filter.return_value = mock_memberships

        result = await list_project_members(project_id="my-project")

        assert isinstance(result, list)
        assert len(result) == 1
        mock_redmine.project_membership.filter.assert_called_once_with(
            project_id="my-project"
        )

    @pytest.mark.asyncio
    async def test_list_members_includes_groups(self, mock_redmine):
        """Test that group memberships are included."""
        mock_memberships = [
            self.create_mock_membership(1, 5, "John Doe", is_group=False),
            self.create_mock_membership(2, 15, "Dev Team", is_group=True),
        ]
        mock_redmine.project_membership.filter.return_value = mock_memberships

        result = await list_project_members(project_id=10)

        assert len(result) == 2
        # First is a user
        assert result[0]["user"] is not None
        assert result[0]["group"] is None
        # Second is a group
        assert result[1]["user"] is None
        assert result[1]["group"] is not None
        assert result[1]["group"]["name"] == "Dev Team"

    @pytest.mark.asyncio
    async def test_list_members_empty_project(self, mock_redmine):
        """Test listing members of a project with no members."""
        mock_redmine.project_membership.filter.return_value = []

        result = await list_project_members(project_id=10)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_members_redmine_not_initialized(self):
        """Test error when Redmine client is not initialized."""
        with patch(
            "redmine_mcp_server.redmine_handler._get_redmine_client",
            side_effect=RuntimeError("No Redmine authentication available"),
        ):
            result = await list_project_members(project_id=10)

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_list_members_project_not_found(self, mock_redmine):
        """Test error when project is not found."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.project_membership.filter.side_effect = ResourceNotFoundError()

        result = await list_project_members(project_id=999)

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_list_members_forbidden(self, mock_redmine):
        """Test error when user lacks permission."""
        from redminelib.exceptions import ForbiddenError

        mock_redmine.project_membership.filter.side_effect = ForbiddenError()

        result = await list_project_members(project_id=10)

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]
        assert "Access denied" in result[0]["error"]

    @pytest.mark.asyncio
    async def test_list_members_includes_roles(self, mock_redmine):
        """Test that roles are included in membership data."""
        mock_membership = Mock()
        mock_membership.id = 1
        mock_membership.user = make_mock_with_name(5, "John Doe")
        mock_membership.group = None
        mock_membership.project = make_mock_with_name(10, "Test Project")
        mock_membership.roles = [
            make_mock_with_name(3, "Developer"),
            make_mock_with_name(4, "Reporter"),
        ]
        mock_redmine.project_membership.filter.return_value = [mock_membership]

        result = await list_project_members(project_id=10)

        assert len(result) == 1
        assert len(result[0]["roles"]) == 2
        role_names = [r["name"] for r in result[0]["roles"]]
        assert "Developer" in role_names
        assert "Reporter" in role_names
