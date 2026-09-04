"""Tests for the pass-through of non-standard top-level issue fields.

Redmine distributions and plugins add their own top-level keys to the issue
JSON (Easy Redmine sends ``easy_sprint`` and ``easy_story_points``). The
serializers expose them under ``unmapped_fields`` instead of dropping them.
"""

from unittest.mock import Mock

import pytest

from redmine_mcp_server.tools.issues import (
    _ISSUE_SERIALIZED_KEYS,
    _issue_unmapped_fields,
    _issue_to_dict,
    _issue_to_dict_selective,
)

# Top-level shape Easy Redmine returns for an issue, trimmed to the point.
EASY_PAYLOAD = {
    "id": 16849,
    "subject": "Print summary register",
    "description": "",
    "project": {"id": 65, "name": "SIS4CARE"},
    "status": {"id": 3, "name": "Closed"},
    "done_ratio": 0,
    "is_private": False,
    "created_on": "2024-11-05T11:19:23Z",
    "updated_on": "2025-01-23T18:03:01Z",
    "custom_fields": [{"id": 13, "name": "Area", "value": ""}],
    # python-redmine seeds the include keys to None on every resource.
    "journals": None,
    "attachments": None,
    "relations": None,
    "children": None,
    "watchers": None,
    "changesets": None,
    "allowed_statuses": None,
    "time_entries": None,
    # Not part of the standard Redmine API.
    "is_favorited": False,
    "easy_sprint": {"id": 356, "name": "June 2025", "due_date": "2025-06-30"},
    "easy_story_points": 0,
}

EXPECTED_EXTRA = {
    "is_favorited": False,
    "easy_sprint": {"id": 356, "name": "June 2025", "due_date": "2025-06-30"},
    "easy_story_points": 0,
}


def _issue_with_raw(payload):
    """Mock issue whose raw() returns the given decoded payload."""
    issue = Mock()
    issue.raw.return_value = payload
    issue.id = payload.get("id")
    issue.subject = payload.get("subject", "")
    issue.description = payload.get("description", "")
    issue.project = Mock(id=65, name="SIS4CARE")
    issue.status = Mock(id=3, name="Closed")
    issue.priority = None
    issue.author = None
    issue.assigned_to = None
    issue.tracker = None
    issue.category = None
    issue.fixed_version = None
    issue.parent = None
    issue.start_date = None
    issue.due_date = None
    issue.closed_on = None
    issue.created_on = None
    issue.updated_on = None
    issue.custom_fields = []
    return issue


class TestIssueExtraFields:
    def test_unknown_top_level_keys_are_collected(self):
        issue = _issue_with_raw(EASY_PAYLOAD)
        assert _issue_unmapped_fields(issue) == EXPECTED_EXTRA

    def test_serialized_and_include_keys_are_excluded(self):
        issue = _issue_with_raw(EASY_PAYLOAD)
        extra = _issue_unmapped_fields(issue)
        assert not set(extra) & _ISSUE_SERIALIZED_KEYS

    def test_standard_payload_yields_nothing(self):
        payload = {k: v for k, v in EASY_PAYLOAD.items() if k not in EXPECTED_EXTRA}
        assert _issue_unmapped_fields(_issue_with_raw(payload)) == {}

    @pytest.mark.parametrize(
        "issue",
        [
            Mock(),  # raw() returns a Mock, not a dict
            Mock(spec=[]),  # no raw() at all
            Mock(raw=Mock(side_effect=RuntimeError("boom"))),
        ],
        ids=["raw-not-dict", "no-raw", "raw-raises"],
    )
    def test_objects_without_a_dict_payload_yield_nothing(self, issue):
        assert _issue_unmapped_fields(issue) == {}

    def test_values_are_passed_through_untouched(self):
        payload = dict(EASY_PAYLOAD, easy_sprint=None, plugin_list=[1, "a", None])
        extra = _issue_unmapped_fields(_issue_with_raw(payload))
        assert extra["easy_sprint"] is None
        assert extra["plugin_list"] == [1, "a", None]


class TestIssueToDictExtraFields:
    def test_unmapped_fields_present_when_payload_has_them(self):
        result = _issue_to_dict(_issue_with_raw(EASY_PAYLOAD))
        assert result["unmapped_fields"] == EXPECTED_EXTRA
        # Nothing leaks to the top level.
        assert "easy_sprint" not in result

    def test_key_absent_without_unmapped_fields(self):
        payload = {k: v for k, v in EASY_PAYLOAD.items() if k not in EXPECTED_EXTRA}
        result = _issue_to_dict(_issue_with_raw(payload))
        assert "unmapped_fields" not in result

    def test_key_absent_for_plain_mock(self):
        issue = Mock()
        issue.journals = []
        issue.attachments = []
        assert "unmapped_fields" not in _issue_to_dict(issue)

    def test_flags_still_honoured(self):
        result = _issue_to_dict(
            _issue_with_raw(EASY_PAYLOAD),
            include_custom_fields=True,
        )
        assert "custom_fields" in result
        assert result["unmapped_fields"] == EXPECTED_EXTRA


class TestIssueToDictSelectiveExtraFields:
    def test_all_fields_delegates(self):
        for fields in (None, ["*"], ["all"]):
            result = _issue_to_dict_selective(_issue_with_raw(EASY_PAYLOAD), fields)
            assert result["unmapped_fields"] == EXPECTED_EXTRA

    def test_selectable_by_name(self):
        result = _issue_to_dict_selective(
            _issue_with_raw(EASY_PAYLOAD), ["id", "unmapped_fields"]
        )
        assert result == {"id": 16849, "unmapped_fields": EXPECTED_EXTRA}

    def test_not_included_unless_named(self):
        result = _issue_to_dict_selective(_issue_with_raw(EASY_PAYLOAD), ["id"])
        assert result == {"id": 16849}

    def test_named_but_empty_is_skipped(self):
        payload = {k: v for k, v in EASY_PAYLOAD.items() if k not in EXPECTED_EXTRA}
        result = _issue_to_dict_selective(
            _issue_with_raw(payload), ["id", "unmapped_fields"]
        )
        assert result == {"id": 16849}
