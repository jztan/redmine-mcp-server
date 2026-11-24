"""Tests for the notification budget warning (#469)."""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from unittest.mock import Mock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from redmine_mcp_server import _caller, _client, _notification_budget
from redmine_mcp_server._env import get_notification_budget
from redmine_mcp_server._notification_budget import (
    MAX_ISSUES_IN_NOTE,
    NOTE_KEY,
    NotificationBudgetMiddleware,
)
from redmine_mcp_server._notifications import notification_count


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _probe_server(budget=3, window_minutes=30, clock=None) -> FastMCP:
    """A server with stand-ins that take what the real tools take."""
    probe = FastMCP("probe")
    probe.add_middleware(
        NotificationBudgetMiddleware(budget, window_minutes, clock or _Clock())
    )

    @probe.tool()
    def update_redmine_issue(
        issue_id: int,
        fields: Optional[Union[Dict[str, Any], str]] = None,
        fail: bool = False,
    ) -> Dict[str, Any]:
        if fail:
            return {"error": "Not found.", "code": "NOT_FOUND"}
        return {"id": issue_id}

    @probe.tool()
    def create_redmine_issue(
        fields: Optional[Union[Dict[str, Any], str]] = None,
    ) -> Dict[str, Any]:
        return {"id": 500}

    @probe.tool()
    def copy_issue(issue_id: int) -> Dict[str, Any]:
        return {"id": 600, "copied_from": issue_id}

    @probe.tool()
    def manage_issue_relation(
        action: str, issue_id: int, issue_to_id: Optional[int] = None
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        return [] if action == "list" else {"id": 77, "issue_id": issue_id}

    @probe.tool()
    def create_checklist_item(issue_id: int) -> ToolResult:
        # A result whose text is not the JSON of its structured content.
        return ToolResult(
            content=[TextContent(type="text", text="Item added.")],
            structured_content={"id": 9},
        )

    @probe.tool()
    def manage_issue_watcher(issue_id: int) -> Dict[str, Any]:
        return {"id": issue_id}

    @probe.tool()
    def list_redmine_issues() -> Dict[str, Any]:
        return {"issues": []}

    return probe


def _note(result) -> Optional[str]:
    """The note in a result's structured content, wrapped or not."""
    structured = result.structured_content or {}
    inner = structured.get("result")
    if isinstance(inner, dict) and NOTE_KEY in inner:
        return inner[NOTE_KEY]
    return structured.get(NOTE_KEY)


async def _update(client, issue_id, **extra):
    return await client.call_tool(
        "update_redmine_issue", {"issue_id": issue_id, **extra}
    )


def _call_as(monkeypatch, caller):
    """Name the caller from ``caller["name"]``, without an auth mode."""

    async def owner():
        return caller["name"]

    monkeypatch.setattr(_notification_budget, "resolve_staged_upload_owner", owner)


def _oauth_token(subject=None):
    """A verified token. Doorkeeper sends no ``sub`` unless it is set up."""
    token = Mock()
    token.subject = subject
    token.claims = {}
    return token


class TestNotificationCount:
    def test_issue_write_counts_once(self):
        assert notification_count("update_redmine_issue", {"issue_id": 1}) == 1

    def test_relation_counts_for_both_issues(self):
        arguments = {"action": "create", "issue_id": 1, "issue_to_id": 2}
        assert notification_count("manage_issue_relation", arguments) == 2

    def test_read_action_of_a_manage_tool_counts_nothing(self):
        assert notification_count("manage_issue_relation", {"action": "list"}) == 0

    @pytest.mark.parametrize(
        "tool, arguments",
        [
            ("create_redmine_issue", {"fields": {"parent_issue_id": 7}}),
            ("create_redmine_issue", {"fields": '{"parent_issue_id": 7}'}),
            ("update_redmine_issue", {"issue_id": 3, "fields": {"parent_issue_id": 7}}),
            ("copy_issue", {"issue_id": 3, "field_overrides": {"parent_issue_id": 7}}),
        ],
    )
    def test_subtask_counts_once_more_for_its_parent(self, tool, arguments):
        assert notification_count(tool, arguments) == 2

    @pytest.mark.parametrize(
        "fields", [None, {}, {"parent_issue_id": None}, "", "not json", "[1]"]
    )
    def test_without_a_parent_it_counts_once(self, fields):
        assert notification_count("create_redmine_issue", {"fields": fields}) == 1

    def test_delete_is_not_counted(self):
        # The call does not say whether the issue was a subtask.
        assert notification_count("delete_redmine_issue", {"issue_id": 1}) == 0

    def test_tools_without_a_hint_count_nothing(self):
        for name in (
            "manage_issue_watcher",  # mails nobody
            "manage_redmine_wiki_page",  # off by default
            "manage_document",  # unverified
            "list_redmine_issues",  # read
            "no_such_tool_exists",
        ):
            assert notification_count(name, {"action": "create"}) == 0, name


class TestBudgetNote:
    async def test_no_note_below_the_budget(self):
        async with Client(_probe_server(budget=3)) as client:
            first = await _update(client, 1)
            second = await _update(client, 2)
        assert _note(first) is None and _note(second) is None
        assert first.structured_content == {"id": 1}

    async def test_note_from_the_budget_on(self):
        async with Client(_probe_server(budget=3)) as client:
            await _update(client, 1)
            await _update(client, 2)
            third = await _update(client, 3)
            fourth = await _update(client, 3)
        assert _note(third) == (
            "Email: 3 notifications may have been sent in the last 30 minutes, "
            "across 3 issues (#1, #2, #3). Check with the user before changing "
            "more."
        )
        assert "4 notifications" in _note(fourth)
        assert "across 3 issues" in _note(fourth)

    async def test_note_is_in_the_structured_result_and_in_its_text(self):
        """Clients differ in which of the two they hand to the model."""
        async with Client(_probe_server(budget=1)) as client:
            result = await _update(client, 8)
        assert result.is_error is False
        assert list(result.structured_content) == [NOTE_KEY, "id"]
        assert result.structured_content["id"] == 8
        assert len(result.content) == 1
        assert json.loads(result.content[0].text) == result.structured_content

    async def test_note_goes_under_result_for_a_wrapped_tool(self):
        async with Client(_probe_server(budget=2)) as client:
            result = await client.call_tool(
                "manage_issue_relation",
                {"action": "create", "issue_id": 4, "issue_to_id": 5},
            )
        assert list(result.structured_content) == ["result"]
        assert result.structured_content["result"]["id"] == 77
        note = _note(result)
        # A relation mails both issues; its own id is not an issue.
        assert "2 notifications" in note
        assert "(#4, #5)" in note

    async def test_note_is_one_more_text_block_when_the_text_is_not_json(self):
        async with Client(_probe_server(budget=1)) as client:
            result = await client.call_tool("create_checklist_item", {"issue_id": 3})
        assert [block.text for block in result.content] == [
            "Item added.",
            _note(result),
        ]
        assert result.structured_content["id"] == 9

    async def test_singular(self):
        async with Client(_probe_server(budget=1, window_minutes=1)) as client:
            result = await _update(client, 12)
        assert _note(result).startswith(
            "Email: 1 notification may have been sent in the last 1 minute, "
            "across 1 issue (#12)."
        )

    async def test_new_issue_is_named_from_the_result(self):
        async with Client(_probe_server(budget=1)) as client:
            created = await client.call_tool("create_redmine_issue", {})
            copied = await client.call_tool("copy_issue", {"issue_id": 5})
        assert "(#500)" in _note(created)
        # The copy mails, not the issue it was copied from.
        assert "(#500, #600)" in _note(copied)

    async def test_subtask_counts_and_names_its_parent(self):
        async with Client(_probe_server(budget=2)) as client:
            result = await client.call_tool(
                "create_redmine_issue", {"fields": {"parent_issue_id": 7}}
            )
        assert "2 notifications" in _note(result)
        assert "(#7, #500)" in _note(result)

    async def test_calls_that_do_not_mail_are_not_counted(self):
        async with Client(_probe_server(budget=1)) as client:
            listed = await client.call_tool("list_redmine_issues", {})
            watched = await client.call_tool("manage_issue_watcher", {"issue_id": 1})
            read = await client.call_tool(
                "manage_issue_relation", {"action": "list", "issue_id": 1}
            )
            first = await _update(client, 1)
        assert _note(listed) is _note(watched) is _note(read) is None
        assert "1 notification " in _note(first)

    async def test_failed_call_is_not_counted(self):
        async with Client(_probe_server(budget=1)) as client:
            failed = await _update(client, 1, fail=True)
            first = await _update(client, 2)
        assert _note(failed) is None
        assert "1 notification " in _note(first)
        assert "(#2)" in _note(first)

    async def test_calls_leave_the_window(self):
        clock = _Clock()
        async with Client(_probe_server(budget=2, clock=clock)) as client:
            await _update(client, 1)
            clock.now += 31 * 60
            second = await _update(client, 2)
            third = await _update(client, 3)
        assert _note(second) is None
        assert "2 notifications" in _note(third)
        assert "(#2, #3)" in _note(third)

    async def test_long_issue_list_is_cut(self):
        async with Client(_probe_server(budget=1)) as client:
            for issue_id in range(1, MAX_ISSUES_IN_NOTE + 3):
                result = await _update(client, issue_id)
        assert "across 12 issues" in _note(result)
        assert "#10 and 2 more)" in _note(result)
        assert "#11" not in _note(result)


class TestCallers:
    async def test_each_caller_has_its_own_count(self, monkeypatch):
        caller = {"name": "redmine-user:1"}
        _call_as(monkeypatch, caller)
        async with Client(_probe_server(budget=2)) as client:
            await _update(client, 1)
            caller["name"] = "redmine-user:2"
            other = await _update(client, 2)
            caller["name"] = "redmine-user:1"
            again = await _update(client, 3)
        assert _note(other) is None
        # The second caller's issue is not shown to the first one.
        assert "(#1, #3)" in _note(again)

    @pytest.mark.parametrize("mode", ["oauth", "oauth-proxy"])
    async def test_oauth_token_without_sub_is_counted_as_the_looked_up_user(self, mode):
        """The stock setup of the shared modes: Redmine is asked who it is,
        but only after a successful mailing call."""
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", mode),
            patch.object(_caller, "get_access_token", return_value=_oauth_token()),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.user.get.return_value.id = 5
            async with Client(_probe_server(budget=2)) as client:
                await client.call_tool("list_redmine_issues", {})
                await _update(client, 9, fail=True)
                lookups_before_a_mailing_call = mock_redmine.user.get.call_count
                first = await _update(client, 1)
                second = await _update(client, 2)
        assert lookups_before_a_mailing_call == 0
        assert _note(first) is None
        assert "(#1, #2)" in _note(second)
        assert mock_redmine.user.get.call_count == 2
        mock_redmine.user.get.assert_called_with("current")

    async def test_looked_up_users_do_not_share_a_count(self):
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", "oauth"),
            patch.object(_caller, "get_access_token", return_value=_oauth_token()),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.user.get.side_effect = [Mock(id=5), Mock(id=6), Mock(id=5)]
            async with Client(_probe_server(budget=2)) as client:
                await _update(client, 1)
                other = await _update(client, 2)
                again = await _update(client, 3)
        assert _note(other) is None
        # The second user's issue is not shown to the first one.
        assert "(#1, #3)" in _note(again)

    async def test_oauth_token_with_sub_is_counted_without_asking_redmine(self):
        token = _oauth_token(subject="5")
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", "oauth"),
            patch.object(_caller, "get_access_token", return_value=token),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            async with Client(_probe_server(budget=1)) as client:
                result = await _update(client, 1)
        assert "(#1)" in _note(result)
        mock_redmine.user.get.assert_not_called()

    async def test_failed_lookup_is_not_counted_and_logged_once(self, caplog):
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", "oauth"),
            patch.object(_caller, "get_access_token", return_value=_oauth_token()),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
            caplog.at_level(logging.WARNING, logger="redmine_mcp_server"),
        ):
            mock_redmine.user.get.side_effect = ConnectionError("down")
            async with Client(_probe_server(budget=1)) as client:
                first = await _update(client, 1)
                second = await _update(client, 2)
        assert _note(first) is None and _note(second) is None
        warnings = [r for r in caplog.records if "not counted" in r.getMessage()]
        assert len(warnings) == 1

    async def test_callers_out_of_the_window_are_forgotten(self, monkeypatch):
        clock = _Clock()
        caller = {"name": "redmine-user:1"}
        _call_as(monkeypatch, caller)
        probe = _probe_server(budget=5, clock=clock)
        middleware = probe.middleware[-1]
        async with Client(probe) as client:
            await _update(client, 1)
            clock.now += 31 * 60
            caller["name"] = "redmine-user:2"
            await _update(client, 2)
        assert list(middleware._sent) == ["redmine-user:2"]


