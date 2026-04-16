"""Unit tests for Stage A issue tracking tools.

Covers:
    - copy_issue
    - list_issue_relations / create_issue_relation / delete_issue_relation
    - list_subtasks
    - edit_note / get_private_notes / set_note_private
    - add_watcher / remove_watcher
    - list_issue_categories / create_issue_category /
      update_issue_category / delete_issue_category

Follows the project's mocking convention: patch the module-level
``redmine_mcp_server.redmine_handler.redmine`` attribute so that
``_get_redmine_client()`` returns the mock synchronously.
"""

import os
import sys

import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _issue_category_to_dict,
    _issue_relation_to_dict,
    _journal_to_dict,
    add_watcher,
    copy_issue,
    create_issue_category,
    create_issue_relation,
    delete_issue_category,
    delete_issue_relation,
    edit_note,
    get_private_notes,
    list_issue_categories,
    list_issue_relations,
    list_subtasks,
    remove_watcher,
    set_note_private,
    update_issue_category,
)


def _mock_with_name(id_val, name_val):
    """Create a Mock with explicit id and name attributes."""
    m = Mock()
    m.id = id_val
    m.name = name_val
    return m


def _mock_minimal_issue(issue_id: int = 1, subject: str = "Test") -> Mock:
    """Create a minimal mock issue that can traverse _issue_to_dict."""
    issue = Mock()
    issue.id = issue_id
    issue.subject = subject
    issue.description = ""
    issue.project = None
    issue.status = None
    issue.priority = None
    issue.author = None
    issue.assigned_to = None
    issue.created_on = None
    issue.updated_on = None
    issue.journals = []
    issue.attachments = []
    return issue


# ---------------------------------------------------------------------------
# Helper conversion tests
# ---------------------------------------------------------------------------


class TestIssueRelationToDict:
    def test_full_relation(self):
        rel = Mock()
        rel.id = 42
        rel.issue_id = 1
        rel.issue_to_id = 2
        rel.relation_type = "blocks"
        rel.delay = 3
        assert _issue_relation_to_dict(rel) == {
            "id": 42,
            "issue_id": 1,
            "issue_to_id": 2,
            "relation_type": "blocks",
            "delay": 3,
        }

    def test_missing_delay(self):
        rel = Mock(spec=["id", "issue_id", "issue_to_id", "relation_type"])
        rel.id = 1
        rel.issue_id = 1
        rel.issue_to_id = 2
        rel.relation_type = "relates"
        result = _issue_relation_to_dict(rel)
        assert result["delay"] is None


class TestIssueCategoryToDict:
    def test_full_category(self):
        cat = Mock()
        cat.id = 5
        cat.name = "Bugs"
        cat.project = _mock_with_name(1, "MyProj")
        cat.assigned_to = _mock_with_name(10, "Alice")
        result = _issue_category_to_dict(cat)
        assert result["id"] == 5
        assert result["name"] == "Bugs"
        assert result["project"] == {"id": 1, "name": "MyProj"}
        assert result["assigned_to"] == {"id": 10, "name": "Alice"}

    def test_no_assignee(self):
        cat = Mock()
        cat.id = 6
        cat.name = "Features"
        cat.project = _mock_with_name(1, "MyProj")
        cat.assigned_to = None
        assert _issue_category_to_dict(cat)["assigned_to"] is None


class TestJournalToDict:
    def test_with_private_flag(self):
        j = Mock()
        j.id = 1
        j.user = _mock_with_name(5, "Bob")
        j.notes = "hello"
        j.created_on = None
        j.private_notes = True
        result = _journal_to_dict(j, include_private_flag=True)
        assert result["id"] == 1
        assert result["user"] == {"id": 5, "name": "Bob"}
        assert "hello" in result["notes"]
        assert result["private_notes"] is True

    def test_empty_notes(self):
        j = Mock()
        j.id = 2
        j.user = None
        j.notes = ""
        j.created_on = None
        j.private_notes = False
        result = _journal_to_dict(j, include_private_flag=True)
        assert result["notes"] == ""
        assert result["user"] is None


# ---------------------------------------------------------------------------
# copy_issue
# ---------------------------------------------------------------------------


