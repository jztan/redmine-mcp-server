"""
TDD tests for wiki page editing tools: create, update, delete.
Tests written first - implementation follows.
"""

import pytest
from unittest.mock import Mock, patch
from redminelib.exceptions import (
    ResourceNotFoundError,
    ForbiddenError,
    ValidationError,
)


class TestCreateRedmineWikiPage:
    """Tests for create_redmine_wiki_page MCP tool."""

    @pytest.fixture
    def mock_wiki_page(self):
        """Create a mock wiki page object for creation response."""
        mock_page = Mock()
        mock_page.title = "New Page"
        mock_page.text = "# New Page\n\nContent here."
        mock_page.version = 1
        mock_page.created_on = "2025-01-15T10:00:00Z"
        mock_page.updated_on = "2025-01-15T10:00:00Z"
        mock_author = Mock()
        mock_author.id = 123
        mock_author.name = "John Doe"
        mock_page.author = mock_author
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "My Project"
        mock_page.project = mock_project
        mock_page.attachments = []
        return mock_page

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_create_wiki_page_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.redmine_handler import create_redmine_wiki_page

        result = await create_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="New Page",
            text="# New Page\n\nContent here.",
        )

        assert "error" in result
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_wiki_page_success(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test successful wiki page creation."""
        from redmine_mcp_server.redmine_handler import create_redmine_wiki_page

        mock_redmine.wiki_page.create.return_value = mock_wiki_page

        result = await create_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="New Page",
            text="# New Page\n\nContent here.",
        )

        assert result["title"] == "New Page"
        assert result["text"] == "# New Page\n\nContent here."
        assert result["version"] == 1
        assert result["author"]["id"] == 123
        mock_redmine.wiki_page.create.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_wiki_page_with_comments(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test wiki page creation with comments."""
        from redmine_mcp_server.redmine_handler import create_redmine_wiki_page

        mock_redmine.wiki_page.create.return_value = mock_wiki_page

        result = await create_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="New Page",
            text="# New Page\n\nContent here.",
            comments="Initial creation",
        )

        assert "error" not in result
        assert result["title"] == "New Page"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_wiki_page_forbidden(self, mock_cleanup, mock_redmine):
        """Test handling of permission denied error."""
        from redmine_mcp_server.redmine_handler import create_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = ForbiddenError()

        result = await create_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="New Page",
            text="Content",
        )

        assert "error" in result
        assert (
            "denied" in result["error"].lower()
            or "permission" in result["error"].lower()
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_wiki_page_validation_error(self, mock_cleanup, mock_redmine):
        """Test handling of validation error."""
        from redmine_mcp_server.redmine_handler import create_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = ValidationError(
            "Title can't be blank"
        )

        result = await create_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="",
            text="Content",
        )

        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_create_wiki_page_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exception."""
        from redmine_mcp_server.redmine_handler import create_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = Exception("Unexpected error")

        result = await create_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="New Page",
            text="Content",
        )

        assert "error" in result


class TestUpdateRedmineWikiPage:
    """Tests for update_redmine_wiki_page MCP tool."""

    @pytest.fixture
    def mock_wiki_page(self):
        """Create a mock wiki page object for update response."""
        mock_page = Mock()
        mock_page.title = "Existing Page"
        mock_page.text = "# Updated Content\n\nNew content here."
        mock_page.version = 2
        mock_page.created_on = "2025-01-10T10:00:00Z"
        mock_page.updated_on = "2025-01-15T14:30:00Z"
        mock_author = Mock()
        mock_author.id = 123
        mock_author.name = "John Doe"
        mock_page.author = mock_author
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "My Project"
        mock_page.project = mock_project
        mock_page.attachments = []
        return mock_page

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_update_wiki_page_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.redmine_handler import update_redmine_wiki_page

        result = await update_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Updated content",
        )

        assert "error" in result
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_wiki_page_success(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test successful wiki page update."""
        from redmine_mcp_server.redmine_handler import update_redmine_wiki_page

        mock_redmine.wiki_page.update.return_value = True
        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await update_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="# Updated Content\n\nNew content here.",
        )

        assert result["title"] == "Existing Page"
        assert result["version"] == 2
        mock_redmine.wiki_page.update.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_wiki_page_with_comments(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test wiki page update with comments."""
        from redmine_mcp_server.redmine_handler import update_redmine_wiki_page

        mock_redmine.wiki_page.update.return_value = True
        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await update_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Updated content",
            comments="Fixed typos",
        )

        assert "error" not in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_wiki_page_not_found(self, mock_cleanup, mock_redmine):
        """Test handling of non-existent wiki page."""
        from redmine_mcp_server.redmine_handler import update_redmine_wiki_page

        mock_redmine.wiki_page.update.side_effect = ResourceNotFoundError()

        result = await update_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="NonExistent",
            text="Content",
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_wiki_page_forbidden(self, mock_cleanup, mock_redmine):
        """Test handling of permission denied error."""
        from redmine_mcp_server.redmine_handler import update_redmine_wiki_page

        mock_redmine.wiki_page.update.side_effect = ForbiddenError()

        result = await update_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Content",
        )

        assert "error" in result
        assert (
            "denied" in result["error"].lower()
            or "permission" in result["error"].lower()
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_update_wiki_page_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exception."""
        from redmine_mcp_server.redmine_handler import update_redmine_wiki_page

        mock_redmine.wiki_page.update.side_effect = Exception("Unexpected error")

        result = await update_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Content",
        )

        assert "error" in result


class TestDeleteRedmineWikiPage:
    """Tests for delete_redmine_wiki_page MCP tool."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_delete_wiki_page_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.redmine_handler import delete_redmine_wiki_page

        result = await delete_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Page To Delete",
        )

        assert "error" in result
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_delete_wiki_page_success(self, mock_cleanup, mock_redmine):
        """Test successful wiki page deletion."""
        from redmine_mcp_server.redmine_handler import delete_redmine_wiki_page

        mock_redmine.wiki_page.delete.return_value = True

        result = await delete_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Page To Delete",
        )

        assert result["success"] is True
        assert result["title"] == "Page To Delete"
        mock_redmine.wiki_page.delete.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_delete_wiki_page_not_found(self, mock_cleanup, mock_redmine):
        """Test handling of non-existent wiki page."""
        from redmine_mcp_server.redmine_handler import delete_redmine_wiki_page

        mock_redmine.wiki_page.delete.side_effect = ResourceNotFoundError()

        result = await delete_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="NonExistent",
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_delete_wiki_page_forbidden(self, mock_cleanup, mock_redmine):
        """Test handling of permission denied error."""
        from redmine_mcp_server.redmine_handler import delete_redmine_wiki_page

        mock_redmine.wiki_page.delete.side_effect = ForbiddenError()

        result = await delete_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Protected Page",
        )

        assert "error" in result
        assert (
            "denied" in result["error"].lower()
            or "permission" in result["error"].lower()
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_delete_wiki_page_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exception."""
        from redmine_mcp_server.redmine_handler import delete_redmine_wiki_page

        mock_redmine.wiki_page.delete.side_effect = Exception("Unexpected error")

        result = await delete_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Some Page",
        )

        assert "error" in result
