"""Unit tests for file uploads on wiki page create/update."""

import base64
import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page  # noqa: E402

B64 = base64.b64encode(b"diagram-bytes").decode("ascii")


def _make_wiki_page(title="Page", text="Body", version=1):
    page = Mock()
    page.title = title
    page.text = text
    page.version = version
    page.created_on = "2026-08-08T10:00:00Z"
    page.updated_on = "2026-08-08T10:00:00Z"
    page.attachments = []
    return page


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_create_passes_upload_descriptors(mock_redmine):
    mock_redmine.upload.return_value = {"token": "tok-1"}
    mock_redmine.wiki_page.create.return_value = _make_wiki_page()

    result = await manage_redmine_wiki_page(
        action="create",
        project_id="proj",
        wiki_page_title="Page",
        text="# Body",
        uploads=[{"filename": "diagram.drawio", "content_base64": B64}],
    )

    assert "error" not in result
    _, kwargs = mock_redmine.wiki_page.create.call_args
    assert kwargs["uploads"] == [{"token": "tok-1", "filename": "diagram.drawio"}]
    assert kwargs["text"] == "# Body"


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_create_upload_failure_short_circuits(mock_redmine):
    result = await manage_redmine_wiki_page(
        action="create",
        project_id="proj",
        wiki_page_title="Page",
        text="# Body",
        uploads=[{"content_base64": B64}],  # no filename -> resolver error
    )

    assert "uploads[0]" in result["error"]
    mock_redmine.wiki_page.create.assert_not_called()


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_update_with_text_passes_upload_descriptors(mock_redmine):
    mock_redmine.upload.return_value = {"token": "tok-2"}
    mock_redmine.wiki_page.get.return_value = _make_wiki_page(text="new body")

    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        text="new body",
        uploads=[{"filename": "a.txt", "content_base64": B64}],
    )

    assert "error" not in result
    args, kwargs = mock_redmine.wiki_page.update.call_args
    assert args[0] == "Page"
    assert kwargs["text"] == "new body"
    assert kwargs["uploads"] == [{"token": "tok-2", "filename": "a.txt"}]
    # Explicit text means no read-back, so version is not sent.
    assert "version" not in kwargs


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_update_upload_failure_short_circuits(mock_redmine):
    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        text="new body",
        uploads=[{"content_base64": B64}],  # no filename -> resolver error
    )

    assert "uploads[0]" in result["error"]
    mock_redmine.wiki_page.update.assert_not_called()


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_attachment_only_update_reuses_fetched_text_and_version(mock_redmine):
    mock_redmine.upload.return_value = {"token": "tok-3"}
    mock_redmine.wiki_page.get.return_value = _make_wiki_page(
        text="existing body", version=7
    )

    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        uploads=[{"filename": "diagram.drawio", "content_base64": B64}],
    )

    assert "error" not in result
    _, kwargs = mock_redmine.wiki_page.update.call_args
    # Body came from the server, never from the caller.
    assert kwargs["text"] == "existing body"
    # Version is echoed back so a concurrent edit 409s instead of reverting.
    assert kwargs["version"] == 7
    assert kwargs["uploads"] == [{"token": "tok-3", "filename": "diagram.drawio"}]


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_update_without_text_or_uploads_is_rejected(mock_redmine):
    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
    )

    assert "text is required" in result["error"]
    mock_redmine.wiki_page.update.assert_not_called()


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_attachment_only_update_skips_readback_when_text_given(mock_redmine):
    mock_redmine.upload.return_value = {"token": "tok-4"}
    mock_redmine.wiki_page.get.return_value = _make_wiki_page(text="server body")

    await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        text="caller body",
        uploads=[{"filename": "a.txt", "content_base64": B64}],
    )

    _, kwargs = mock_redmine.wiki_page.update.call_args
    assert kwargs["text"] == "caller body"
    # Exactly one get(), the post-update re-fetch. No read-back happened.
    assert mock_redmine.wiki_page.get.call_count == 1
