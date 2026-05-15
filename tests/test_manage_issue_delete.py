"""Tests for manage_issue(action="delete") (#120).

Issue deletion is irreversible and cascades to subtasks, journals,
attachments, time entries, and inbound relations. The tool gates the
delete behind explicit confirmation flags and surfaces an impact
preview when refused.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from redminelib.exceptions import ResourceNotFoundError

from redmine_mcp_server.tools.issues import manage_issue


def _make_issue(issue_id: int = 1, children=(), **extras) -> SimpleNamespace:
    return SimpleNamespace(
        id=issue_id,
        subject=extras.get("subject", "Test issue"),
        children=list(children),
        journals=extras.get("journals", []),
        attachments=extras.get("attachments", []),
        relations=extras.get("relations", []),
        time_entries=extras.get("time_entries", []),
    )


class TestConfirmationGate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_refuses_without_confirm_delete(self, mock_redmine):
        mock_redmine.issue.get.return_value = _make_issue(1)
        result = await manage_issue(action="delete", issue_id=1)

        assert result["code"] == "CONFIRMATION_REQUIRED"
        assert "irreversible" in result["hint"].lower()
        assert "confirm_delete=True" in result["hint"]
        # The impact preview is structured so a caller can show it.
        assert result["impact"]["issue_id"] == 1
        assert "children_count" in result["impact"]
        # And the API was NOT actually called.
        mock_redmine.issue.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_confirm_delete_proceeds(self, mock_redmine):
        mock_redmine.issue.get.return_value = _make_issue(1)
        mock_redmine.issue.delete.return_value = True

        result = await manage_issue(action="delete", issue_id=1, confirm_delete=True)

        assert result["success"] is True
        assert result["deleted_issue_id"] == 1
        assert "cascade_deleted" in result
        mock_redmine.issue.delete.assert_called_once_with(1)


class TestCascadeChildrenGate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_refuses_with_children_unless_double_confirmed(self, mock_redmine):
        # An issue with two subtasks must refuse even when confirm_delete
        # is True -- the cascade-delete of the subtasks needs its own
        # opt-in.
        mock_redmine.issue.get.return_value = _make_issue(
            1, children=[SimpleNamespace(id=2), SimpleNamespace(id=3)]
        )

        result = await manage_issue(action="delete", issue_id=1, confirm_delete=True)

        assert result["code"] == "CHILDREN_PRESENT"
        assert "2 subtask" in result["error"]
        assert "confirm_delete_with_children=True" in result["hint"]
        mock_redmine.issue.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_double_confirmed_with_children_proceeds(self, mock_redmine):
        mock_redmine.issue.get.return_value = _make_issue(
            1, children=[SimpleNamespace(id=2)]
        )
        mock_redmine.issue.delete.return_value = True

        result = await manage_issue(
            action="delete",
            issue_id=1,
            confirm_delete=True,
            confirm_delete_with_children=True,
        )

        assert result["success"] is True
        assert result["cascade_deleted"]["children_count"] == 1
        mock_redmine.issue.delete.assert_called_once_with(1)


class TestImpactPreview:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_preview_counts_all_cascade_categories(self, mock_redmine):
        mock_redmine.issue.get.return_value = _make_issue(
            42,
            children=[SimpleNamespace(id=1), SimpleNamespace(id=2)],
            journals=[SimpleNamespace(id=3), SimpleNamespace(id=4)],
            attachments=[SimpleNamespace(id=5)],
            relations=[SimpleNamespace(id=6)],
            time_entries=[
                SimpleNamespace(id=7),
                SimpleNamespace(id=8),
                SimpleNamespace(id=9),
            ],
        )

        result = await manage_issue(action="delete", issue_id=42)

        preview = result["impact"]
        assert preview["children_count"] == 2
        assert preview["journals_count"] == 2
        assert preview["attachments_count"] == 1
        assert preview["relations_count"] == 1
        assert preview["time_entries_count"] == 3


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_invalid_issue_id_returns_error(self):
        for bogus in (None, -1, 0, "abc", 1.5):
            result = await manage_issue(action="delete", issue_id=bogus)
            assert "error" in result
            assert "positive integer" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_not_found_returns_404_envelope(self, mock_redmine):
        mock_redmine.issue.get.side_effect = ResourceNotFoundError()
        result = await manage_issue(action="delete", issue_id=999)
        assert result["code"] == "NOT_FOUND"
        assert result["upstream_status"] == 404
        assert result["issue_id"] == 999

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_not_found_on_delete_call(self, mock_redmine):
        # Issue was visible at fetch time but gone by delete time --
        # surface the upstream 404 cleanly rather than crashing.
        mock_redmine.issue.get.return_value = _make_issue(1)
        mock_redmine.issue.delete.side_effect = ResourceNotFoundError()
        result = await manage_issue(action="delete", issue_id=1, confirm_delete=True)
        assert result["code"] == "NOT_FOUND"


class TestReadOnlyMode:
    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await manage_issue(action="delete", issue_id=1, confirm_delete=True)
        # The @action_dispatch decorator surfaces the standard
        # read-only envelope before the action handler runs.
        assert "error" in result
        assert "read-only" in result["error"].lower()
