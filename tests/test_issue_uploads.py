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


@pytest.mark.asyncio
@patch("redmine_mcp_server.tools.issues._augment_fields_with_required_custom_fields")
@patch("redmine_mcp_server.tools.issues._extract_missing_required_field_names")
@patch("redmine_mcp_server.tools.issues._is_required_custom_field_autofill_enabled")
@patch("redmine_mcp_server._client.redmine")
async def test_update_retry_preserves_uploads(
    mock_redmine,
    mock_autofill_enabled,
    mock_extract_missing,
    mock_augment_fields,
):
    """Autofill retry must return attachments+journal_id when uploads were sent."""
    mock_autofill_enabled.return_value = True
    mock_extract_missing.return_value = ["My Required Field"]
    mock_augment_fields.return_value = {
        "subject": "x",
        "custom_fields": [{"id": 1, "value": "auto"}],
    }

    from redminelib.exceptions import ValidationError

    issue_before = MagicMock()
    issue_before.custom_fields = []

    call_count = {"n": 0}

    def update_side_effect(issue_id, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValidationError("Field cannot be blank")

    mock_redmine.upload.return_value = {"token": "tok-retry"}
    mock_redmine.issue.update.side_effect = update_side_effect
    mock_redmine.issue.get.return_value = _issue_with_attachment(
        issue_id=42, journal_id=99
    )

    result = await update_redmine_issue(
        42,
        {"subject": "x"},
        uploads=[{"filename": "retry.txt", "content_base64": B64}],
    )

    assert "error" not in result, f"Unexpected error: {result.get('error')}"

    # Both issue.update calls must carry the upload token.
    assert mock_redmine.issue.update.call_count == 2
    for call in mock_redmine.issue.update.call_args_list:
        _, kwargs = call
        assert "uploads" in kwargs, "uploads missing from an issue.update call"
        assert kwargs["uploads"] == [{"token": "tok-retry", "filename": "retry.txt"}]

    # Re-fetch after retry must use attachments,journals include.
    assert (
        mock_redmine.issue.get.call_args.kwargs.get("include") == "attachments,journals"
    )

    # Response must surface attachment metadata and journal_id.
    assert "attachments" in result, "attachments missing from retry-path response"
    assert result["journal_id"] == 99
