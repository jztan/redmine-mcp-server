"""Unit tests for Stage D time tracking tools.

Covers:
    - log_time_for_user
    - import_time_entries
"""

import os
import sys

import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    import_time_entries,
    log_time_for_user,
)


def _mock_with_name(id_val, name_val):
    m = Mock()
    m.id = id_val
    m.name = name_val
    return m


def _mock_time_entry(
    entry_id=1,
    hours=1.0,
    user_id=5,
    user_name="Alice",
    project_id=10,
    project_name="Test",
):
    """Create a minimal mock time entry that _time_entry_to_dict can handle."""
    te = Mock()
    te.id = entry_id
    te.hours = hours
    te.comments = ""
    te.spent_on = None
    te.user = _mock_with_name(user_id, user_name)
    te.project = _mock_with_name(project_id, project_name)
    te.issue = None
    te.activity = None
    te.created_on = None
    te.updated_on = None
    return te


# ---------------------------------------------------------------------------
# log_time_for_user
# ---------------------------------------------------------------------------


class TestLogTimeForUser:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_log_time_on_issue(self, mock_redmine):
        mock_redmine.time_entry.create.return_value = _mock_time_entry(
            entry_id=100, hours=2.5, user_id=7, user_name="Bob"
        )

        result = await log_time_for_user(
            user_id=7,
            hours=2.5,
            issue_id=123,
            comments="Bug fix",
        )

        assert result["id"] == 100
        mock_redmine.time_entry.create.assert_called_once_with(
            hours=2.5, user_id=7, issue_id=123, comments="Bug fix"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_log_time_on_project(self, mock_redmine):
        mock_redmine.time_entry.create.return_value = _mock_time_entry(
            entry_id=101, hours=1.0, user_id=7
        )

        result = await log_time_for_user(
            user_id=7,
            hours=1.0,
            project_id="web",
            activity_id=9,
            spent_on="2026-04-15",
        )

        assert result["id"] == 101
        mock_redmine.time_entry.create.assert_called_once_with(
            hours=1.0,
            user_id=7,
            project_id="web",
            activity_id=9,
            spent_on="2026-04-15",
        )

    @pytest.mark.asyncio
    async def test_missing_project_and_issue(self):
        result = await log_time_for_user(user_id=7, hours=1.0)
        assert "error" in result
        assert "project_id or issue_id" in result["error"]

    @pytest.mark.asyncio
    async def test_negative_hours(self):
        result = await log_time_for_user(user_id=7, hours=-1.0, issue_id=123)
        assert "error" in result
        assert "positive" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_zero_hours(self):
        result = await log_time_for_user(user_id=7, hours=0, issue_id=123)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await log_time_for_user(user_id=7, hours=1.0, issue_id=123)
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_forbidden(self, mock_redmine):
        """User lacks log_time_for_other_users permission."""
        from redminelib.exceptions import ForbiddenError

        mock_redmine.time_entry.create.side_effect = ForbiddenError()
        result = await log_time_for_user(user_id=7, hours=1.0, issue_id=123)
        assert "error" in result
        assert "Access denied" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_target_user_not_project_member(self, mock_redmine):
        """Known Redmine quirk: target user not in project -> 422."""
        from redminelib.exceptions import ValidationError

        mock_redmine.time_entry.create.side_effect = ValidationError("User is invalid")
        result = await log_time_for_user(user_id=999, hours=1.0, issue_id=123)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_issue_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.time_entry.create.side_effect = ResourceNotFoundError()
        result = await log_time_for_user(user_id=7, hours=1.0, issue_id=9999)
        assert "error" in result


# ---------------------------------------------------------------------------
# import_time_entries
# ---------------------------------------------------------------------------


class TestImportTimeEntries:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_bulk_import_all_succeed(self, mock_redmine):
        mock_redmine.time_entry.create.side_effect = [
            _mock_time_entry(entry_id=1, hours=2.0),
            _mock_time_entry(entry_id=2, hours=1.5),
            _mock_time_entry(entry_id=3, hours=3.0),
        ]

        result = await import_time_entries(
            [
                {"hours": 2.0, "issue_id": 123, "comments": "Fix 1"},
                {"hours": 1.5, "project_id": "web", "activity_id": 9},
                {"hours": 3.0, "issue_id": 456, "user_id": 7},
            ]
        )

        assert result["total"] == 3
        assert result["succeeded"] == 3
        assert result["failed"] == 0
        assert len(result["created"]) == 3
        assert result["errors"] == []
        assert mock_redmine.time_entry.create.call_count == 3

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_bulk_import_partial_failure(self, mock_redmine):
        """One entry fails; by default we continue past errors."""
        from redminelib.exceptions import ValidationError

        mock_redmine.time_entry.create.side_effect = [
            _mock_time_entry(entry_id=1),
            ValidationError("Activity is invalid"),
            _mock_time_entry(entry_id=3),
        ]

        result = await import_time_entries(
            [
                {"hours": 1.0, "issue_id": 1},
                {"hours": 2.0, "issue_id": 2, "activity_id": 999},
                {"hours": 3.0, "issue_id": 3},
            ]
        )

        assert result["total"] == 3
        assert result["succeeded"] == 2
        assert result["failed"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["index"] == 1
        assert "Activity" in result["errors"][0]["error"]
        # Third entry still attempted
        assert mock_redmine.time_entry.create.call_count == 3

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_stop_on_error(self, mock_redmine):
        """stop_on_error=True aborts at first failure."""
        from redminelib.exceptions import ValidationError

        mock_redmine.time_entry.create.side_effect = [
            _mock_time_entry(entry_id=1),
            ValidationError("Bad"),
            _mock_time_entry(entry_id=3),
        ]

        result = await import_time_entries(
            [
                {"hours": 1.0, "issue_id": 1},
                {"hours": 2.0, "issue_id": 2},
                {"hours": 3.0, "issue_id": 3},
            ],
            stop_on_error=True,
        )

        assert result["total"] == 3
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        # Third entry NOT attempted
        assert mock_redmine.time_entry.create.call_count == 2

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_accepts_json_string(self, mock_redmine):
        mock_redmine.time_entry.create.return_value = _mock_time_entry()

        result = await import_time_entries('[{"hours": 1.0, "issue_id": 123}]')

        assert result["total"] == 1
        assert result["succeeded"] == 1

    @pytest.mark.asyncio
    async def test_invalid_json_string(self):
        result = await import_time_entries("not-json")
        assert "error" in result
        assert "Invalid entries payload" in result["error"]

    @pytest.mark.asyncio
    async def test_non_list_input(self):
        result = await import_time_entries({"hours": 1.0})
        assert "error" in result
        assert "list" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await import_time_entries([])
        assert result == {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "created": [],
            "errors": [],
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_per_entry_missing_hours(self, mock_redmine):
        result = await import_time_entries(
            [
                {"issue_id": 123},  # missing hours
                {"hours": 1.0, "issue_id": 456},
            ]
        )

        assert result["total"] == 2
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert result["errors"][0]["index"] == 0
        assert "hours" in result["errors"][0]["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_per_entry_negative_hours(self, mock_redmine):
        result = await import_time_entries(
            [
                {"hours": -1.0, "issue_id": 123},
            ]
        )
        assert result["failed"] == 1
        assert "positive" in result["errors"][0]["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_per_entry_missing_target(self, mock_redmine):
        result = await import_time_entries(
            [
                {"hours": 1.0},  # no project_id or issue_id
            ]
        )
        assert result["failed"] == 1
        assert "project_id or issue_id" in result["errors"][0]["error"]

    @pytest.mark.asyncio
    async def test_non_dict_entry(self):
        result = await import_time_entries(
            [
                "not a dict",
                {"hours": 1.0, "issue_id": 1},
            ]
        )
        # First entry fails validation, second is mocked-less so we check
        # only the dict-type validation error
        assert result["failed"] >= 1
        assert "not a dict" in result["errors"][0]["error"]

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await import_time_entries([{"hours": 1.0, "issue_id": 1}])
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_whitelist_filters_unknown_keys(self, mock_redmine):
        """Unknown keys in the entry are filtered out before create()."""
        mock_redmine.time_entry.create.return_value = _mock_time_entry()

        await import_time_entries(
            [
                {
                    "hours": 1.0,
                    "issue_id": 123,
                    "bogus_field": "should be filtered",
                    "another_bogus": 42,
                }
            ]
        )

        _, kwargs = mock_redmine.time_entry.create.call_args
        assert "bogus_field" not in kwargs
        assert "another_bogus" not in kwargs
        assert kwargs["hours"] == 1.0
        assert kwargs["issue_id"] == 123

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_user_id_passthrough(self, mock_redmine):
        """import_time_entries supports user_id for logging on behalf of others."""
        mock_redmine.time_entry.create.return_value = _mock_time_entry()

        await import_time_entries(
            [
                {"hours": 1.0, "issue_id": 123, "user_id": 7},
            ]
        )

        _, kwargs = mock_redmine.time_entry.create.call_args
        assert kwargs["user_id"] == 7
