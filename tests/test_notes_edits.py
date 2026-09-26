"""Tests for patching a note in place (#317, second half).

Unlike replacing a note from a file, patching has to read the current text
first -- and Redmine serves no endpoint for a single journal, so it can only
be read through its issue. Hence `issue_id`, asked for only on this path,
and an error that has to fit a note the caller cannot see.
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from redmine_mcp_server.tools.issues import get_redmine_issue, manage_issue_note

NOTE = "<p>Der Dienst laeuft auf zwei Knoten.</p>\n<p>Stand: offen.</p>\n"


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _journal(journal_id, notes):
    journal = MagicMock()
    journal.id = journal_id
    journal.notes = notes
    journal.details = []
    journal.user = None
    journal.created_on = None
    journal.private_notes = False
    return journal


def _issue(journals):
    issue = MagicMock()
    issue.id = 43376
    issue.description = "beschreibung"
    issue.journals = journals
    issue.attachments = []
    issue.raw.return_value = {"journals": journals, "attachments": []}
    return issue


@pytest.fixture
def mock_redmine(monkeypatch):
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
    with patch("redmine_mcp_server._client.redmine") as mock:
        mock.issue.get.return_value = _issue([_journal(514482, NOTE)])
        yield mock


@pytest.mark.unit
class TestPatching:
    @pytest.mark.asyncio
    async def test_only_the_changed_passage_is_sent(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            issue_id=43376,
            notes_edits=[{"find": "zwei Knoten", "replace": "vier Knoten"}],
        )

        written = mock_redmine.issue_journal.update.call_args.kwargs["notes"]
        assert "vier Knoten" in written
        assert "<p>Stand: offen.</p>" in written
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_the_note_is_not_echoed_back(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            issue_id=43376,
            notes_edits=[{"find": "zwei", "replace": "vier"}],
        )

        assert "notes" not in result
        assert result["notes_length"] > 0
        assert result["notes_sha256"] == _sha(NOTE.replace("zwei", "vier"))

    @pytest.mark.asyncio
    async def test_an_ambiguous_find_writes_nothing(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            issue_id=43376,
            notes_edits=[{"find": "<p>", "replace": "<div>"}],
        )

        assert "error" in result
        assert "ambiguous" in result["error"]
        mock_redmine.issue_journal.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_error_names_the_note_not_the_description(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            issue_id=43376,
            notes_edits=[{"find": "nicht vorhanden", "replace": "x"}],
        )

        assert "notes_edits[0]" in result["error"]
        assert "description" not in result["error"]


@pytest.mark.unit
class TestTheSecondId:
    @pytest.mark.asyncio
    async def test_issue_id_is_required_for_edits(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            notes_edits=[{"find": "zwei", "replace": "vier"}],
        )

        assert "error" in result
        assert "issue_id" in result["error"]
        mock_redmine.issue_journal.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_it_is_not_required_for_the_other_paths(self, mock_redmine):
        result = await manage_issue_note(
            action="edit", journal_id=514482, notes="<p>direkt</p>"
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_a_journal_not_on_that_issue_is_refused(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=999999,
            issue_id=43376,
            notes_edits=[{"find": "zwei", "replace": "vier"}],
        )

        assert "error" in result
        mock_redmine.issue_journal.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_that_refusal_allows_for_a_note_it_cannot_see(self, mock_redmine):
        """A private note is absent from the response, not marked as hidden.

        So the message must not claim the journal does not exist.
        """
        result = await manage_issue_note(
            action="edit",
            journal_id=999999,
            issue_id=43376,
            notes_edits=[{"find": "zwei", "replace": "vier"}],
        )

        assert "View private notes" in result["error"]
        assert "does not exist" not in result["error"]
        assert "visible to you" in result["error"]


@pytest.mark.unit
class TestTheGuard:
    @pytest.mark.asyncio
    async def test_the_digest_comes_from_the_read_tool(self, mock_redmine):
        read = await get_redmine_issue(issue_id=43376)
        journal = read["journals"][0]

        assert journal["notes_sha256"] == _sha(NOTE)
        # And emphatically not of what the caller can see.
        assert journal["notes_sha256"] != _sha(journal["notes"])

        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            issue_id=43376,
            notes_edits=[{"find": "zwei", "replace": "vier"}],
            notes_expected_sha256=journal["notes_sha256"],
        )

        assert "error" not in result

    @pytest.mark.asyncio
    async def test_a_stale_digest_writes_nothing(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            issue_id=43376,
            notes_edits=[{"find": "zwei", "replace": "vier"}],
            notes_expected_sha256=_sha("eine andere Fassung"),
        )

        assert "error" in result
        assert "notes has changed since it was read" in result["error"]
        mock_redmine.issue_journal.update.assert_not_called()


@pytest.mark.unit
class TestExclusivity:
    @pytest.mark.asyncio
    async def test_edits_and_notes_together_are_refused(self, mock_redmine):
        result = await manage_issue_note(
            action="edit",
            journal_id=514482,
            issue_id=43376,
            notes="<p>ganz neu</p>",
            notes_edits=[{"find": "zwei", "replace": "vier"}],
        )

        assert "error" in result
        assert "one way at a time" in result["error"]
        mock_redmine.issue_journal.update.assert_not_called()
