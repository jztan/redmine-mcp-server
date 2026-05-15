"""Tests for custom-field-name lookup on create_redmine_issue (#123).

``update_redmine_issue`` already accepts custom fields by name; #123
brought ``create_redmine_issue`` to parity. Both tools now route
through the shared ``_resolve_named_custom_fields`` helper, so this
suite both exercises the create-side wrapper end-to-end AND pins the
shared-helper contract directly.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from redminelib.exceptions import ValidationError as RedmineValidationError

from redmine_mcp_server._custom_fields import (
    _map_named_custom_fields_for_create,
    _resolve_named_custom_fields,
)
from redmine_mcp_server.tools.issues import create_redmine_issue


def _cf(field_id: int, name: str, possible_values=None) -> SimpleNamespace:
    """Build a python-redmine-shaped custom-field definition stub."""
    return SimpleNamespace(
        id=field_id,
        name=name,
        possible_values=possible_values or [],
    )


class TestResolveNamedCustomFieldsHelper:
    def test_name_keyed_entry_resolves_to_custom_fields_id(self):
        payload = {"Department": "Engineering"}
        custom_fields = [_cf(2, "Department")]
        out = _resolve_named_custom_fields(payload, custom_fields)
        assert out == {
            "custom_fields": [{"id": 2, "value": "Engineering"}],
        }

    def test_preserves_caller_provided_custom_fields_list(self):
        payload = {
            "Department": "Engineering",
            "custom_fields": [{"id": 1, "value": "High"}],
        }
        custom_fields = [_cf(2, "Department")]
        out = _resolve_named_custom_fields(payload, custom_fields)
        # Both entries present; order doesn't matter to Redmine.
        assert {"id": 1, "value": "High"} in out["custom_fields"]
        assert {"id": 2, "value": "Engineering"} in out["custom_fields"]

    def test_standard_keys_pass_through_unchanged(self):
        # subject / description / status_id etc. are not custom-field
        # candidates -- they belong at the top of the payload.
        payload = {
            "subject": "X",
            "status_id": 1,
            "Department": "Engineering",
        }
        out = _resolve_named_custom_fields(payload, [_cf(2, "Department")])
        assert out["subject"] == "X"
        assert out["status_id"] == 1
        assert out["custom_fields"] == [
            {"id": 2, "value": "Engineering"},
        ]

    def test_unknown_name_passes_through(self):
        # When a name-keyed field doesn't match any project custom
        # field definition, leave it on the payload. Redmine will
        # reject it with its own validation error, which is the
        # right surface for "this field doesn't exist."
        payload = {"NonExistent": "value"}
        out = _resolve_named_custom_fields(payload, [_cf(2, "Department")])
        assert out["NonExistent"] == "value"

    def test_ambiguous_name_raises(self):
        # Two custom fields share the normalized name -> the caller
        # must use the explicit id form.
        payload = {"Department": "Engineering"}
        custom_fields = [_cf(2, "Department"), _cf(3, "DEPARTMENT")]
        with pytest.raises(ValueError, match="Ambiguous"):
            _resolve_named_custom_fields(payload, custom_fields)

    def test_invalid_value_against_possible_values_raises(self):
        payload = {"Department": "BogusValue"}
        custom_fields = [
            _cf(2, "Department", possible_values=["Engineering", "Sales"]),
        ]
        with pytest.raises(ValueError, match="Invalid value"):
            _resolve_named_custom_fields(payload, custom_fields)


class TestCreateWrapperFetchesProjectCustomFields:
    """The create-side wrapper takes project_id directly (no parent
    issue lookup) and routes through the shared helper."""

    def test_wrapper_no_op_for_empty_payload(self):
        # The wrapper should short-circuit without calling out to
        # Redmine when there's nothing to resolve.
        with patch(
            "redmine_mcp_server._custom_fields._get_redmine_client"
        ) as client_factory:
            out = _map_named_custom_fields_for_create(1, {})
        assert out == {}
        client_factory.assert_not_called()

    def test_wrapper_fetches_project_and_resolves(self):
        project_obj = SimpleNamespace(issue_custom_fields=[_cf(2, "Department")])
        with patch(
            "redmine_mcp_server._custom_fields._get_redmine_client"
        ) as client_factory:
            client_factory.return_value.project.get.return_value = project_obj
            out = _map_named_custom_fields_for_create(1, {"Department": "Engineering"})
        assert out["custom_fields"] == [
            {"id": 2, "value": "Engineering"},
        ]


class TestCreateRedmineIssueEndToEnd:
    """Round-trip the create path: name-keyed input survives all the
    way into the python-redmine client call as custom_fields entries."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_creates_with_name_keyed_custom_field(self, mock_redmine):
        # Project lookup returns the custom field definition.
        mock_redmine.project.get.return_value = SimpleNamespace(
            issue_custom_fields=[_cf(2, "Department")]
        )
        # The create itself returns a minimal issue stub.
        mock_redmine.issue.create.return_value = SimpleNamespace(
            id=42,
            project=SimpleNamespace(id=1, name="Test"),
            tracker=SimpleNamespace(id=1, name="Bug"),
            status=SimpleNamespace(id=1, name="New"),
            priority=SimpleNamespace(id=1, name="Normal"),
            author=SimpleNamespace(id=1, name="Test User"),
            subject="X",
            description="",
            created_on=None,
            updated_on=None,
            custom_fields=[],
        )

        result = await create_redmine_issue(
            project_id=1,
            subject="X",
            fields={"Department": "Engineering"},
        )

        assert "error" not in result
        kwargs = mock_redmine.issue.create.call_args.kwargs
        # The named field was resolved into the custom_fields shape
        # Redmine actually accepts.
        assert kwargs["custom_fields"] == [
            {"id": 2, "value": "Engineering"},
        ]
        # The name-keyed entry was popped, not forwarded as a
        # top-level Redmine field (which would cause a 422).
        assert "Department" not in kwargs

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_validation_error_envelope_lists_known_recovery(self, mock_redmine):
        # The simplified hint (post-#123) promotes the name-keyed
        # shortcut and no longer carries the "does NOT yet support"
        # caveat.
        mock_redmine.project.get.return_value = SimpleNamespace(issue_custom_fields=[])
        mock_redmine.issue.create.side_effect = RedmineValidationError(
            "Department cannot be blank"
        )

        result = await create_redmine_issue(project_id=1, subject="X")

        assert result["missing_required_fields"] == ["Department"]
        hint = result["hint"]
        assert "create_redmine_issue does NOT yet support" not in hint
        assert '"Department": "Engineering"' in hint or "name lookup" in hint
