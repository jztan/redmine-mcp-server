"""Unit tests for wiki management tools: list_wiki_pages and rename_wiki_page."""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page  # noqa: E402


def _make_wiki_page(
    title: str = "Page",
    version: int = 1,
    parent_title: str = None,
    text: str = "Body",
) -> Mock:
    page = Mock()
    page.title = title
    page.text = text
    page.version = version
    page.created_on = "2026-04-20T10:00:00Z"
    page.updated_on = "2026-04-20T11:00:00Z"
    if parent_title is not None:
        parent = Mock()
        parent.title = parent_title
        page.parent = parent
    else:
        page.parent = None
    return page


# ---------------------------------------------------------------------------
# list_wiki_pages
# ---------------------------------------------------------------------------


class TestManageRedmineWikiPageList:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_returns_list_of_pages(self, mock_redmine):
        mock_redmine.wiki_page.filter.return_value = [
            _make_wiki_page("Home", version=3),
            _make_wiki_page("Setup", version=1, parent_title="Home"),
        ]

        result = await manage_redmine_wiki_page(action="list", project_id="my-project")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["title"] == "Home"
        assert result[0]["version"] == 3
        assert "parent_title" not in result[0]
        assert result[1]["title"] == "Setup"
        assert result[1]["parent_title"] == "Home"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_empty_project(self, mock_redmine):
        mock_redmine.wiki_page.filter.return_value = []

        result = await manage_redmine_wiki_page(action="list", project_id="empty")

        assert result == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_returns_error_dict_on_exception(self, mock_redmine):
        mock_redmine.wiki_page.filter.side_effect = Exception("boom")

        result = await manage_redmine_wiki_page(action="list", project_id="x")

        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# rename_wiki_page
# ---------------------------------------------------------------------------


class TestManageRedmineWikiPageRename:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_rename_success(self, mock_redmine):
        existing = _make_wiki_page("Old", text="Body")
        renamed = _make_wiki_page("New", text="Body")
        mock_redmine.wiki_page.get.side_effect = [existing, renamed]

        result = await manage_redmine_wiki_page(
            action="rename", project_id="proj", wiki_page_title="Old", new_title="New"
        )

        assert "error" not in result
        assert result["title"] == "New"
        # Verify update called with title + redirect + existing text
        mock_redmine.wiki_page.update.assert_called_once_with(
            "Old",
            project_id="proj",
            title="New",
            text="Body",
            redirect_existing_links="1",
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_rename_without_redirect(self, mock_redmine):
        existing = _make_wiki_page("Old", text="Body")
        renamed = _make_wiki_page("New", text="Body")
        mock_redmine.wiki_page.get.side_effect = [existing, renamed]

        await manage_redmine_wiki_page(
            action="rename",
            project_id="proj",
            wiki_page_title="Old",
            new_title="New",
            redirect_existing_links=False,
        )

        call_kwargs = mock_redmine.wiki_page.update.call_args.kwargs
        assert "redirect_existing_links" not in call_kwargs

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_silent_permission_failure_detected(self, mock_redmine):
        """If the rename silently fails (permission missing), Redmine will
        return 404 when fetching by new_title."""
        existing = _make_wiki_page("Old", text="Body")
        mock_redmine.wiki_page.get.side_effect = [
            existing,
            Exception("404"),
        ]

        result = await manage_redmine_wiki_page(
            action="rename", project_id="proj", wiki_page_title="Old", new_title="New"
        )

        assert "error" in result
        assert "rename_wiki_pages" in result["error"]

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"}):
            result = await manage_redmine_wiki_page(
                action="rename", project_id="p", wiki_page_title="A", new_title="B"
            )

        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_empty_old_title(self):
        result = await manage_redmine_wiki_page(
            action="rename", project_id="p", wiki_page_title="", new_title="B"
        )

        assert "error" in result
        assert "wiki_page_title" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_empty_new_title(self):
        result = await manage_redmine_wiki_page(
            action="rename", project_id="p", wiki_page_title="A", new_title=""
        )

        assert "error" in result
        assert "new_title" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_unchanged_title(self):
        result = await manage_redmine_wiki_page(
            action="rename", project_id="p", wiki_page_title="A", new_title="A"
        )

        assert "error" in result
        assert "differ" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_handles_get_error_gracefully(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.wiki_page.get.side_effect = ResourceNotFoundError()

        result = await manage_redmine_wiki_page(
            action="rename", project_id="p", wiki_page_title="Missing", new_title="New"
        )

        assert "error" in result
