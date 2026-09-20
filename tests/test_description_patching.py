"""Tests for patching a description instead of replacing it (#314).

Redmine replaces `description` wholesale, so the finished text has to come
from somewhere -- and having the model produce it means writing out every
character of a 50 KB field. These tests pin the server-side alternative:
send the passage that changed, and refuse anything ambiguous rather than
landing an edit in the wrong place.
"""

import hashlib

import pytest

from redmine_mcp_server.tools.issues import _apply_text_edits


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


DOC = """<h2>Ausgangslage</h2>
<p>Der Dienst laeuft auf zwei Knoten.</p>
<h2>Ziel</h2>
<p>Der Dienst laeuft auf drei Knoten.</p>
"""


@pytest.mark.unit
class TestApplyingEdits:
    def test_a_single_edit_lands(self):
        new, error = _apply_text_edits(
            DOC,
            [{"find": "zwei Knoten", "replace": "vier Knoten"}],
            None,
            "description",
        )

        assert error is None
        assert "vier Knoten" in new
        assert "zwei Knoten" not in new
        # Everything else is untouched.
        assert new.count("<h2>") == 2
        assert "drei Knoten" in new

    def test_edits_apply_in_order_and_can_build_on_each_other(self):
        new, error = _apply_text_edits(
            DOC,
            [
                {"find": "zwei Knoten", "replace": "TEMP"},
                {"find": "TEMP", "replace": "fuenf Knoten"},
            ],
            None,
            "description",
        )

        assert error is None
        assert "fuenf Knoten" in new
        assert "TEMP" not in new

    def test_replacing_with_empty_deletes(self):
        new, error = _apply_text_edits(
            DOC, [{"find": "<h2>Ziel</h2>\n", "replace": ""}], None, "description"
        )

        assert error is None
        assert "<h2>Ziel</h2>" not in new
        assert "<h2>Ausgangslage</h2>" in new

    def test_the_payload_is_the_change_not_the_document(self):
        """The whole point: a big field, a small argument."""
        big = "<p>Zeile</p>\n" * 5000 + "<p>zu aendern</p>\n"
        edits = [{"find": "zu aendern", "replace": "geaendert"}]

        new, error = _apply_text_edits(big, edits, None, "description")

        assert error is None
        assert "geaendert" in new
        assert len(str(edits)) < len(big) / 1000


@pytest.mark.unit
class TestRefusals:
    def test_a_find_that_is_absent_changes_nothing(self):
        new, error = _apply_text_edits(
            DOC, [{"find": "sechs Knoten", "replace": "x"}], None, "description"
        )

        assert new is None
        assert "does not occur" in error["error"]

    def test_an_ambiguous_find_is_refused(self):
        new, error = _apply_text_edits(
            DOC,
            [{"find": "Der Dienst laeuft auf", "replace": "x"}],
            None,
            "description",
        )

        assert new is None
        assert "occurs 2 times" in error["error"]
        assert "ambiguous" in error["error"]

    def test_a_later_failing_edit_discards_the_earlier_ones(self):
        """A half-applied patch is worse than none."""
        new, error = _apply_text_edits(
            DOC,
            [
                {"find": "zwei Knoten", "replace": "vier Knoten"},
                {"find": "nicht vorhanden", "replace": "x"},
            ],
            None,
            "description",
        )

        assert new is None
        assert "description_edits[1]" in error["error"]

    @pytest.mark.parametrize(
        "edits",
        [[], "not-a-list", None, [{"replace": "x"}], [{"find": "", "replace": "x"}]],
    )
    def test_unusable_edits_are_reported(self, edits):
        new, error = _apply_text_edits(DOC, edits, None, "description")

        assert new is None
        assert "error" in error

    def test_replace_must_be_a_string(self):
        new, error = _apply_text_edits(
            DOC, [{"find": "zwei Knoten", "replace": 4}], None, "description"
        )

        assert new is None
        assert "'replace' must be a string" in error["error"]


@pytest.mark.unit
class TestConcurrencyGuard:
    def test_matching_digest_passes(self):
        new, error = _apply_text_edits(
            DOC,
            [{"find": "zwei Knoten", "replace": "vier Knoten"}],
            _sha(DOC),
            "description",
        )

        assert error is None
        assert "vier Knoten" in new

    def test_a_changed_description_refuses_the_edit(self):
        """Somebody else edited between the read and the write."""
        stale = _sha(DOC.replace("zwei", "sieben"))

        new, error = _apply_text_edits(
            DOC,
            [{"find": "zwei Knoten", "replace": "vier Knoten"}],
            stale,
            "description",
        )

        assert new is None
        assert "has changed since it was read" in error["error"]
        assert stale in error["error"]

    def test_the_digest_is_optional(self):
        new, error = _apply_text_edits(
            DOC, [{"find": "zwei Knoten", "replace": "vier"}], None, "description"
        )

        assert error is None

    def test_case_and_whitespace_in_the_digest_do_not_matter(self):
        new, error = _apply_text_edits(
            DOC,
            [{"find": "zwei Knoten", "replace": "vier"}],
            f"  {_sha(DOC).upper()}  ",
            "description",
        )

        assert error is None

    def test_a_non_string_digest_is_reported(self):
        new, error = _apply_text_edits(
            DOC, [{"find": "zwei", "replace": "vier"}], 12345, "description"
        )

        assert new is None
        assert "must be a hex string" in error["error"]


