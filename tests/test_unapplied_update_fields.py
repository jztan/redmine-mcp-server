"""``update_redmine_issue`` reports submitted fields Redmine discarded (#ISSUE).

``Issue#safe_attributes=`` drops several kinds of write without a validation
error -- a status the workflow does not allow (``attrs.delete('status_id')``
is unconditional, the assignment is not), a tracker or project outside the
allowed targets, whatever ``delete_unsafe_attributes`` removes, and custom
fields the user may not edit -- so ``save`` succeeds with the field unchanged
and the tool used to return the issue as if the write had landed.
"""

import base64
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.issues import (  # noqa: E402
    _unapplied_update_fields,
    update_redmine_issue,
)


def _ref(ref_id, name="x"):
    return SimpleNamespace(id=ref_id, name=name)


def _issue(**overrides):
    """A re-fetched issue, as a plain object so no attribute is invented."""
    attrs = {
        "id": 123,
        "subject": "Subject",
        "description": "Line one\r\nLine two",
        "project": _ref(1, "Project"),
        "status": _ref(1, "New"),
        "priority": _ref(2, "Normal"),
        "tracker": _ref(1, "Bug"),
        "author": _ref(1, "Author"),
        "assigned_to": None,
        "start_date": "2026-01-05",
        "due_date": None,
        "done_ratio": 0,
        "estimated_hours": None,
        "is_private": False,
        "custom_fields": [],
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def _serialized(**overrides):
    from redmine_mcp_server.tools.issues import _issue_to_dict

    issue = _issue(**overrides)
    return _issue_to_dict(issue, include_custom_fields=True), issue.description


def _unapplied(submitted, **issue_overrides):
    result, description = _serialized(**issue_overrides)
    return _unapplied_update_fields(submitted, result, description)


class TestReferenceFields:
    def test_discarded_status_is_reported(self):
        assert _unapplied({"status_id": 2}) == ["status_id"]

    def test_applied_status_is_not_reported(self):
        assert _unapplied({"status_id": 2}, status=_ref(2, "In Progress")) == []

    def test_digit_string_id_compares_as_int(self):
        assert _unapplied({"status_id": "2"}, status=_ref(2)) == []

    @pytest.mark.parametrize(
        "field,attr",
        [
            ("tracker_id", "tracker"),
            ("project_id", "project"),
            ("priority_id", "priority"),
            ("category_id", "category"),
            ("fixed_version_id", "fixed_version"),
            ("assigned_to_id", "assigned_to"),
            ("parent_issue_id", "parent"),
        ],
    )
    def test_each_reference_field_is_checked(self, field, attr):
        assert _unapplied({field: 99}) == [field]
        assert _unapplied({field: 99}, **{attr: _ref(99)}) == []

    @pytest.mark.parametrize("clear", [None, ""])
    def test_clearing_is_applied_when_the_ref_is_gone(self, clear):
        assert _unapplied({"assigned_to_id": clear}) == []

    def test_clear_discarded_when_the_ref_remains(self):
        assert _unapplied({"assigned_to_id": None}, assigned_to=_ref(5)) == [
            "assigned_to_id"
        ]

    @pytest.mark.parametrize("value", ["my-project", "me", "#12", True])
    def test_values_redmine_resolves_itself_are_not_checked(self, value):
        """A project identifier, ``me`` or ``#12`` cannot be confirmed from the
        re-fetched issue, so no claim is made either way."""
        assert _unapplied({"project_id": value, "assigned_to_id": value}) == []


class TestScalarFields:
    def test_dates(self):
        assert _unapplied({"start_date": "2026-01-05"}) == []
        assert _unapplied({"start_date": "2026-02-01"}) == ["start_date"]
        assert _unapplied({"due_date": None}) == []
        assert _unapplied({"due_date": ""}) == []
        assert _unapplied({"start_date": None}) == ["start_date"]

    def test_non_iso_date_is_not_checked(self):
        assert _unapplied({"due_date": "next week"}) == []

    def test_done_ratio(self):
        assert _unapplied({"done_ratio": 0}) == []
        assert _unapplied({"done_ratio": "50"}, done_ratio=50) == []
        assert _unapplied({"done_ratio": 50}) == ["done_ratio"]

    def test_estimated_hours(self):
        assert _unapplied({"estimated_hours": 2.5}, estimated_hours=2.5) == []
        assert _unapplied({"estimated_hours": "2.5"}, estimated_hours=2.5) == []
        assert _unapplied({"estimated_hours": 2}, estimated_hours=2.0) == []
        assert _unapplied({"estimated_hours": None}) == []
        assert _unapplied({"estimated_hours": 3}) == ["estimated_hours"]
        assert _unapplied({"estimated_hours": None}, estimated_hours=1.0) == [
            "estimated_hours"
        ]

    def test_estimated_hours_tolerates_single_precision_storage(self):
        """A MySQL FLOAT column reads 2.3 back as 2.2999999523."""
        assert _unapplied({"estimated_hours": 2.3}, estimated_hours=2.2999999523) == []
        assert _unapplied({"estimated_hours": 2.3}, estimated_hours=2.25) == [
            "estimated_hours"
        ]

    def test_estimated_hours_in_redmine_duration_syntax_is_not_checked(self):
        """``"1h30"`` is parsed by ``String#to_hours``; not re-implemented."""
        assert _unapplied({"estimated_hours": "1h30"}) == []

    def test_is_private(self):
        assert _unapplied({"is_private": False}) == []
        assert _unapplied({"is_private": "1"}, is_private=True) == []
        assert _unapplied({"is_private": True}) == ["is_private"]
        assert _unapplied({"is_private": "maybe"}) == []

    def test_subject(self):
        assert _unapplied({"subject": "Subject"}) == []
        assert _unapplied({"subject": "Renamed"}) == ["subject"]

    def test_description_ignores_line_endings(self):
        """Redmine stores the description with CRLF line endings."""
        assert _unapplied({"description": "Line one\nLine two"}) == []

    def test_description(self):
        assert _unapplied({"description": "Rewritten"}) == ["description"]
        assert _unapplied({"description": None}, description=None) == []
        assert _unapplied({"description": ""}, description="") == []


class TestCustomFields:
    def _cf(self, field_id, value, multiple=False):
        entry = {"id": field_id, "name": f"Field {field_id}", "value": value}
        if multiple:
            entry["multiple"] = True
        return entry

    def test_applied_value(self):
        assert (
            _unapplied(
                {"custom_fields": [{"id": 5, "value": "Gold"}]},
                custom_fields=[self._cf(5, "Gold")],
            )
            == []
        )

    def test_discarded_value_is_reported_by_id(self):
        assert _unapplied(
            {"custom_fields": [{"id": 5, "value": "Gold"}]},
            custom_fields=[self._cf(5, "Silver")],
        ) == ["cf_5"]

    def test_field_missing_from_the_response_is_reported(self):
        """Not visible to this user, so not editable either."""
        assert _unapplied(
            {"custom_fields": [{"id": 5, "value": "Gold"}]},
            custom_fields=[self._cf(6, "x")],
        ) == ["cf_5"]

    def test_values_are_compared_as_redmine_stores_them(self):
        stored = [
            self._cf(1, "7"),
            self._cf(2, "1"),
            self._cf(3, "1.5"),
            self._cf(4, ["b", "a"], multiple=True),
            self._cf(5, ""),
            self._cf(6, []),
            self._cf(7, "a\r\nb"),
        ]
        submitted = [
            {"id": 1, "value": 7},
            {"id": "2", "value": True},
            {"id": 3, "value": "1.50"},
            {"id": 4, "value": ["a", "b", "", "a"]},
            {"id": 5, "value": None},
            {"id": 6, "value": [""]},
            {"id": 7, "value": "a\nb"},
        ]
        assert _unapplied({"custom_fields": submitted}, custom_fields=stored) == []

    def test_malformed_entries_are_skipped(self):
        submitted = ["junk", {"value": "no id"}, {"id": None, "value": "x"}]
        assert _unapplied({"custom_fields": submitted}) == []

    def test_non_list_payload_is_not_checked(self):
        assert _unapplied({"custom_fields": None}) == []


class TestUncheckedKeys:
    @pytest.mark.parametrize(
        "key,value",
        [
            ("notes", "hello"),
            ("private_notes", True),
            ("watcher_user_ids", [3]),
            ("deleted_attachment_ids", [4]),
            ("some_plugin_key", "x"),
        ],
    )
    def test_never_reported(self, key, value):
        assert _unapplied({key: value}) == []


def _statuses(*pairs):
    statuses = []
    for status_id, name in pairs:
        status = Mock()
        status.id = status_id
        status.name = name
        statuses.append(status)
    return statuses


class TestThroughTheTool:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_workflow_discarded_status_is_reported(self, mock_redmine):
        """The reported case: success, the old status, no error field."""
        mock_redmine.issue.get.return_value = _issue()
        result = await update_redmine_issue(123, {"status_id": 2})
        assert "error" not in result
        assert result["status"] == {"id": 1, "name": "New"}
        assert result["unapplied_fields"] == ["status_id"]
        mock_redmine.issue.update.assert_called_once_with(123, status_id=2)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_applied_write_reports_nothing(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue(status=_ref(2, "In Progress"))
        result = await update_redmine_issue(123, {"status_id": 2, "notes": "moved"})
        assert result["unapplied_fields"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_no_extra_request(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue()
        await update_redmine_issue(123, {"status_id": 2, "subject": "Subject"})
        assert mock_redmine.issue.get.call_count == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_discarded_status_name_is_reported_under_that_key(self, mock_redmine):
        mock_redmine.issue_status.all.return_value = _statuses(
            (1, "New"), (2, "In Progress")
        )
        mock_redmine.issue.get.return_value = _issue()
        result = await update_redmine_issue(123, {"status_name": "In Progress"})
        assert result["unapplied_fields"] == ["status_name"]
        mock_redmine.issue.update.assert_called_once_with(123, status_id=2)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_unknown_status_name_is_refused_before_writing(self, mock_redmine):
        mock_redmine.issue_status.all.return_value = _statuses(
            (1, "New"), (2, "In Progress")
        )
        result = await update_redmine_issue(
            123, {"status_name": "Doing", "notes": "note"}
        )
        assert "Unknown status_name 'Doing'" in result["error"]
        assert "New, In Progress" in result["error"]
        mock_redmine.issue.update.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_status_lookup_failure_writes_the_rest_and_says_so(
        self, mock_redmine
    ):
        mock_redmine.issue_status.all.side_effect = Exception("API Error")
        mock_redmine.issue.get.return_value = _issue()
        result = await update_redmine_issue(
            123, {"status_name": "Closed", "notes": "note"}
        )
        assert "error" not in result
        assert result["unapplied_fields"] == ["status_name"]
        mock_redmine.issue.update.assert_called_once_with(123, notes="note")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_named_custom_field_discard_is_reported_by_id(self, mock_redmine):
        project_lookup = Mock()
        project_lookup.project = Mock(id=41, name="Project")
        mock_redmine.issue.get.side_effect = [
            project_lookup,
            _issue(custom_fields=[{"id": 6, "name": "Size", "value": "M"}]),
        ]
        size = Mock()
        size.id = 6
        size.name = "Size"
        size.possible_values = ["S", "M", "L"]
        project = Mock()
        project.issue_custom_fields = [size]
        mock_redmine.project.get.return_value = project

        result = await update_redmine_issue(123, {"size": "S"})

        assert mock_redmine.issue.update.call_args.kwargs["custom_fields"] == [
            {"id": 6, "value": "S"}
        ]
        assert result["unapplied_fields"] == ["cf_6"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_autofilled_fields_on_retry_are_not_checked(self, mock_redmine):
        """Compared with what the caller sent, not with the retry payload."""
        from redminelib.exceptions import ValidationError

        location = Mock()
        location.id = 8
        location.name = "Location"
        location.possible_values = [{"value": "Any"}]
        location.default_value = "Any"
        project = Mock()
        project.issue_custom_fields = [location]
        mock_redmine.project.get.return_value = project
        project_lookup = Mock()
        project_lookup.project = Mock(id=41, name="Project")
        mock_redmine.issue.update.side_effect = [
            ValidationError("Location cannot be blank"),
            None,
        ]
        mock_redmine.issue.get.side_effect = [
            project_lookup,
            _issue(status=_ref(2)),
        ]
        with patch.dict(
            os.environ, {"REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true"}, clear=False
        ):
            result = await update_redmine_issue(123, {"status_id": 2})

        assert mock_redmine.issue.update.call_count == 2
        assert result["unapplied_fields"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_upload_path_reports_too(self, mock_redmine):
        mock_redmine.upload.return_value = {"token": "tok"}
        mock_redmine.issue.get.return_value = _issue(attachments=[], journals=[])
        result = await update_redmine_issue(
            123,
            {"status_id": 2},
            uploads=[
                {
                    "filename": "a.txt",
                    "content_base64": base64.b64encode(b"x").decode("ascii"),
                }
            ],
        )
        assert result["unapplied_fields"] == ["status_id"]
        assert result["attachments"] == []
