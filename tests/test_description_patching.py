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
        assert "not both" in result["error"]
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