class TestCopyIssue:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_basic_copy(self, mock_redmine):
        new_issue = _mock_minimal_issue(issue_id=200, subject="Copy")
        mock_redmine.issue.copy.return_value = new_issue

        result = await copy_issue(issue_id=100)

        assert result["id"] == 200
        mock_redmine.issue.copy.assert_called_once()
        _, kwargs = mock_redmine.issue.copy.call_args
        assert mock_redmine.issue.copy.call_args.args[0] == 100
        assert kwargs["link_original"] is True
        assert kwargs["include"] == ("subtasks", "attachments")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_copy_with_subject_and_project_override(self, mock_redmine):
        new_issue = _mock_minimal_issue(issue_id=201, subject="New")
        mock_redmine.issue.copy.return_value = new_issue

        result = await copy_issue(
            issue_id=100,
            project_id="other-proj",
            subject="New Subject",
            link_original=False,
            copy_subtasks=False,
            copy_attachments=False,
        )

        assert result["id"] == 201
        _, kwargs = mock_redmine.issue.copy.call_args
        assert kwargs["link_original"] is False
        # When both copy_* flags are False, we pass a sentinel tuple to
        # prevent python-redmine's `include or (...)` fallback from
        # silently copying subtasks+attachments. The sentinel MUST be
        # truthy and MUST not contain "subtasks" or "attachments".
        assert kwargs["include"]  # truthy
        assert "subtasks" not in kwargs["include"]
        assert "attachments" not in kwargs["include"]
        assert kwargs["project_id"] == "other-proj"
        assert kwargs["subject"] == "New Subject"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_field_overrides_dict(self, mock_redmine):
        new_issue = _mock_minimal_issue(issue_id=202)
        mock_redmine.issue.copy.return_value = new_issue

        await copy_issue(
            issue_id=100,
            field_overrides={"assigned_to_id": 7, "description": "redirect"},
        )

        _, kwargs = mock_redmine.issue.copy.call_args
        assert kwargs["assigned_to_id"] == 7
        assert kwargs["description"] == "redirect"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_field_overrides_json_string(self, mock_redmine):
        new_issue = _mock_minimal_issue(issue_id=203)
        mock_redmine.issue.copy.return_value = new_issue

        await copy_issue(
            issue_id=100,
            field_overrides='{"priority_id": 3}',
        )

        _, kwargs = mock_redmine.issue.copy.call_args
        assert kwargs["priority_id"] == 3

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_invalid_field_overrides(self, mock_redmine):
        result = await copy_issue(issue_id=100, field_overrides="not-json")
        assert "error" in result
        mock_redmine.issue.copy.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await copy_issue(issue_id=100)
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_copy_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue.copy.side_effect = ResourceNotFoundError()
        result = await copy_issue(issue_id=999)
        assert "error" in result


# ---------------------------------------------------------------------------
# Issue relations
# ---------------------------------------------------------------------------


class TestListIssueRelations:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_returns_relations(self, mock_redmine):
        rel = Mock()
        rel.id = 5
        rel.issue_id = 1
        rel.issue_to_id = 2
        rel.relation_type = "blocks"
        rel.delay = None
        mock_redmine.issue_relation.filter.return_value = [rel]

        result = await list_issue_relations(issue_id=1)

        assert len(result) == 1
        assert result[0]["id"] == 5
        assert result[0]["relation_type"] == "blocks"
        mock_redmine.issue_relation.filter.assert_called_once_with(issue_id=1)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_empty(self, mock_redmine):
        mock_redmine.issue_relation.filter.return_value = []
        result = await list_issue_relations(issue_id=1)
        assert result == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.issue_relation.filter.side_effect = ForbiddenError()
        result = await list_issue_relations(issue_id=1)
        assert isinstance(result, dict)
        assert "error" in result


