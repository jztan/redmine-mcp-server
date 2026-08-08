"""Conflict and validation error reporting for wiki writes."""

import base64
import os
import sys
from unittest.mock import Mock, patch

import pytest
from redminelib.exceptions import ConflictError, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page  # noqa: E402

B64 = base64.b64encode(b"bytes").decode("ascii")


def _page(text="body", version=3):
    page = Mock()
    page.title = "Page"
    page.text = text
    page.version = version
    page.created_on = "2026-08-08T10:00:00Z"
    page.updated_on = "2026-08-08T10:00:00Z"
    page.attachments = []
    return page


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_conflict_is_reported_as_edit_conflict(mock_redmine):
    mock_redmine.upload.return_value = {"token": "t"}
    mock_redmine.wiki_page.get.return_value = _page()
    mock_redmine.wiki_page.update.side_effect = ConflictError()

    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        uploads=[{"filename": "a.txt", "content_base64": B64}],
    )

    assert "Edit conflict" in result["error"]
    assert "retry" in result["error"].lower()


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_blank_text_validation_message_reaches_caller(mock_redmine):
    mock_redmine.wiki_page.update.side_effect = ValidationError(
        "Text field cannot be blank"
    )

    result = await manage_redmine_wiki_page(
        action="update",
        project_id="proj",
        wiki_page_title="Page",
        text="body",
    )

    assert "Text field cannot be blank" in result["error"]
