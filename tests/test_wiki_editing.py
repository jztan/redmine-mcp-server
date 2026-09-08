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


class TestManageRedmineWikiPageCreate:
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
    @patch("redmine_mcp_server._client.redmine", None)
    async def test_create_wiki_page_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="# New Page\n\nContent here.",
        )

        assert "error" in result
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_wiki_page_success(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test successful wiki page creation."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.return_value = mock_wiki_page

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="# New Page\n\nContent here.",
        )

        assert result["title"] == "New Page"
        assert "# New Page" in result["text"]
        assert result["version"] == 1
        assert result["author"]["id"] == 123
        mock_redmine.wiki_page.create.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_wiki_page_with_comments(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test wiki page creation with comments."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.return_value = mock_wiki_page

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="# New Page\n\nContent here.",
            comments="Initial creation",
        )

        assert "error" not in result
        assert result["title"] == "New Page"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_wiki_page_under_parent(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """parent_title files the new page under an existing page (#270)."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.return_value = mock_wiki_page

        await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="Content",
            parent_title="Handbook",
        )

        kwargs = mock_redmine.wiki_page.create.call_args.kwargs
        assert kwargs["parent_title"] == "Handbook"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_wiki_page_omits_parent_title_when_not_given(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """No parent_title argument means the key is never sent."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.return_value = mock_wiki_page

        await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="Content",
        )

        kwargs = mock_redmine.wiki_page.create.call_args.kwargs
        assert "parent_title" not in kwargs

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_wiki_page_forbidden(self, mock_cleanup, mock_redmine):
        """Test handling of permission denied error."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = ForbiddenError()

        result = await manage_redmine_wiki_page(
            action="create",
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
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_wiki_page_validation_error(self, mock_cleanup, mock_redmine):
        """Test handling of validation error."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = ValidationError(
            "Title can't be blank"
        )

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="",
            text="Content",
        )

        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_with_unknown_parent_explains_itself(
        self, mock_cleanup, mock_redmine
    ):
        """A bad parent_title yields a 422 carrying no reason at all.

        Redmine 6.1 and 7.0 both answer {"errors": []}, which reaches us
        as ValidationError(""). Left alone the tool would report a blank
        error, so name the likely cause. See #270.
        """
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = ValidationError("")

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="Content",
            parent_title="NoSuchPage",
        )

        assert "NoSuchPage" in result["error"]
        assert "parent_title" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_blank_validation_error_unchanged_without_parent_title(
        self, mock_cleanup, mock_redmine
    ):
        """The parent hint is only offered when a parent was requested."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = ValidationError("")

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="Content",
        )

        assert "error" in result
        assert "parent_title" not in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_create_wiki_page_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exception."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.create.side_effect = Exception("Unexpected error")

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="my-project",
            wiki_page_title="New Page",
            text="Content",
        )

        assert "error" in result


class TestManageRedmineWikiPageUpdate:
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
    @patch("redmine_mcp_server._client.redmine", None)
    async def test_update_wiki_page_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        result = await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Updated content",
        )

        assert "error" in result
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_success(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test successful wiki page update."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.update.return_value = True
        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="# Updated Content\n\nNew content here.",
        )

        assert result["title"] == "Existing Page"
        assert result["version"] == 2
        mock_redmine.wiki_page.update.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_with_comments(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test wiki page update with comments."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.update.return_value = True
        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Updated content",
            comments="Fixed typos",
        )

        assert "error" not in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_reparents(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """parent_title moves an existing page under another page (#270)."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Content",
            parent_title="Handbook",
        )

        kwargs = mock_redmine.wiki_page.update.call_args.kwargs
        assert kwargs["parent_title"] == "Handbook"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_clears_parent_with_empty_string(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """An empty parent_title moves the page back to the wiki root."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Content",
            parent_title="",
        )

        kwargs = mock_redmine.wiki_page.update.call_args.kwargs
        assert kwargs["parent_title"] == ""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_leaves_parent_untouched(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """A text-only update must not orphan a page that has a parent.

        Redmine preserves the parent when the key is absent, so the key
        must not be sent at all rather than sent as None.
        """
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Content",
        )

        kwargs = mock_redmine.wiki_page.update.call_args.kwargs
        assert "parent_title" not in kwargs

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_not_found(self, mock_cleanup, mock_redmine):
        """Test handling of non-existent wiki page."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.update.side_effect = ResourceNotFoundError()

        result = await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="NonExistent",
            text="Content",
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_forbidden(self, mock_cleanup, mock_redmine):
        """Test handling of permission denied error."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.update.side_effect = ForbiddenError()

        result = await manage_redmine_wiki_page(
            action="update",
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
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_update_wiki_page_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exception."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.update.side_effect = Exception("Unexpected error")

        result = await manage_redmine_wiki_page(
            action="update",
            project_id="my-project",
            wiki_page_title="Existing Page",
            text="Content",
        )

        assert "error" in result


class TestManageRedmineWikiPageDelete:
    """Tests for delete_redmine_wiki_page MCP tool."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine", None)
    async def test_delete_wiki_page_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        result = await manage_redmine_wiki_page(
            action="delete",
            project_id="my-project",
            wiki_page_title="Page To Delete",
        )

        assert "error" in result
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_delete_wiki_page_success(self, mock_cleanup, mock_redmine):
        """Test successful wiki page deletion."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.delete.return_value = True

        result = await manage_redmine_wiki_page(
            action="delete",
            project_id="my-project",
            wiki_page_title="Page To Delete",
        )

        assert result["success"] is True
        assert result["title"] == "Page To Delete"
        mock_redmine.wiki_page.delete.assert_called_once()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_delete_wiki_page_not_found(self, mock_cleanup, mock_redmine):
        """Test handling of non-existent wiki page."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.delete.side_effect = ResourceNotFoundError()

        result = await manage_redmine_wiki_page(
            action="delete",
            project_id="my-project",
            wiki_page_title="NonExistent",
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_delete_wiki_page_forbidden(self, mock_cleanup, mock_redmine):
        """Test handling of permission denied error."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.delete.side_effect = ForbiddenError()

        result = await manage_redmine_wiki_page(
            action="delete",
            project_id="my-project",
            wiki_page_title="Protected Page",
        )

        assert "error" in result
        assert (
            "denied" in result["error"].lower()
            or "permission" in result["error"].lower()
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_delete_wiki_page_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exception."""
        from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page

        mock_redmine.wiki_page.delete.side_effect = Exception("Unexpected error")

        result = await manage_redmine_wiki_page(
            action="delete",
            project_id="my-project",
            wiki_page_title="Some Page",
        )

        assert "error" in result