@pytest.mark.unit
class TestLabelling:
    def test_errors_name_the_field_they_are_about(self):
        """The helper is written to serve notes too, once #314's part 3 lands."""
        new, error = _apply_text_edits(
            "some note", [{"find": "absent", "replace": "x"}], None, "notes"
        )

        assert new is None
        assert "notes_edits[0]" in error["error"]
        assert "current notes" in error["error"]


@pytest.mark.unit
class TestThroughTheTool:
    """The parameters as `update_redmine_issue` exposes them."""

    @pytest.fixture
    def mock_redmine(self):
        from unittest.mock import patch

        with patch("redmine_mcp_server._client.redmine") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_patching_sends_only_the_finished_text_to_redmine(
        self, mock_redmine, monkeypatch
    ):
        from unittest.mock import MagicMock

        from redmine_mcp_server.tools.issues import update_redmine_issue

        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        current = MagicMock()
        current.description = DOC
        mock_redmine.issue.get.return_value = current

        await update_redmine_issue(
            issue_id=7,
            fields={},
            description_edits=[{"find": "zwei Knoten", "replace": "vier Knoten"}],
            description_expected_sha256=_sha(DOC),
        )

        sent = mock_redmine.issue.update.call_args
        assert sent is not None
        description = sent.kwargs["description"]
        assert "vier Knoten" in description
        assert "zwei Knoten" not in description

    @pytest.mark.asyncio
    async def test_edits_and_a_full_description_together_are_refused(
        self, mock_redmine, monkeypatch
    ):
        from redmine_mcp_server.tools.issues import update_redmine_issue

        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)

        result = await update_redmine_issue(
            issue_id=7,
            fields={"description": "a whole new text"},
            description_edits=[{"find": "x", "replace": "y"}],
        )

        assert "error" in result
        assert "one way at a time" in result["error"]
        mock_redmine.issue.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failed_edit_never_reaches_redmine(self, mock_redmine, monkeypatch):
        from unittest.mock import MagicMock

        from redmine_mcp_server.tools.issues import update_redmine_issue

        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        current = MagicMock()
        current.description = DOC
        mock_redmine.issue.get.return_value = current

        result = await update_redmine_issue(
            issue_id=7,
            fields={},
            description_edits=[{"find": "nicht vorhanden", "replace": "x"}],
        )

        assert "error" in result
        mock_redmine.issue.update.assert_not_called()


@pytest.mark.unit
class TestStagedUploadAsTheSource:
    """The other half of #314: the text is all new, so send it as a file."""

    @pytest.fixture
    def attachments_dir(self, tmp_path, monkeypatch):
        path = tmp_path / "attachments"
        path.mkdir()
        monkeypatch.setenv("ATTACHMENTS_DIR", str(path))
        return path

    def _stage(self, text):
        from redmine_mcp_server import _upload_store

        issued = _upload_store.create_ticket(filename="description.html")
        record, reason = _upload_store.redeem_ticket(
            issued["upload_id"], issued["ticket"]
        )
        assert reason is None
        _upload_store.staged_path(record).write_bytes(text)
        _upload_store.mark_ready(issued["upload_id"], record, len(text), "x")
        return issued["upload_id"]

    def test_the_staged_text_becomes_the_description(self, attachments_dir):
        from redmine_mcp_server.tools.issues import _text_from_staged_upload

        upload_id = self._stage("<p>Ein neuer Text mit Ümläuten.</p>".encode("utf-8"))

        text, error = _text_from_staged_upload(upload_id, "description")

        assert error is None
        assert text == "<p>Ein neuer Text mit Ümläuten.</p>"

    def test_non_utf8_is_reported_rather_than_mangled(self, attachments_dir):
        from redmine_mcp_server.tools.issues import _text_from_staged_upload

        upload_id = self._stage(bytes([0xFF, 0xFE]) + b" not text")

        text, error = _text_from_staged_upload(upload_id, "description")

        assert text is None
        assert "not valid UTF-8" in error["error"]

    def test_an_unknown_upload_is_reported(self, attachments_dir):
        import uuid

        from redmine_mcp_server.tools.issues import _text_from_staged_upload

        text, error = _text_from_staged_upload(str(uuid.uuid4()), "description")

        assert text is None
        assert "error" in error

    @pytest.mark.asyncio
    async def test_two_sources_at_once_are_refused(self, attachments_dir, monkeypatch):
        from unittest.mock import patch

        from redmine_mcp_server.tools.issues import update_redmine_issue

        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        upload_id = self._stage(b"<p>neu</p>")

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            result = await update_redmine_issue(
                issue_id=7,
                fields={},
                description_edits=[{"find": "x", "replace": "y"}],
                description_upload_id=upload_id,
            )

            assert "error" in result
            assert "one way at a time" in result["error"]
            mock_redmine.issue.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_upload_reaches_redmine_as_the_description(
        self, attachments_dir, monkeypatch
    ):
        from unittest.mock import patch

        from redmine_mcp_server.tools.issues import update_redmine_issue

        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        upload_id = self._stage("<p>die neue Fassung</p>".encode("utf-8"))

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            await update_redmine_issue(
                issue_id=7, fields={}, description_upload_id=upload_id
            )

            sent = mock_redmine.issue.update.call_args
            assert sent.kwargs["description"] == "<p>die neue Fassung</p>"