class TestCreateIssueRelation:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_basic(self, mock_redmine):
        rel = Mock()
        rel.id = 99
        rel.issue_id = 1
        rel.issue_to_id = 2
        rel.relation_type = "relates"
        rel.delay = None
        mock_redmine.issue_relation.create.return_value = rel

        result = await create_issue_relation(issue_id=1, issue_to_id=2)

        assert result["id"] == 99
        mock_redmine.issue_relation.create.assert_called_once_with(
            issue_id=1, issue_to_id=2, relation_type="relates"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_with_delay_for_precedes(self, mock_redmine):
        rel = Mock()
        rel.id = 100
        rel.issue_id = 1
        rel.issue_to_id = 2
        rel.relation_type = "precedes"
        rel.delay = 5
        mock_redmine.issue_relation.create.return_value = rel

        result = await create_issue_relation(
            issue_id=1,
            issue_to_id=2,
            relation_type="precedes",
            delay=5,
        )

        assert result["delay"] == 5
        mock_redmine.issue_relation.create.assert_called_once_with(
            issue_id=1, issue_to_id=2, relation_type="precedes", delay=5
        )

    @pytest.mark.asyncio
    async def test_invalid_relation_type(self):
        result = await create_issue_relation(
            issue_id=1, issue_to_id=2, relation_type="bogus"
        )
        assert "error" in result
        assert "Invalid relation_type" in result["error"]

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await create_issue_relation(issue_id=1, issue_to_id=2)
        assert "error" in result
        assert "read-only" in result["error"].lower()


class TestDeleteIssueRelation:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_success(self, mock_redmine):
        mock_redmine.issue_relation.delete.return_value = True
        result = await delete_issue_relation(relation_id=42)
        assert result == {"success": True, "deleted_relation_id": 42}
        mock_redmine.issue_relation.delete.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await delete_issue_relation(relation_id=42)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue_relation.delete.side_effect = ResourceNotFoundError()
        result = await delete_issue_relation(relation_id=999)
        assert "error" in result


# ---------------------------------------------------------------------------
# list_subtasks
# ---------------------------------------------------------------------------


class TestListSubtasks:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_children(self, mock_redmine):
        child1 = _mock_minimal_issue(issue_id=10, subject="Sub 1")
        child2 = _mock_minimal_issue(issue_id=11, subject="Sub 2")
        mock_redmine.issue.filter.return_value = [child1, child2]

        result = await list_subtasks(issue_id=1)

        assert len(result) == 2
        assert result[0]["id"] == 10
        assert result[1]["id"] == 11
        mock_redmine.issue.filter.assert_called_once_with(parent_id=1, status_id="*")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_no_subtasks(self, mock_redmine):
        mock_redmine.issue.filter.return_value = []
        result = await list_subtasks(issue_id=1)
        assert result == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_parent_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue.filter.side_effect = ResourceNotFoundError()
        result = await list_subtasks(issue_id=999)
        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# Watchers
# ---------------------------------------------------------------------------


class TestWatchers:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_add_watcher(self, mock_redmine):
        issue_mock = Mock()
        mock_redmine.issue.get.return_value = issue_mock

        result = await add_watcher(issue_id=1, user_id=5)

        assert result["success"] is True
        assert result["issue_id"] == 1
        assert result["user_id"] == 5
        mock_redmine.issue.get.assert_called_once_with(1)
        issue_mock.watcher.add.assert_called_once_with(5)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_remove_watcher(self, mock_redmine):
        issue_mock = Mock()
        mock_redmine.issue.get.return_value = issue_mock

        result = await remove_watcher(issue_id=1, user_id=5)

        assert result["success"] is True
        issue_mock.watcher.remove.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_add_watcher_read_only(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await add_watcher(issue_id=1, user_id=5)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_remove_watcher_read_only(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await remove_watcher(issue_id=1, user_id=5)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_add_watcher_issue_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue.get.side_effect = ResourceNotFoundError()
        result = await add_watcher(issue_id=999, user_id=5)
        assert "error" in result


# ---------------------------------------------------------------------------
# Notes / Journals
# ---------------------------------------------------------------------------


class TestEditNote:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_edit_note_basic(self, mock_redmine):
        mock_redmine.issue_journal.update.return_value = True

        result = await edit_note(journal_id=10, notes="Updated text")

        assert result["success"] is True
        assert result["journal_id"] == 10
        mock_redmine.issue_journal.update.assert_called_once_with(
            10, notes="Updated text"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_edit_note_with_private_flag(self, mock_redmine):
        mock_redmine.issue_journal.update.return_value = True

        await edit_note(journal_id=10, notes="Secret", private_notes=True)

        mock_redmine.issue_journal.update.assert_called_once_with(
            10, notes="Secret", private_notes=True
        )

    @pytest.mark.asyncio
    async def test_edit_note_read_only(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await edit_note(journal_id=10, notes="x")
        assert "error" in result


class TestGetPrivateNotes:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_filters_private_notes(self, mock_redmine):
        j1 = Mock()
        j1.id = 1
        j1.user = _mock_with_name(5, "Alice")
        j1.notes = "public note"
        j1.created_on = None
        j1.private_notes = False

        j2 = Mock()
        j2.id = 2
        j2.user = _mock_with_name(5, "Alice")
        j2.notes = "secret note"
        j2.created_on = None
        j2.private_notes = True

        issue = Mock()
        issue.journals = [j1, j2]
        mock_redmine.issue.get.return_value = issue

        result = await get_private_notes(issue_id=1)

        assert len(result) == 1
        assert result[0]["id"] == 2
        assert result[0]["private_notes"] is True
        mock_redmine.issue.get.assert_called_once_with(1, include="journals")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_skips_empty_private_notes(self, mock_redmine):
        j = Mock()
        j.id = 3
        j.user = None
        j.notes = ""  # empty body -> skip
        j.created_on = None
        j.private_notes = True

        issue = Mock()
        issue.journals = [j]
        mock_redmine.issue.get.return_value = issue

        result = await get_private_notes(issue_id=1)
        assert result == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_no_journals(self, mock_redmine):
        issue = Mock()
        issue.journals = None
        mock_redmine.issue.get.return_value = issue
        result = await get_private_notes(issue_id=1)
        assert result == []


class TestSetNotePrivate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_toggle_private_true(self, mock_redmine):
        mock_redmine.issue_journal.update.return_value = True

        result = await set_note_private(journal_id=10, is_private=True)

        assert result["success"] is True
        assert result["private_notes"] is True
        mock_redmine.issue_journal.update.assert_called_once_with(
            10, private_notes=True
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_toggle_private_false(self, mock_redmine):
        mock_redmine.issue_journal.update.return_value = True
        await set_note_private(journal_id=10, is_private=False)
        mock_redmine.issue_journal.update.assert_called_once_with(
            10, private_notes=False
        )

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await set_note_private(journal_id=10, is_private=True)
        assert "error" in result


# ---------------------------------------------------------------------------
# Issue categories
# ---------------------------------------------------------------------------


class TestListIssueCategories:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_categories(self, mock_redmine):
        cat = Mock()
        cat.id = 1
        cat.name = "Bugs"
        cat.project = _mock_with_name(10, "Proj")
        cat.assigned_to = None
        mock_redmine.issue_category.filter.return_value = [cat]

        result = await list_issue_categories(project_id=10)

        assert len(result) == 1
        assert result[0]["name"] == "Bugs"
        mock_redmine.issue_category.filter.assert_called_once_with(project_id=10)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_by_identifier(self, mock_redmine):
        mock_redmine.issue_category.filter.return_value = []
        result = await list_issue_categories(project_id="my-project")
        assert result == []
        mock_redmine.issue_category.filter.assert_called_once_with(
            project_id="my-project"
        )


class TestCreateIssueCategory:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_basic(self, mock_redmine):
        cat = Mock()
        cat.id = 7
        cat.name = "New Cat"
        cat.project = _mock_with_name(10, "Proj")
        cat.assigned_to = None
        mock_redmine.issue_category.create.return_value = cat

        result = await create_issue_category(project_id=10, name="New Cat")

        assert result["id"] == 7
        mock_redmine.issue_category.create.assert_called_once_with(
            project_id=10, name="New Cat"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_with_assignee(self, mock_redmine):
        cat = Mock()
        cat.id = 8
        cat.name = "Support"
        cat.project = _mock_with_name(10, "Proj")
        cat.assigned_to = _mock_with_name(3, "Bob")
        mock_redmine.issue_category.create.return_value = cat

        result = await create_issue_category(
            project_id=10, name="Support", assigned_to_id=3
        )

        assert result["assigned_to"] == {"id": 3, "name": "Bob"}
        mock_redmine.issue_category.create.assert_called_once_with(
            project_id=10, name="Support", assigned_to_id=3
        )

    @pytest.mark.asyncio
    async def test_create_empty_name(self):
        result = await create_issue_category(project_id=10, name="   ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await create_issue_category(project_id=10, name="Test")
        assert "error" in result


class TestUpdateIssueCategory:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_name(self, mock_redmine):
        updated = Mock()
        updated.id = 1
        updated.name = "Renamed"
        updated.project = _mock_with_name(10, "Proj")
        updated.assigned_to = None
        mock_redmine.issue_category.get.return_value = updated

        result = await update_issue_category(category_id=1, name="Renamed")

        assert result["name"] == "Renamed"
        mock_redmine.issue_category.update.assert_called_once_with(1, name="Renamed")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_update_assignee(self, mock_redmine):
        updated = Mock()
        updated.id = 1
        updated.name = "Cat"
        updated.project = _mock_with_name(10, "Proj")
        updated.assigned_to = _mock_with_name(9, "Carol")
        mock_redmine.issue_category.get.return_value = updated

        result = await update_issue_category(category_id=1, assigned_to_id=9)

        assert result["assigned_to"] == {"id": 9, "name": "Carol"}
        mock_redmine.issue_category.update.assert_called_once_with(1, assigned_to_id=9)

    @pytest.mark.asyncio
    async def test_update_no_fields(self):
        result = await update_issue_category(category_id=1)
        assert "error" in result
        assert "No fields" in result["error"]

    @pytest.mark.asyncio
    async def test_update_empty_name(self):
        result = await update_issue_category(category_id=1, name="   ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await update_issue_category(category_id=1, name="x")
        assert "error" in result


class TestDeleteIssueCategory:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_basic(self, mock_redmine):
        mock_redmine.issue_category.delete.return_value = True
        result = await delete_issue_category(category_id=5)
        assert result["success"] is True
        assert result["deleted_category_id"] == 5
        mock_redmine.issue_category.delete.assert_called_once_with(5)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_with_reassign(self, mock_redmine):
        mock_redmine.issue_category.delete.return_value = True
        result = await delete_issue_category(category_id=5, reassign_to_id=7)
        assert result["reassigned_to_id"] == 7
        mock_redmine.issue_category.delete.assert_called_once_with(5, reassign_to_id=7)

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await delete_issue_category(category_id=5)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.issue_category.delete.side_effect = ResourceNotFoundError()
        result = await delete_issue_category(category_id=999)
        assert "error" in result
