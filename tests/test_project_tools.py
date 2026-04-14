"""Unit tests for Stage C project tools.

Covers:
    - get_project_modules
    - add_project_member / update_project_member / remove_project_member
"""

import os
import sys

import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    add_project_member,
    get_project_modules,
    list_redmine_roles,
    remove_project_member,
    update_project_member,
)


def _mock_with_name(id_val, name_val):
    m = Mock()
    m.id = id_val
    m.name = name_val
    return m


def _mock_membership(
    membership_id=1,
    user_id=5,
    user_name="Alice",
    project_id=10,
    project_name="Test Project",
    role_ids=None,
):
    if role_ids is None:
        role_ids = [3]
    m = Mock()
    m.id = membership_id
    m.user = _mock_with_name(user_id, user_name)
    m.group = None
    m.project = _mock_with_name(project_id, project_name)
    m.roles = [_mock_with_name(rid, f"Role{rid}") for rid in role_ids]
    return m


# ---------------------------------------------------------------------------
# get_project_modules
# ---------------------------------------------------------------------------


class TestGetProjectModules:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_returns_module_names(self, mock_redmine):
        """Standard path: python-redmine returns enabled_modules as a
        list of strings (after its Project.encode() transformation)."""
        project = Mock()
        project.id = 1
        project.name = "My Project"
        project.enabled_modules = ["issue_tracking", "wiki", "time_tracking"]
        mock_redmine.project.get.return_value = project

        result = await get_project_modules(project_id="my-project")

        assert result["project_id"] == 1
        assert result["project_name"] == "My Project"
        assert result["enabled_modules"] == [
            "issue_tracking",
            "wiki",
            "time_tracking",
        ]
        mock_redmine.project.get.assert_called_once_with(
            "my-project", include="enabled_modules"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_handles_string_modules(self, mock_redmine):
        """python-redmine's Project.encode() transforms enabled_modules
        to a plain list of strings."""
        project = Mock()
        project.id = 2
        project.name = "Web App"
        project.enabled_modules = [
            "issue_tracking",
            "time_tracking",
            "wiki",
            "repository",
        ]
        mock_redmine.project.get.return_value = project

        result = await get_project_modules(project_id=2)

        assert result["enabled_modules"] == [
            "issue_tracking",
            "time_tracking",
            "wiki",
            "repository",
        ]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_handles_dict_modules(self, mock_redmine):
        """Some Redmine versions return modules as plain dicts."""
        project = Mock()
        project.id = 2
        project.name = "Other"
        project.enabled_modules = [
            {"name": "issue_tracking"},
            {"name": "files"},
        ]
        mock_redmine.project.get.return_value = project

        result = await get_project_modules(project_id=2)

        assert result["enabled_modules"] == ["issue_tracking", "files"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_empty_modules(self, mock_redmine):
        project = Mock()
        project.id = 3
        project.name = "Empty"
        project.enabled_modules = []
        mock_redmine.project.get.return_value = project

        result = await get_project_modules(project_id=3)
        assert result["enabled_modules"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_missing_modules_attribute(self, mock_redmine):
        project = Mock(spec=["id", "name"])
        project.id = 4
        project.name = "NoModules"
        mock_redmine.project.get.return_value = project

        result = await get_project_modules(project_id=4)
        assert result["enabled_modules"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_project_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.project.get.side_effect = ResourceNotFoundError()
        result = await get_project_modules(project_id=9999)
        assert "error" in result


# ---------------------------------------------------------------------------
# add_project_member
# ---------------------------------------------------------------------------


class TestAddProjectMember:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_add_user(self, mock_redmine):
        mock_redmine.project_membership.create.return_value = _mock_membership(
            membership_id=100, user_id=5, user_name="Alice", role_ids=[3]
        )

        result = await add_project_member(
            project_id="my-project", role_ids=[3], user_id=5
        )

        assert result["id"] == 100
        assert result["user"] == {"id": 5, "name": "Alice"}
        mock_redmine.project_membership.create.assert_called_once_with(
            project_id="my-project", user_id=5, role_ids=[3]
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_add_group(self, mock_redmine):
        """Redmine's membership API uses user_id for both users and groups
        (principal ID namespace is shared). The tool forwards group_id via
        the user_id field."""
        m = Mock()
        m.id = 101
        m.user = None
        m.group = _mock_with_name(20, "Dev Team")
        m.project = _mock_with_name(10, "Proj")
        m.roles = [_mock_with_name(3, "Developer")]
        mock_redmine.project_membership.create.return_value = m

        result = await add_project_member(project_id=10, role_ids=[3], group_id=20)

        assert result["group"] == {"id": 20, "name": "Dev Team"}
        assert result["user"] is None
        # Verify group_id was forwarded as user_id (Redmine API convention)
        mock_redmine.project_membership.create.assert_called_once_with(
            project_id=10, user_id=20, role_ids=[3]
        )

    @pytest.mark.asyncio
    async def test_missing_user_and_group(self):
        result = await add_project_member(project_id=10, role_ids=[3])
        assert "error" in result
        assert "user_id or group_id" in result["error"]

    @pytest.mark.asyncio
    async def test_both_user_and_group(self):
        result = await add_project_member(
            project_id=10, role_ids=[3], user_id=5, group_id=20
        )
        assert "error" in result
        assert "Exactly one" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_role_ids(self):
        result = await add_project_member(project_id=10, role_ids=[], user_id=5)
        assert "error" in result
        assert "role_id" in result["error"]

    @pytest.mark.asyncio
    async def test_non_integer_role_ids(self):
        result = await add_project_member(project_id=10, role_ids=["admin"], user_id=5)
        assert "error" in result
        assert "integers" in result["error"]

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await add_project_member(project_id=10, role_ids=[3], user_id=5)
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_project_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.project_membership.create.side_effect = ResourceNotFoundError()
        result = await add_project_member(project_id=9999, role_ids=[3], user_id=5)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.project_membership.create.side_effect = ForbiddenError()
        result = await add_project_member(project_id=10, role_ids=[3], user_id=5)
        assert "error" in result
        assert "Access denied" in result["error"]


# ---------------------------------------------------------------------------
# update_project_member
# ---------------------------------------------------------------------------


class TestUpdateProjectMember:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_roles(self, mock_redmine):
        mock_redmine.project_membership.update.return_value = True
        updated = _mock_membership(membership_id=42, role_ids=[3, 4])
        mock_redmine.project_membership.get.return_value = updated

        result = await update_project_member(membership_id=42, role_ids=[3, 4])

        assert result["id"] == 42
        assert len(result["roles"]) == 2
        mock_redmine.project_membership.update.assert_called_once_with(
            42, role_ids=[3, 4]
        )
        mock_redmine.project_membership.get.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_empty_role_ids(self):
        result = await update_project_member(membership_id=42, role_ids=[])
        assert "error" in result

    @pytest.mark.asyncio
    async def test_non_integer_role_ids(self):
        result = await update_project_member(membership_id=42, role_ids=["admin"])
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await update_project_member(membership_id=42, role_ids=[3])
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_membership_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.project_membership.update.side_effect = ResourceNotFoundError()
        result = await update_project_member(membership_id=9999, role_ids=[3])
        assert "error" in result


# ---------------------------------------------------------------------------
# remove_project_member
# ---------------------------------------------------------------------------


class TestRemoveProjectMember:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_remove_success(self, mock_redmine):
        mock_redmine.project_membership.delete.return_value = True

        result = await remove_project_member(membership_id=42)

        assert result == {"success": True, "deleted_membership_id": 42}
        mock_redmine.project_membership.delete.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await remove_project_member(membership_id=42)
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_membership_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.project_membership.delete.side_effect = ResourceNotFoundError()
        result = await remove_project_member(membership_id=9999)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_inherited_membership_error(self, mock_redmine):
        """Redmine returns 422 for inherited memberships that cannot be removed."""
        from redminelib.exceptions import ValidationError

        mock_redmine.project_membership.delete.side_effect = ValidationError(
            "Cannot remove inherited membership"
        )
        result = await remove_project_member(membership_id=42)
        assert "error" in result


# ---------------------------------------------------------------------------
# list_redmine_roles
# ---------------------------------------------------------------------------


class TestListRedmineRoles:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_returns_roles(self, mock_redmine):
        role1 = _mock_with_name(3, "Manager")
        role2 = _mock_with_name(4, "Developer")
        role3 = _mock_with_name(5, "Reporter")
        mock_redmine.role.all.return_value = [role1, role2, role3]

        result = await list_redmine_roles()

        assert result == [
            {"id": 3, "name": "Manager"},
            {"id": 4, "name": "Developer"},
            {"id": 5, "name": "Reporter"},
        ]
        mock_redmine.role.all.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_empty_roles(self, mock_redmine):
        mock_redmine.role.all.return_value = []
        result = await list_redmine_roles()
        assert result == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_auth_error(self, mock_redmine):
        from redminelib.exceptions import AuthError

        mock_redmine.role.all.side_effect = AuthError()
        result = await list_redmine_roles()
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.role.all.side_effect = ForbiddenError()
        result = await list_redmine_roles()
        assert len(result) == 1
        assert "error" in result[0]
        assert "Access denied" in result[0]["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_role_missing_attributes(self, mock_redmine):
        """Handle role objects missing some attributes gracefully."""
        role = Mock(spec=["id"])
        role.id = 7
        mock_redmine.role.all.return_value = [role]

        result = await list_redmine_roles()
        assert result == [{"id": 7, "name": ""}]


# ---------------------------------------------------------------------------
# Error hints point to list_redmine_roles (regression test)
# ---------------------------------------------------------------------------


class TestRoleIdErrorHints:
    """Verify that role_id validation errors direct callers to
    list_redmine_roles so AI agents don't hallucinate role IDs."""

    @pytest.mark.asyncio
    async def test_add_member_empty_role_ids_hints_list_roles(self):
        result = await add_project_member(project_id=10, role_ids=[], user_id=5)
        assert "list_redmine_roles" in result["error"]

    @pytest.mark.asyncio
    async def test_add_member_invalid_role_ids_hints_list_roles(self):
        result = await add_project_member(project_id=10, role_ids=["admin"], user_id=5)
        assert "list_redmine_roles" in result["error"]

    @pytest.mark.asyncio
    async def test_update_member_empty_role_ids_hints_list_roles(self):
        result = await update_project_member(membership_id=42, role_ids=[])
        assert "list_redmine_roles" in result["error"]

    @pytest.mark.asyncio
    async def test_update_member_invalid_role_ids_hints_list_roles(self):
        result = await update_project_member(membership_id=42, role_ids=["admin"])
        assert "list_redmine_roles" in result["error"]
