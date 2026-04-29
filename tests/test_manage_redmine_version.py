"""
Tests for manage_redmine_version MCP tool.
TDD: tests written before implementation.
"""

import os
import sys
import pytest
from datetime import date, datetime
from unittest.mock import Mock, patch
from redminelib.exceptions import ResourceNotFoundError, ForbiddenError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def create_mock_version(
    version_id=1,
    name="v1.0",
    description="Test version",
    status="open",
    due_date=date(2026, 6, 1),
    sharing="none",
    wiki_page_title="",
    project_id=1,
    project_name="Test Project",
):
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
    mock_version.updated_on = datetime(2026, 4, 1, 14, 30, 0)
    return mock_version


# ── Shared / cross-action ─────────────────────────────────────────────


class TestManageRedmineVersionShared:

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="publish")

        assert "error" in result
        assert "publish" in result["error"]
        assert "create, update, delete" in result["error"]

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_read_only_blocks_create(self, mock_redmine, mock_cleanup):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(
            action="create", project_id=1, name="v1.0"
        )

        assert "error" in result
        assert "read-only" in result["error"].lower()
        mock_redmine.version.create.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_read_only_blocks_update(self, mock_redmine, mock_cleanup):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(
            action="update", version_id=1, name="v2.0"
        )

        assert "error" in result
        assert "read-only" in result["error"].lower()
        mock_redmine.version.update.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_read_only_blocks_delete(self, mock_redmine, mock_cleanup):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="delete", version_id=1)

        assert "error" in result
        assert "read-only" in result["error"].lower()
        mock_redmine.version.delete.assert_not_called()


# ── create ────────────────────────────────────────────────────────────


class TestManageRedmineVersionCreate:

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_success_all_fields(self, mock_cleanup, mock_redmine):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_version = create_mock_version(
            version_id=5,
            name="v2.0",
            status="open",
            sharing="none",
            wiki_page_title="Release_v2",
        )
        mock_redmine.version.create.return_value = mock_version

        result = await manage_redmine_version(
            action="create",
            project_id=1,
            name="v2.0",
            description="Second release",
            status="open",
            due_date="2026-06-01",
            sharing="none",
            wiki_page_title="Release_v2",
        )

        assert result["id"] == 5
        assert result["name"] == "v2.0"
        assert result["status"] == "open"
        mock_redmine.version.create.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_defaults_applied(self, mock_cleanup, mock_redmine):
        """Omitting status and sharing must apply status='open', sharing='none'."""
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_version = create_mock_version(status="open", sharing="none")
        mock_redmine.version.create.return_value = mock_version

        await manage_redmine_version(
            action="create",
            project_id=1,
            name="v1.0",
        )

        call_kwargs = mock_redmine.version.create.call_args[1]
        assert call_kwargs["status"] == "open"
        assert call_kwargs["sharing"] == "none"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_success_required_fields_only(
        self, mock_cleanup, mock_redmine
    ):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_version = create_mock_version(version_id=3, name="v1.0")
        mock_redmine.version.create.return_value = mock_version

        result = await manage_redmine_version(
            action="create",
            project_id=1,
            name="v1.0",
        )

        assert "error" not in result
        assert result["id"] == 3
        assert result["name"] == "v1.0"
        mock_redmine.version.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_missing_project_id(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="create", name="v1.0")

        assert "error" in result
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    async def test_create_missing_name(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="create", project_id=1)

        assert "error" in result
        assert "name" in result["error"]

    @pytest.mark.asyncio
    async def test_create_invalid_status(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(
            action="create", project_id=1, name="v1.0", status="done"
        )

        assert "error" in result
        assert "done" in result["error"]
        assert "open, locked, closed" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_api_error(self, mock_cleanup, mock_redmine):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_redmine.version.create.side_effect = Exception("Connection refused")

        result = await manage_redmine_version(
            action="create", project_id=1, name="v1.0"
        )

        assert "error" in result


# ── update ────────────────────────────────────────────────────────────


class TestManageRedmineVersionUpdate:

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_single_field(self, mock_cleanup, mock_redmine):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_version = create_mock_version(version_id=1, status="closed")
        mock_redmine.version.get.return_value = mock_version

        result = await manage_redmine_version(
            action="update", version_id=1, status="closed"
        )

        assert result["status"] == "closed"
        mock_redmine.version.update.assert_called_once_with(1, status="closed")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_multiple_fields(self, mock_cleanup, mock_redmine):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_version = create_mock_version(version_id=1, name="v1.1", status="locked")
        mock_redmine.version.get.return_value = mock_version

        result = await manage_redmine_version(
            action="update", version_id=1, name="v1.1", status="locked"
        )

        assert result["name"] == "v1.1"
        assert result["status"] == "locked"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_meta_params_excluded(self, mock_cleanup, mock_redmine):
        """action, project_id, version_id must NOT appear in version.update() kwargs."""
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_version = create_mock_version(version_id=1, name="v2.0")
        mock_redmine.version.get.return_value = mock_version

        await manage_redmine_version(
            action="update", version_id=1, project_id=5, name="v2.0"
        )

        call_kwargs = mock_redmine.version.update.call_args[1]
        assert "action" not in call_kwargs
        assert "project_id" not in call_kwargs
        assert "version_id" not in call_kwargs
        assert call_kwargs.get("name") == "v2.0"

    @pytest.mark.asyncio
    async def test_update_missing_version_id(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="update", name="v2.0")

        assert "error" in result
        assert "version_id" in result["error"]

    @pytest.mark.asyncio
    async def test_update_no_fields(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="update", version_id=1)

        assert "error" in result
        assert "field" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_invalid_status(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(
            action="update", version_id=1, status="done"
        )

        assert "error" in result
        assert "done" in result["error"]
        assert "open, locked, closed" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_api_error(self, mock_cleanup, mock_redmine):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_redmine.version.update.side_effect = ResourceNotFoundError()

        result = await manage_redmine_version(
            action="update", version_id=999, name="v2.0"
        )

        assert "error" in result


# ── delete ────────────────────────────────────────────────────────────


class TestManageRedmineVersionDelete:

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_delete_success(self, mock_cleanup, mock_redmine):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="delete", version_id=1)

        assert result["success"] is True
        assert result["version_id"] == 1
        assert "deleted" in result["message"].lower()
        mock_redmine.version.delete.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_delete_missing_version_id(self):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        result = await manage_redmine_version(action="delete")

        assert "error" in result
        assert "version_id" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_delete_api_error(self, mock_cleanup, mock_redmine):
        from redmine_mcp_server.redmine_handler import manage_redmine_version

        mock_redmine.version.delete.side_effect = ForbiddenError()

        result = await manage_redmine_version(action="delete", version_id=1)

        assert "error" in result
