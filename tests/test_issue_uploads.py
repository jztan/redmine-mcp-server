"""Unit tests for file uploads on issue create/update."""

import base64
import os
import sys

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.issues import update_redmine_issue  # noqa: E402

B64 = base64.b64encode(b"file-bytes").decode("ascii")


def _issue_with_attachment(issue_id=42, journal_id=7):
    issue = MagicMock()
    issue.id = issue_id
    att = MagicMock()
    att.id = 99
    att.filename = "a.txt"
    issue.attachments = [att]
    journal = MagicMock()
    journal.id = journal_id
    issue.journals = [journal]
    return issue


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_update_with_upload_attaches_and_returns_metadata(mock_redmine):
    mock_redmine.upload.return_value = {"token": "tok-9"}
    mock_redmine.issue.get.return_value = _issue_with_attachment()
    result = await update_redmine_issue(
        42,
        {"notes": "see attached"},
        uploads=[{"filename": "a.txt", "content_base64": B64}],
    )
    assert "error" not in result
    # issue.update called with uploads containing the token + notes field.
    _, kwargs = mock_redmine.issue.update.call_args
    assert kwargs["uploads"] == [{"token": "tok-9", "filename": "a.txt"}]
    assert kwargs["notes"] == "see attached"
    # re-fetch used attachments,journals include and surfaced metadata.
    assert mock_redmine.issue.get.call_args.kwargs["include"] == "attachments,journals"
    assert result["attachments"][0]["id"] == 99
    assert result["journal_id"] == 7


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_pure_attach_with_empty_fields_still_updates(mock_redmine):
    mock_redmine.upload.return_value = {"token": "t"}
    mock_redmine.issue.get.return_value = _issue_with_attachment()
    result = await update_redmine_issue(
        42, {}, uploads=[{"filename": "a.txt", "content_base64": B64}]
    )
    assert "error" not in result
    mock_redmine.issue.update.assert_called_once()


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_update_rejects_uploads_inside_fields(mock_redmine):
    result = await update_redmine_issue(42, {"uploads": [{"x": 1}]})
    assert "error" in result
    assert "uploads" in result["error"]
    mock_redmine.issue.update.assert_not_called()


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_update_without_uploads_unchanged_return(mock_redmine):
    mock_redmine.issue.get.return_value = _issue_with_attachment()
    result = await update_redmine_issue(42, {"subject": "x"})
    # No uploads -> no attachment augmentation, plain get (no include kwarg).
    assert "attachments" not in result
    assert "include" not in mock_redmine.issue.get.call_args.kwargs


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_update_read_only_blocks_upload(mock_redmine, monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
    result = await update_redmine_issue(
        42, {}, uploads=[{"filename": "a.txt", "content_base64": B64}]
    )
    assert "error" in result
    mock_redmine.upload.assert_not_called()
