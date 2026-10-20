"""`expected_version` on wiki writes: Redmine's own optimistic lock (#324)."""

import base64
import os
import sys
from unittest.mock import Mock, patch

import pytest
from redminelib.exceptions import ConflictError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page  # noqa: E402

B64 = base64.b64encode(b"bytes").decode("ascii")


def _page(title="Page", text="body", version=3):
    page = Mock()
    page.title = title
    page.text = text
    page.version = version
    page.created_on = "2026-09-20T10:00:00Z"
    page.updated_on = "2026-09-20T10:00:00Z"
    page.attachments = []
    return page


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_text_update_sends_the_expected_version(mock_redmine):
    mock_redmine.wiki_page.get.return_value = _page(version=6)

    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        text="new body",
        expected_version=5,
    )

    assert "error" not in result
    _, kwargs = mock_redmine.wiki_page.update.call_args
    assert kwargs["text"] == "new body"
    assert kwargs["version"] == 5


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_text_update_without_it_sends_no_version(mock_redmine):
    mock_redmine.wiki_page.get.return_value = _page()

    await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        text="new body",
    )

    _, kwargs = mock_redmine.wiki_page.update.call_args
    assert "version" not in kwargs


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_stale_expected_version_is_an_edit_conflict(mock_redmine):
    mock_redmine.wiki_page.update.side_effect = ConflictError()

    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        text="new body",
        expected_version=1,
    )

    assert "Edit conflict" in result["error"]


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_attachment_only_update_keeps_the_version_it_read(mock_redmine):
    # Redmine checks the version only when the text changes, and this path
    # echoes text it has just read, so the version read with it is the one
    # that turns an edit landing in between into a 409.
    mock_redmine.upload.return_value = {"token": "t"}
    mock_redmine.wiki_page.get.return_value = _page(text="existing", version=7)

    await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        uploads=[{"filename": "a.txt", "content_base64": B64}],
        expected_version=5,
    )

    _, kwargs = mock_redmine.wiki_page.update.call_args
    assert kwargs["text"] == "existing"
    assert kwargs["version"] == 7


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_rename_sends_the_version_it_read(mock_redmine):
    mock_redmine.wiki_page.get.return_value = _page(text="existing", version=4)

    await manage_redmine_wiki_page(
        action="rename",
        project_id="proj",
        wiki_page_title="Page",
        new_title="Renamed",
    )

    _, kwargs = mock_redmine.wiki_page.update.call_args
    assert kwargs["text"] == "existing"
    assert kwargs["version"] == 4


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_rename_conflict_is_an_edit_conflict(mock_redmine):
    mock_redmine.wiki_page.get.return_value = _page()
    mock_redmine.wiki_page.update.side_effect = ConflictError()

    result = await manage_redmine_wiki_page(
        action="rename",
        project_id="proj",
        wiki_page_title="Page",
        new_title="Renamed",
    )

    assert "Edit conflict" in result["error"]