@pytest.mark.unit
class TestDigestComesFromTheReadTool:
    """#316 review: a caller cannot hash what it read.

    `get_redmine_issue` wraps the description in `<insecure-content-...>`
    tags whose id is random per call, so a digest taken from the response
    text could never match the stored description. The tool hands the digest
    over instead.
    """

    @pytest.fixture
    def mock_redmine(self):
        from unittest.mock import patch

        with patch("redmine_mcp_server._client.redmine") as mock:
            yield mock

    def _issue(self, description):
        from unittest.mock import MagicMock

        issue = MagicMock()
        issue.id = 7
        issue.description = description
        issue.journals = []
        issue.attachments = []
        return issue

    @pytest.mark.asyncio
    async def test_the_read_tool_reports_a_digest_of_the_raw_description(
        self, mock_redmine
    ):
        from redmine_mcp_server.tools.issues import get_redmine_issue

        mock_redmine.issue.get.return_value = self._issue(DOC)

        result = await get_redmine_issue(issue_id=7, include_journals=False)

        assert result["description_sha256"] == _sha(DOC)
        # And emphatically not of what the caller can see.
        assert result["description_sha256"] != _sha(result["description"])
        assert "insecure-content" in result["description"]

    @pytest.mark.asyncio
    async def test_echoing_that_digest_back_is_accepted(self, mock_redmine):
        from redmine_mcp_server.tools.issues import (
            get_redmine_issue,
            update_redmine_issue,
        )

        mock_redmine.issue.get.return_value = self._issue(DOC)

        read = await get_redmine_issue(issue_id=7, include_journals=False)
        result = await update_redmine_issue(
            issue_id=7,
            fields={},
            description_edits=[{"find": "zwei Knoten", "replace": "vier Knoten"}],
            description_expected_sha256=read["description_sha256"],
        )

        assert "error" not in result
        assert (
            "vier Knoten" in mock_redmine.issue.update.call_args.kwargs["description"]
        )

    def test_the_mismatch_error_names_the_digest_to_retry_with(self):
        error = _apply_text_edits(
            DOC,
            [{"find": "zwei Knoten", "replace": "x"}],
            _sha("something else"),
            "description",
        )[1]

        assert _sha(DOC) in error["error"]
        assert "description_sha256" in error["error"]


@pytest.mark.unit
class TestLineEndings:
    """#316 review: Redmine's web UI saves CRLF."""

    CRLF_DOC = DOC.replace("\n", "\r\n")

    def test_a_plain_newline_find_matches_crlf_text(self):
        new, error = _apply_text_edits(
            self.CRLF_DOC,
            [
                {
                    "find": "<h2>Ziel</h2>\n<p>Der Dienst",
                    "replace": "<h2>Neu</h2>\n<p>Der Dienst",
                }
            ],
            None,
            "description",
        )

        assert error is None
        assert "<h2>Neu</h2>" in new

    def test_the_stored_convention_survives_the_edit(self):
        new, error = _apply_text_edits(
            self.CRLF_DOC,
            [{"find": "zwei Knoten", "replace": "vier Knoten"}],
            None,
            "description",
        )

        assert error is None
        assert "\r\n" in new
        assert "\n" not in new.replace("\r\n", "")
        # Including inside text the caller supplied with plain newlines.
        assert new.count("\r\n") == self.CRLF_DOC.count("\r\n")

    def test_a_multiline_replace_adopts_the_stored_convention(self):
        new, error = _apply_text_edits(
            self.CRLF_DOC,
            [
                {
                    "find": "<p>Der Dienst laeuft auf zwei Knoten.</p>",
                    "replace": "<p>Zeile eins.</p>\n<p>Zeile zwei.</p>",
                }
            ],
            None,
            "description",
        )

        assert error is None
        assert "<p>Zeile eins.</p>\r\n<p>Zeile zwei.</p>" in new

    def test_an_lf_document_stays_lf(self):
        new, error = _apply_text_edits(
            DOC,
            [{"find": "zwei Knoten", "replace": "vier Knoten"}],
            None,
            "description",
        )

        assert error is None
        assert "\r" not in new

    def test_the_digest_is_still_of_the_stored_text(self):
        """Normalisation is for matching only -- the guard sees the raw text."""
        new, error = _apply_text_edits(
            self.CRLF_DOC,
            [{"find": "zwei Knoten", "replace": "vier"}],
            _sha(self.CRLF_DOC),
            "description",
        )

        assert error is None
