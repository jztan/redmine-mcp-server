"""Tests for the is_required discovery-mismatch hint (#119).

Redmine's ``list_project_issue_custom_fields`` reflects only the
field-definition ``is_required`` flag and does not see workflow rules,
role-based field permissions, or tracker-bound required-field settings.
A custom field with ``is_required: false`` can still cause
``create_redmine_issue`` / ``update_redmine_issue`` to reject with
``"<field name> cannot be blank"``.

To make the recovery path discoverable for an LLM caller, the
validation-error envelope from those two tools is augmented with
``missing_required_fields`` and ``hint`` keys when the error message
matches the canonical Redmine validation patterns.
"""

from unittest.mock import patch

import pytest
from redminelib.exceptions import ValidationError as RedmineValidationError

from redmine_mcp_server._custom_fields import (
    _augment_validation_error_with_field_hint,
)
from redmine_mcp_server.tools.issues import (
    create_redmine_issue,
    update_redmine_issue,
)


class TestAugmentValidationErrorHelper:
    def test_does_nothing_when_no_field_names_parseable(self):
        envelope = {"error": "Something went wrong"}
        out = _augment_validation_error_with_field_hint(envelope, "noise")
        assert out == envelope

    def test_custom_field_hint_names_custom_recovery(self):
        # Department is not in _STANDARD_FIELD_DISPLAY_NAMES -- treated
        # as a custom field. The hint must point at the working
        # extra_fields shape and the autofill env var, NOT at the
        # broken "custom-field-name lookup on create" shape.
        out = _augment_validation_error_with_field_hint(
            {"error": "Validation failed: Department cannot be blank"},
            "Department cannot be blank",
        )
        assert out["missing_required_fields"] == ["Department"]
        hint = out["hint"]
        assert "extra_fields" in hint
        assert "custom_fields" in hint
        # Honest about the asymmetry between create and update.
        assert "create_redmine_issue does NOT yet support" in hint
        assert "REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS" in hint
        assert "list_project_issue_custom_fields" in hint or "#119" in hint

    def test_standard_field_hint_names_standard_recovery(self):
        # "Priority" is a built-in Redmine field. The hint must NOT
        # steer the caller toward the custom-field machinery for it.
        out = _augment_validation_error_with_field_hint(
            {"error": "Validation failed: Priority cannot be blank"},
            "Priority cannot be blank",
        )
        assert out["missing_required_fields"] == ["Priority"]
        hint = out["hint"]
        assert "Standard fields" in hint
        assert "priority_id" in hint or "list_redmine_issue_priorities" in hint
        # No mention of the custom-field-only recovery paths -- that
        # would be misleading for a missing standard field.
        assert "extra_fields" not in hint
        assert "REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS" not in hint

    def test_mixed_fields_hint_includes_both_paths(self):
        out = _augment_validation_error_with_field_hint(
            {
                "error": "Validation failed: Priority cannot be blank, "
                "Department cannot be blank"
            },
            "Priority cannot be blank, Department cannot be blank",
        )
        assert set(out["missing_required_fields"]) == {
            "Priority",
            "Department",
        }
        hint = out["hint"]
        # Both recovery sections present.
        assert "Standard fields" in hint
        assert "extra_fields" in hint

    def test_preserves_existing_envelope_keys(self):
        envelope = {"error": "...", "code": "VAL_FAILED", "upstream_status": 422}
        out = _augment_validation_error_with_field_hint(
            envelope, "Department cannot be blank"
        )
        assert out["error"] == "..."
        assert out["code"] == "VAL_FAILED"
        assert out["upstream_status"] == 422

    def test_does_not_mutate_input(self):
        envelope = {"error": "Validation failed: Foo cannot be blank"}
        copy_before = dict(envelope)
        _augment_validation_error_with_field_hint(envelope, "Foo cannot be blank")
        assert envelope == copy_before

    def test_parses_multiple_fields(self):
        out = _augment_validation_error_with_field_hint(
            {
                "error": "Validation failed: Department cannot be blank, "
                "Priority is not included in the list"
            },
            "Department cannot be blank, Priority is not included in the list",
        )
        assert set(out["missing_required_fields"]) == {"Department", "Priority"}


class TestCreateIssueEnrichesValidationEnvelope:
    """The user-facing #119 fix: a 'cannot be blank' validation error on
    create_redmine_issue now carries the recovery hint."""

    @pytest.mark.asyncio
    async def test_envelope_includes_missing_field_and_hint(self):
        with patch("redmine_mcp_server._client.redmine") as m:
            m.issue.create.side_effect = RedmineValidationError(
                "Department cannot be blank"
            )
            result = await create_redmine_issue(project_id=1, subject="x")

        assert result.get("missing_required_fields") == ["Department"]
        assert "hint" in result
        hint = result["hint"]
        # Recovery shape that actually works on create.
        assert "extra_fields" in hint
        assert "custom_fields" in hint
        # Honest about the create-path asymmetry surfaced in
        # verification round 8.
        assert "create_redmine_issue does NOT yet support" in hint
        assert "REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS" in hint

    @pytest.mark.asyncio
    async def test_non_field_validation_error_is_not_augmented(self):
        # Validation errors that don't name a field shouldn't get the
        # hint -- noise on legitimate errors would be worse than silence.
        with patch("redmine_mcp_server._client.redmine") as m:
            m.issue.create.side_effect = RedmineValidationError(
                "Some unrelated server message"
            )
            result = await create_redmine_issue(project_id=1, subject="x")

        assert "missing_required_fields" not in result
        assert "hint" not in result


class TestUpdateIssueEnrichesValidationEnvelope:
    @pytest.mark.asyncio
    async def test_envelope_includes_missing_field_and_hint(self):
        with patch("redmine_mcp_server._client.redmine") as m:
            m.issue.update.side_effect = RedmineValidationError(
                "Department cannot be blank"
            )
            result = await update_redmine_issue(issue_id=1, fields={"subject": "x"})

        assert result.get("missing_required_fields") == ["Department"]
        assert "hint" in result
        assert "list_project_issue_custom_fields" in result["hint"]
