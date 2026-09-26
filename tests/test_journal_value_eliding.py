"""Tests for eliding long before/after values in journal details (#313).

Redmine journals a description change with the full old *and* new text. A
ticket whose description is edited repeatedly therefore carries several
copies of it in its change log: measured at 94% of an 879k-character issue
response, against 0.5% of actual comment text. These tests pin that the
text is reported by length instead, and that a caller can still ask for it.
"""

import json

import pytest

from redmine_mcp_server.tools.issues import (
    _journal_details_to_list,
    _journal_value_max_chars,
    _journals_to_list,
)


class _Journal:
    def __init__(self, details, journal_id=1, notes=""):
        self.id = journal_id
        self.details = details
        self.notes = notes
        self.user = None
        self.created_on = None
        self.private_notes = False


def _description_change(old_chars=30_000, new_chars=50_000):
    return _Journal(
        [
            {
                "property": "attr",
                "name": "description",
                "old_value": "a" * old_chars,
                "new_value": "b" * new_chars,
            }
        ]
    )


@pytest.mark.unit
class TestEliding:
    def test_long_values_are_reported_by_length(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", raising=False)

        (detail,) = _journal_details_to_list(_description_change())

        assert detail["elided"] is True
        assert detail["old_value_length"] == 30_000
        assert detail["new_value_length"] == 50_000
        # The keys stay, so a caller reading them gets None rather than a
        # KeyError, and the flag tells it apart from an empty value.
        assert "old_value" in detail and "new_value" in detail
        assert "a" * 100 not in json.dumps(detail)

    def test_short_values_are_untouched(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", raising=False)
        journal = _Journal(
            [
                {
                    "property": "attr",
                    "name": "status_id",
                    "old_value": "2",
                    "new_value": "3",
                }
            ]
        )

        (detail,) = _journal_details_to_list(journal)

        assert "elided" not in detail
        assert "old_value_length" not in detail
        assert detail["old_value"] == "2"
        assert detail["new_value"] == "3"

    def test_each_value_is_judged_on_its_own(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", "10")
        journal = _Journal(
            [
                {
                    "property": "attr",
                    "name": "subject",
                    "old_value": "short",
                    "new_value": "x" * 50,
                }
            ]
        )

        (detail,) = _journal_details_to_list(journal)

        assert detail["elided"] is True
        assert "old_value_length" not in detail
        assert detail["new_value_length"] == 50
        # The short one survives -- wrapped, since subject is free text.
        assert "short" in str(detail["old_value"])

    def test_include_values_returns_the_text(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", raising=False)

        (detail,) = _journal_details_to_list(
            _description_change(), include_values=True
        )

        assert "elided" not in detail
        assert "a" * 30_000 in str(detail["old_value"])
        assert "b" * 50_000 in str(detail["new_value"])

    def test_threshold_zero_disables_eliding(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", "0")

        (detail,) = _journal_details_to_list(_description_change())

        assert "elided" not in detail
        assert "a" * 30_000 in str(detail["old_value"])

    def test_non_string_values_are_left_alone(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", "1")
        journal = _Journal(
            [
                {
                    "property": "attr",
                    "name": "estimated_hours",
                    "old_value": None,
                    "new_value": 7,
                }
            ]
        )

        (detail,) = _journal_details_to_list(journal)

        assert "elided" not in detail
        assert detail["new_value"] == 7


@pytest.mark.unit
class TestThresholdConfig:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", raising=False)
        assert _journal_value_max_chars() == 500

    @pytest.mark.parametrize("raw", ["", "   ", "not-a-number"])
    def test_unusable_values_fall_back_to_the_default(self, monkeypatch, raw):
        monkeypatch.setenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", raw)
        assert _journal_value_max_chars() == 500

    def test_negative_is_read_as_disabled(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", "-20")
        assert _journal_value_max_chars() == 0


@pytest.mark.unit
class TestWhatThisSaves:
    def test_a_repeatedly_edited_description_stops_dominating(self, monkeypatch):
        """The shape of the ticket that prompted #313.

        Fourteen description edits against two real comments: the change log
        was 94% of the response and the comments 0.5%.
        """
        monkeypatch.delenv("REDMINE_MCP_JOURNAL_VALUE_MAX_CHARS", raising=False)

        class _Issue:
            journals = [_description_change(30_000, 50_000) for _ in range(14)] + [
                _Journal([], journal_id=99, notes="the actual comment")
            ]

            def raw(self):
                return {"journals": self.journals}

        elided = json.dumps(_journals_to_list(_Issue()))
        full = json.dumps(_journals_to_list(_Issue(), include_journal_values=True))

        assert len(full) > 1_000_000
        assert len(elided) < len(full) / 50
        # The comment -- the part anyone wanted -- survives either way.
        assert "the actual comment" in elided
