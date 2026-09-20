"""Tests for `notes_upload_id` on `manage_issue_note` (#317).

Editing a long note had the same problem as a long description: the whole
text has to be written out into a tool argument. Staging it as a file takes
that path away, and the response reports a length and a digest rather than
echoing the note -- otherwise the text would end up in the conversation
after all, which is the cost this route exists to avoid.
"""

import hashlib
from unittest.mock import patch

import pytest

from redmine_mcp_server import _upload_store
from redmine_mcp_server.tools.issues import manage_issue_note

NOTE = "<p>Eine lange Notiz mit Ümläuten.</p>\n" * 200


@pytest.fixture
def attachments_dir(tmp_path, monkeypatch):
    path = tmp_path / "attachments"
    path.mkdir()
    monkeypatch.setenv("ATTACHMENTS_DIR", str(path))
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
    return path


@pytest.fixture
def mock_redmine():
    with patch("redmine_mcp_server._client.redmine") as mock:
        yield mock


def _stage(text: bytes) -> str:
    issued = _upload_store.create_ticket(filename="note.html")
    record, reason = _upload_store.redeem_ticket(issued["upload_id"], issued["ticket"])
    assert reason is None
    _upload_store.staged_path(record).write_bytes(text)
    _upload_store.mark_ready(issued["upload_id"], record, len(text), "x")
    return issued["upload_id"]


@pytest.mark.unit
class TestStagedNote:
    @pytest.mark.asyncio
    async def test_the_staged_text_reaches_redmine(self, attachments_dir, mock_redmine):
        upload_id = _stage(NOTE.encode("utf-8"))

        await manage_issue_note(
            action="edit", journal_id=514482, notes_upload_id=upload_id
        )

        sent = mock_redmine.issue_journal.update.call_args
        assert sent.kwargs["notes"] == NOTE

    @pytest.mark.asyncio
    async def test_the_note_is_not_echoed_back(self, attachments_dir, mock_redmine):
        upload_id = _stage(NOTE.encode("utf-8"))

        result = await manage_issue_note(
            action="edit", journal_id=514482, notes_upload_id=upload_id
        )

        assert "notes" not in result
        assert result["notes_length"] == len(NOTE)
        assert (
            result["notes_sha256"] == hashlib.sha256(NOTE.encode("utf-8")).hexdigest()
        )
        assert len(str(result)) < len(NOTE) / 10

    @pytest.mark.asyncio
    async def test_non_utf8_is_reported_and_nothing_is_written(
        self, attachments_dir, mock_redmine
    ):
        upload_id = _stage(bytes([0xFF, 0xFE]) + b" not text")

        result = await manage_issue_note(
            action="edit", journal_id=514482, notes_upload_id=upload_id
        )

        assert "error" in result
        assert "not valid UTF-8" in result["error"]
        mock_redmine.issue_journal.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_unsent_upload_is_reported(self, attachments_dir, mock_redmine):
        issued = _upload_store.create_ticket(filename="note.html")

        result = await manage_issue_note(
            action="edit", journal_id=514482, notes_upload_id=issued["upload_id"]
        )

        assert "error" in result
        mock_redmine.issue_journal.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_private_flag_still_rides_along(
        self, attachments_dir, mock_redmine
    ):
        upload_id = _stage(b"<p>kurz</p>")

        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            notes_upload_id=upload_id,
            private_notes=True,
        )

        assert result["private_notes"] is True
        assert (
            mock_redmine.issue_journal.update.call_args.kwargs["private_notes"] is True
        )


@pytest.mark.unit
class TestTheTwoSources:
    @pytest.mark.asyncio
    async def test_both_at_once_are_refused(self, attachments_dir, mock_redmine):
        upload_id = _stage(b"<p>aus der Datei</p>")

        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            notes="<p>direkt</p>",
            notes_upload_id=upload_id,
        )

        assert "error" in result
        assert "not both" in result["error"]
        mock_redmine.issue_journal.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_neither_is_refused_and_names_both(
        self, attachments_dir, mock_redmine
    ):
        result = await manage_issue_note(action="edit", journal_id=514482)

        assert "error" in result
        assert "notes" in result["error"]
        assert "notes_upload_id" in result["error"]

    @pytest.mark.asyncio
    async def test_plain_notes_still_echo_back(self, attachments_dir, mock_redmine):
        """Unchanged: a caller that wrote the text already has it."""
        result = await manage_issue_note(
            action="edit", journal_id=514482, notes="<p>kurz</p>"
        )

        assert result["notes"] == "<p>kurz</p>"
        assert "notes_sha256" not in result

    @pytest.mark.asyncio
    async def test_clearing_a_note_with_an_empty_string_still_works(
        self, attachments_dir, mock_redmine
    ):
        result = await manage_issue_note(action="edit", journal_id=514482, notes="")

        assert result["success"] is True
        assert mock_redmine.issue_journal.update.call_args.kwargs["notes"] == ""
