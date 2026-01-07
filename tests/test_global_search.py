"""
TDD tests for search_entire_redmine and get_redmine_wiki_page tools.
Following existing patterns from test_redmine_handler.py.
"""

import pytest
from unittest.mock import Mock, patch
from redminelib.exceptions import ResourceNotFoundError


class TestResourceToDict:
    """Tests for _resource_to_dict helper function."""

    def test_issue_resource_conversion(self):
        """Test converting an issue resource to dict."""
        from redmine_mcp_server.redmine_handler import _resource_to_dict

        mock_issue = Mock()
        mock_issue.id = 123
        mock_issue.subject = "Test Issue"
        # Mock's name kwarg is special - set as attribute instead
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Project A"
        mock_issue.project = mock_project
        mock_status = Mock()
        mock_status.name = "Open"
        mock_issue.status = mock_status
        mock_issue.updated_on = "2025-01-15T10:00:00Z"
        mock_issue.description = "Issue description"

        result = _resource_to_dict(mock_issue, "issues")

        assert result["id"] == 123
        assert result["type"] == "issues"
        assert result["title"] == "Test Issue"
        assert result["project"] == "Project A"
        assert result["status"] == "Open"
        assert result["updated_on"] == "2025-01-15T10:00:00Z"

    def test_wiki_page_resource_conversion(self):
        """Test converting a wiki page resource to dict."""
        from redmine_mcp_server.redmine_handler import _resource_to_dict

        # Use spec to control which attributes exist
        mock_wiki = Mock(spec=["id", "title", "project", "updated_on", "text"])
        mock_wiki.id = None  # Wiki pages may not have id
        mock_wiki.title = "Installation Guide"
        # Mock's name kwarg is special - set as attribute instead
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Project A"
        mock_wiki.project = mock_project
        mock_wiki.updated_on = "2025-01-15T10:00:00Z"
        mock_wiki.text = "Wiki content here"
        # Note: status, subject, description not in spec so hasattr returns False

        result = _resource_to_dict(mock_wiki, "wiki_pages")

        assert result["type"] == "wiki_pages"
        assert result["title"] == "Installation Guide"
        assert result["project"] == "Project A"
        assert result.get("status") is None

    def test_missing_attributes_handled_gracefully(self):
        """Test that missing attributes don't cause errors."""
        from redmine_mcp_server.redmine_handler import _resource_to_dict

        mock_resource = Mock(spec=[])  # Empty spec = no attributes
        mock_resource.id = 456

        result = _resource_to_dict(mock_resource, "issues")

        assert result["id"] == 456
        assert result["type"] == "issues"
        assert result.get("title") is None
        assert result.get("project") is None


