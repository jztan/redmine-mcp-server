"""
Tests for read-only mode (REDMINE_MCP_READ_ONLY env var).

Phase 3 of v1.0.0 TDD plan: Validates that write tools are blocked
when read-only mode is enabled, and read tools still work.
"""

import os
import pytest
from unittest.mock import Mock, patch

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _is_read_only_mode,
    create_redmine_issue,
    update_redmine_issue,
    create_redmine_wiki_page,
    update_redmine_wiki_page,
    delete_redmine_wiki_page,
    get_redmine_issue,
    list_redmine_projects,
    list_redmine_issues,
    cleanup_attachment_files,
)


class TestIsReadOnlyMode:
    """Tests for _is_read_only_mode function."""

    def test_true_when_env_true(self):
        with patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"}):
            assert _is_read_only_mode() is True

    def test_true_when_env_1(self):
        with patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "1"}):
            assert _is_read_only_mode() is True

    def test_false_when_env_false(self):
        with patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "false"}):
            assert _is_read_only_mode() is False

    def test_false_when_env_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _is_read_only_mode() is False


class TestWriteToolsBlockedInReadOnly:
    """Tests that write tools return error in read-only mode."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_issue_blocked(self, mock_redmine, mock_cleanup):
        result = await create_redmine_issue(project_id=1, subject="X")
        assert "read-only" in result["error"].lower()
        mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_issue_blocked(self, mock_redmine, mock_cleanup):
        result = await update_redmine_issue(issue_id=1, fields={"subject": "X"})
        assert "read-only" in result["error"].lower()
        mock_redmine.issue.update.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_wiki_blocked(self, mock_redmine, mock_cleanup):
        result = await create_redmine_wiki_page("proj", "Page", "text")
        assert "read-only" in result["error"].lower()
        mock_redmine.wiki_page.create.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_wiki_blocked(self, mock_redmine, mock_cleanup):
        result = await update_redmine_wiki_page("proj", "Page", "text")
        assert "read-only" in result["error"].lower()
        mock_redmine.wiki_page.update.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_wiki_blocked(self, mock_redmine, mock_cleanup):
        result = await delete_redmine_wiki_page("proj", "Page")
        assert "read-only" in result["error"].lower()
        mock_redmine.wiki_page.delete.assert_not_called()


class TestReadToolsWorkInReadOnly:
    """Tests that read tools are NOT blocked in read-only mode."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_issue_works(self, mock_redmine, mock_cleanup):
        mock_issue = Mock()
        mock_issue.id = 123
        mock_issue.subject = "Test"
        mock_issue.description = "Desc"
        mock_issue.project = Mock(id=1, name="Project")
        mock_issue.status = Mock(id=1, name="New")
        mock_issue.priority = Mock(id=2, name="Normal")
        mock_issue.author = Mock(id=1, name="Author")
        mock_issue.assigned_to = None
        mock_issue.created_on = None
        mock_issue.updated_on = None
        mock_issue.journals = []
        mock_issue.attachments = []
        mock_redmine.issue.get.return_value = mock_issue

        result = await get_redmine_issue(123)
        assert "error" not in result
        assert result["id"] == 123

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_projects_works(self, mock_redmine, mock_cleanup):
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test"
        mock_project.identifier = "test"
        mock_project.description = ""
        mock_project.status = 1
        mock_project.created_on = None
        mock_project.updated_on = None
        mock_redmine.project.all.return_value = [mock_project]

        result = await list_redmine_projects()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_issues_works(self, mock_redmine, mock_cleanup):
        mock_redmine.issue.filter.return_value = []
        result = await list_redmine_issues()
        assert isinstance(result, list)


class TestWriteToolsWorkWhenNotReadOnly:
    """Tests that writes proceed when read-only mode is off."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "false"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_issue_proceeds(self, mock_redmine, mock_cleanup):
        mock_issue = Mock()
        mock_issue.id = 1
        mock_issue.subject = "X"
        mock_issue.description = ""
        mock_issue.project = Mock(id=1, name="P")
        mock_issue.status = Mock(id=1, name="New")
        mock_issue.priority = Mock(id=2, name="Normal")
        mock_issue.author = Mock(id=1, name="A")
        mock_issue.assigned_to = None
        mock_issue.created_on = None
        mock_issue.updated_on = None
        mock_redmine.issue.create.return_value = mock_issue

        await create_redmine_issue(project_id=1, subject="X")
        mock_redmine.issue.create.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_issue_proceeds_unset(self, mock_redmine, mock_cleanup):
        # Ensure env var is absent
        env = os.environ.copy()
        env.pop("REDMINE_MCP_READ_ONLY", None)
        with patch.dict(os.environ, env, clear=True):
            mock_redmine.issue.update.return_value = True
            mock_redmine.issue.get.return_value = Mock(
                id=1,
                subject="X",
                description="",
                project=Mock(id=1, name="P"),
                status=Mock(id=1, name="New"),
                priority=Mock(id=2, name="Normal"),
                author=Mock(id=1, name="A"),
                assigned_to=None,
                created_on=None,
                updated_on=None,
            )

            await update_redmine_issue(issue_id=1, fields={"subject": "X"})
            mock_redmine.issue.update.assert_called_once()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_cleanup_not_blocked(self, mock_cleanup):
        # cleanup_attachment_files is a local operation, not guarded
        result = await cleanup_attachment_files()
        # Should not return a read-only error
        assert (
            "error" not in result or "read-only" not in result.get("error", "").lower()
        )
