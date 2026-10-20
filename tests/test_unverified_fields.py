"""Pass-through issue keys are reported as ``unverified_fields`` (#380).

Since #370 a snake_case ``fields`` key that is not a standard issue key and
not a near miss for a custom field name goes to Redmine as a top-level
attribute, so plugin attributes such as ``agile_data_attributes`` keep
working. Redmine ignores a key it does not know without an error, and
``unapplied_fields`` cannot check a key whose stored form it cannot predict,
so ``customer_id`` (#378) reported success and changed nothing. The keys are
still sent, and the result now names them.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._custom_fields import _unverified_issue_fields  # noqa: E402
from redmine_mcp_server.tools.issues import (  # noqa: E402
    create_redmine_issue,
    update_redmine_issue,
)


def _ref(ref_id, name="x"):
    return {"id": ref_id, "name": name}


def _issue():
    payload = {
        "id": 123,
        "subject": "Subject",
        "description": "",
        "project": _ref(1, "Project"),
        "status": _ref(1, "New"),
        "priority": _ref(2, "Normal"),
        "tracker": _ref(1, "Bug"),
        "author": _ref(1, "Author"),
        "start_date": None,
        "due_date": None,
        "done_ratio": 0,
        "estimated_hours": None,
        "is_private": False,
        "custom_fields": [],
    }
    attrs = {
        key: SimpleNamespace(**value) if isinstance(value, dict) else value
        for key, value in payload.items()
    }
    return SimpleNamespace(raw=lambda: payload, **attrs)


_NO_CUSTOM_FIELDS = patch(
    "redmine_mcp_server._custom_fields._issue_custom_fields_for_name_lookup",
    return_value=[],
)


class TestUnverifiedIssueFields:
    def test_names_only_pass_through_keys(self):
        payload = {
            "customer_id": 726,
            "agile_data_attributes": {"story_points": 3},
            "notes": "x",
            "status_id": 2,
            "custom_fields": [{"id": 1, "value": "Low"}],
            "project_id": 4,
            "lock_version": 7,
            "custom_field_values": {"1": "Low"},
        }
        assert _unverified_issue_fields(payload) == [
            "agile_data_attributes",
            "customer_id",
        ]

    def test_empty_when_every_key_is_known(self):
        assert _unverified_issue_fields({"notes": "x", "subject": "y"}) == []

    def test_a_registered_extension_key_counts_as_known(self):
        with patch(
            "redmine_mcp_server._custom_fields.extension_issue_update_keys",
            return_value=frozenset({"easy_sprint_id"}),
        ):
            assert _unverified_issue_fields({"easy_sprint_id": 5}) == []


class TestUpdate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_ignored_key_is_sent_and_reported(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue()
        with patch(
            "redmine_mcp_server._custom_fields._resolve_project_issue_custom_fields",
            return_value=[],
        ):
            result = await update_redmine_issue(123, {"customer_id": 726})
        assert "error" not in result
        mock_redmine.issue.update.assert_called_once_with(123, customer_id=726)
        assert result["unverified_fields"] == ["customer_id"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_omitted_when_every_key_is_known(self, mock_redmine):
        mock_redmine.issue.get.return_value = _issue()
        result = await update_redmine_issue(123, {"notes": "x"})
        assert "error" not in result
        assert "unverified_fields" not in result


class TestCreate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_ignored_key_is_sent_and_reported(self, mock_redmine):
        mock_redmine.issue.create.return_value = _issue()
        with _NO_CUSTOM_FIELDS:
            result = await create_redmine_issue(
                1, "Subject", fields={"customer_id": 726}
            )
        assert "error" not in result
        assert mock_redmine.issue.create.call_args.kwargs["customer_id"] == 726
        assert result["unverified_fields"] == ["customer_id"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_omitted_when_every_key_is_known(self, mock_redmine):
        mock_redmine.issue.create.return_value = _issue()
        result = await create_redmine_issue(1, "Subject", fields={"priority_id": 2})
        assert "error" not in result
        assert "unverified_fields" not in result