class TestSearchEntireRedmine:
    """Tests for search_entire_redmine MCP tool."""

    @pytest.fixture
    def mock_search_results(self):
        """Create mock categorized search results from python-redmine."""
        # Mock Issue
        mock_issue = Mock(
            spec=["id", "subject", "project", "status", "updated_on", "description"]
        )
        mock_issue.id = 123
        mock_issue.subject = "Test Issue"
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Project A"
        mock_issue.project = mock_project
        mock_status = Mock()
        mock_status.name = "Open"
        mock_issue.status = mock_status
        mock_issue.updated_on = "2025-01-15T10:00:00Z"
        mock_issue.description = "Issue description"

        # Mock WikiPage
        mock_wiki = Mock(spec=["id", "title", "project", "updated_on", "text"])
        mock_wiki.id = None
        mock_wiki.title = "Installation Guide"
        mock_wiki_project = Mock()
        mock_wiki_project.id = 1
        mock_wiki_project.name = "Project A"
        mock_wiki.project = mock_wiki_project
        mock_wiki.updated_on = "2025-01-15T10:00:00Z"
        mock_wiki.text = "Wiki content here"

        # Categorized results (python-redmine format)
        return {
            "issues": [mock_issue],
            "wiki_pages": [mock_wiki],
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_search_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        result = await search_entire_redmine(query="test")

        assert "error" in result
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_success(
        self, mock_cleanup, mock_redmine, mock_search_results
    ):
        """Test successful search returns properly formatted results."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = mock_search_results

        result = await search_entire_redmine(query="test")

        assert "results" in result
        assert "total_count" in result
        assert "results_by_type" in result
        assert result["total_count"] == 2
        assert result["results_by_type"]["issues"] == 1
        assert result["results_by_type"]["wiki_pages"] == 1
        assert result["query"] == "test"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_empty_results(self, mock_cleanup, mock_redmine):
        """Test search with no results returns empty structure."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        # CRITICAL GOTCHA: redmine.search() returns None for empty results
        mock_redmine.search.return_value = None

        result = await search_entire_redmine(query="nonexistent")

        assert result["results"] == []
        assert result["total_count"] == 0
        assert result["results_by_type"] == {}
        assert result["query"] == "nonexistent"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_with_resource_filter(self, mock_cleanup, mock_redmine):
        """Test search with resource type filtering."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_issue = Mock(
            spec=["id", "subject", "project", "status", "updated_on", "description"]
        )
        mock_issue.id = 1
        mock_issue.subject = "Test"
        mock_project = Mock()
        mock_project.name = "P"
        mock_project.id = 1
        mock_issue.project = mock_project
        mock_status = Mock()
        mock_status.name = "Open"
        mock_issue.status = mock_status
        mock_issue.updated_on = None
        mock_issue.description = None
        mock_redmine.search.return_value = {"issues": [mock_issue]}

        await search_entire_redmine(query="test", resources=["issues"])

        # Verify resources parameter passed to API
        mock_redmine.search.assert_called_once()
        call_kwargs = mock_redmine.search.call_args[1]
        assert call_kwargs.get("resources") == ["issues"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_invalid_resource_types_filtered(
        self, mock_cleanup, mock_redmine
    ):
        """Test that invalid resource types are filtered out (v1.4 scope)."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = {"issues": []}

        # Pass invalid types along with valid ones
        await search_entire_redmine(
            query="test", resources=["issues", "projects", "news", "wiki_pages"]
        )

        # Only valid types should be passed
        call_kwargs = mock_redmine.search.call_args[1]
        assert set(call_kwargs.get("resources", [])) == {"issues", "wiki_pages"}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_default_resources(self, mock_cleanup, mock_redmine):
        """Test that default search includes both issues and wiki_pages."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = {}

        await search_entire_redmine(query="test")

        call_kwargs = mock_redmine.search.call_args[1]
        assert set(call_kwargs.get("resources", [])) == {"issues", "wiki_pages"}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_pagination(self, mock_cleanup, mock_redmine):
        """Test pagination parameters are passed correctly."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = {}

        await search_entire_redmine(query="test", limit=50, offset=25)

        call_kwargs = mock_redmine.search.call_args[1]
        assert call_kwargs.get("limit") == 50
        assert call_kwargs.get("offset") == 25

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_limit_capped(self, mock_cleanup, mock_redmine):
        """Test that limit is capped at 100 (Redmine API max)."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.return_value = {}

        await search_entire_redmine(query="test", limit=500)

        call_kwargs = mock_redmine.search.call_args[1]
        assert call_kwargs.get("limit") == 100  # Capped

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_version_mismatch(self, mock_cleanup, mock_redmine):
        """Test handling of VersionMismatchError (Redmine < 3.3.0)."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine
        from redminelib.exceptions import VersionMismatchError

        mock_redmine.search.side_effect = VersionMismatchError("search")

        result = await search_entire_redmine(query="test")

        assert "error" in result
        assert "3.3.0" in result["error"]  # Must mention correct version

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exceptions."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_redmine.search.side_effect = Exception("Network error")

        result = await search_entire_redmine(query="test")

        assert "error" in result
        assert "Network error" in result["error"] or "failed" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_search_unknown_resources_ignored(self, mock_cleanup, mock_redmine):
        """Test that 'unknown' category from plugins is handled gracefully."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        mock_issue = Mock(
            spec=["id", "subject", "project", "status", "updated_on", "description"]
        )
        mock_issue.id = 1
        mock_issue.subject = "Test"
        mock_project = Mock()
        mock_project.name = "P"
        mock_project.id = 1
        mock_issue.project = mock_project
        mock_status = Mock()
        mock_status.name = "Open"
        mock_issue.status = mock_status
        mock_issue.updated_on = None
        mock_issue.description = None

        mock_redmine.search.return_value = {
            "issues": [mock_issue],
            "unknown": {"custom_plugin_type": [{"id": 1}]},  # Plugin data
        }

        result = await search_entire_redmine(query="test")

        # Should only include known types, ignore unknown
        assert result["total_count"] == 1
        assert "unknown" not in result["results_by_type"]


class TestGetRedmineWikiPage:
    """Tests for get_redmine_wiki_page MCP tool."""

    @pytest.fixture
    def mock_wiki_page(self):
        """Create a mock wiki page object."""
        mock_page = Mock()
        mock_page.title = "Installation Guide"
        mock_page.text = "# Installation\n\nFollow these steps..."
        mock_page.version = 5
        mock_page.created_on = "2025-01-15T10:00:00Z"
        mock_page.updated_on = "2025-01-20T14:30:00Z"
        mock_author = Mock()
        mock_author.id = 123
        mock_author.name = "John Doe"
        mock_page.author = mock_author
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "My Project"
        mock_page.project = mock_project
        mock_page.attachments = []  # Default to empty list for iteration
        return mock_page

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine", None)
    async def test_wiki_page_no_client(self):
        """Test error when Redmine client is not initialized."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        result = await get_redmine_wiki_page(
            project_id="my-project", wiki_page_title="Installation"
        )

        assert "error" in result
        assert result["error"] == "Redmine client not initialized."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_success(self, mock_cleanup, mock_redmine, mock_wiki_page):
        """Test successful wiki page retrieval."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await get_redmine_wiki_page(
            project_id="my-project", wiki_page_title="Installation Guide"
        )

        assert result["title"] == "Installation Guide"
        assert result["text"] == "# Installation\n\nFollow these steps..."
        assert result["version"] == 5
        assert result["author"]["id"] == 123
        assert result["author"]["name"] == "John Doe"
        assert result["project"]["id"] == 1
        assert result["project"]["name"] == "My Project"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_not_found(self, mock_cleanup, mock_redmine):
        """Test handling of non-existent wiki page."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_redmine.wiki_page.get.side_effect = ResourceNotFoundError()

        result = await get_redmine_wiki_page(
            project_id="my-project", wiki_page_title="NonExistent"
        )

        assert "error" in result
        # Error message includes wiki page title and "not found"
        assert "NonExistent" in result["error"]
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_specific_version(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test retrieving specific wiki page version."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_wiki_page.version = 3
        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await get_redmine_wiki_page(
            project_id="my-project", wiki_page_title="Installation", version=3
        )

        # Verify version parameter passed
        mock_redmine.wiki_page.get.assert_called_once_with(
            "Installation", project_id="my-project", version=3
        )
        assert result["version"] == 3

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_with_attachments(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test wiki page with attachments."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_attachment = Mock()
        mock_attachment.id = 456
        mock_attachment.filename = "diagram.png"
        mock_attachment.filesize = 102400
        mock_attachment.content_type = "image/png"
        mock_attachment.description = "Architecture diagram"
        mock_attachment.created_on = "2025-01-15T10:00:00Z"

        mock_wiki_page.attachments = [mock_attachment]
        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await get_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Installation",
            include_attachments=True,
        )

        assert "attachments" in result
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["id"] == 456
        assert result["attachments"][0]["filename"] == "diagram.png"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_without_attachments(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test excluding attachments from response."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_wiki_page.attachments = [Mock(id=1)]
        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        result = await get_redmine_wiki_page(
            project_id="my-project",
            wiki_page_title="Installation",
            include_attachments=False,
        )

        assert "attachments" not in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_missing_attributes(self, mock_cleanup, mock_redmine):
        """Test handling of wiki page with missing optional attributes."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_page = Mock(spec=["title", "text", "version"])
        mock_page.title = "Simple Page"
        mock_page.text = "Content"
        mock_page.version = 1

        mock_redmine.wiki_page.get.return_value = mock_page

        result = await get_redmine_wiki_page(
            project_id=1, wiki_page_title="Simple Page"
        )

        assert result["title"] == "Simple Page"
        assert result["text"] == "Content"
        assert result.get("created_on") is None
        assert result.get("author") is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_integer_project_id(
        self, mock_cleanup, mock_redmine, mock_wiki_page
    ):
        """Test wiki page retrieval with integer project ID."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_redmine.wiki_page.get.return_value = mock_wiki_page

        await get_redmine_wiki_page(project_id=123, wiki_page_title="Test")

        mock_redmine.wiki_page.get.assert_called_once_with("Test", project_id=123)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_wiki_page_general_exception(self, mock_cleanup, mock_redmine):
        """Test handling of general exceptions."""
        from redmine_mcp_server.redmine_handler import get_redmine_wiki_page

        mock_redmine.wiki_page.get.side_effect = Exception("Network error")

        result = await get_redmine_wiki_page(
            project_id="my-project", wiki_page_title="Test"
        )

        assert "error" in result
        assert "Failed" in result["error"] or "Network error" in result["error"]


@pytest.mark.integration
class TestGlobalSearchIntegration:
    """Integration tests requiring live Redmine server."""

    @pytest.mark.asyncio
    async def test_search_entire_redmine_real_server(self):
        """Test search against real Redmine instance."""
        from redmine_mcp_server.redmine_handler import search_entire_redmine

        result = await search_entire_redmine(query="test")

        # Should return valid structure even with no results
        assert "results" in result or "error" in result
        if "results" in result:
            assert "total_count" in result
            assert isinstance(result["results"], list)

    @pytest.mark.asyncio
    async def test_wiki_page_real_server(self):
        """Test wiki page retrieval by first discovering a wiki page via search."""
        from redmine_mcp_server.redmine_handler import (
            search_entire_redmine,
            get_redmine_wiki_page,
            redmine,
        )

        # First, search for any wiki page using common terms
        search_result = await search_entire_redmine(
            query="wiki", resources=["wiki_pages"], limit=1
        )
        # Fallback to broader search if no results
        if search_result.get("total_count", 0) == 0:
            search_result = await search_entire_redmine(
                query="test", resources=["wiki_pages"], limit=1
            )

        if "error" in search_result:
            pytest.skip(f"Search not available: {search_result['error']}")

        if search_result.get("total_count", 0) == 0:
            pytest.skip("No wiki pages found on Redmine server")

        # Get the first wiki page from search results
        wiki_info = search_result["results"][0]
        wiki_title = wiki_info.get("title")

        if not wiki_title:
            pytest.skip("Search result missing title")

        # Clean up title (search results prefix with "Wiki: ")
        if wiki_title.startswith("Wiki: "):
            wiki_title = wiki_title[6:]

        # Get project identifier - search API doesn't provide it for wiki pages
        # so we get the first available project
        projects = list(redmine.project.all())
        if not projects:
            pytest.skip("No projects available")
        project_id = projects[0].identifier

        # Retrieve the wiki page
        result = await get_redmine_wiki_page(
            project_id=project_id, wiki_page_title=wiki_title
        )

        # Should return valid structure with content
        assert "title" in result or "error" in result
        if "title" in result:
            assert result["title"] == wiki_title
            assert "text" in result