class TestSetting:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_NOTIFY_BUDGET", raising=False)
        monkeypatch.delenv("REDMINE_MCP_NOTIFY_WINDOW_MIN", raising=False)
        assert get_notification_budget() == (0, 30)

    def test_reads_both_values(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_NOTIFY_BUDGET", " 10 ")
        monkeypatch.setenv("REDMINE_MCP_NOTIFY_WINDOW_MIN", "15")
        assert get_notification_budget() == (10, 15)

    @pytest.mark.parametrize(
        "name, value",
        [
            ("REDMINE_MCP_NOTIFY_BUDGET", "ten"),
            ("REDMINE_MCP_NOTIFY_BUDGET", "-1"),
            ("REDMINE_MCP_NOTIFY_WINDOW_MIN", "0"),
            ("REDMINE_MCP_NOTIFY_WINDOW_MIN", "1.5"),
        ],
    )
    def test_bad_value_is_refused(self, monkeypatch, name, value):
        monkeypatch.setenv(name, value)
        with pytest.raises(RuntimeError, match=name):
            get_notification_budget()

    def _registered(self):
        from redmine_mcp_server.server import _register_middlewares

        instance = FastMCP("wiring")
        _register_middlewares(instance, auth_provider=None)
        return [type(middleware).__name__ for middleware in instance.middleware]

    def test_middleware_is_not_registered_by_default(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_NOTIFY_BUDGET", raising=False)
        assert "NotificationBudgetMiddleware" not in self._registered()

    def test_middleware_is_registered_with_a_budget(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_NOTIFY_BUDGET", "10")
        assert "NotificationBudgetMiddleware" in self._registered()

    def test_bad_value_fails_registration(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_NOTIFY_BUDGET", "many")
        with pytest.raises(RuntimeError):
            self._registered()
