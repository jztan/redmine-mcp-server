"""Tests for the email-effect table and the hint it produces (#401)."""

import sys
from types import SimpleNamespace

import pytest

from redmine_mcp_server._annotations import TOOL_KINDS, ToolKind
from redmine_mcp_server._decorators import ACTION_SPECS, ActionMode
from redmine_mcp_server._notifications import (
    HINT_PREFIX,
    MAIL_EFFECTS,
    MailEffect,
    mail_hint,
    with_mail_hint,
)
from redmine_mcp_server.extensions import REGISTERED_EXTENSIONS


@pytest.fixture(autouse=True)
def _full_surface(all_plugin_tools_visible):
    """Enumerating tests must see every plugin tool (see conftest)."""
    yield


def _extension_tool_names() -> set:
    """Tool names an out-of-tree extension merged into ``TOOL_KINDS``.

    Empty on a stock server and in this suite. An extension classifies its
    tools for annotations and scopes but not for mail, so the anti-drift
    assertions subtract them instead of demanding an entry this tree cannot
    write.
    """
    names: set = set()
    for spec in REGISTERED_EXTENSIONS:
        names |= set(spec.tool_kinds)
    return names


def _unclassified_write_tools(registered: set) -> set:
    """Built-in write tools among ``registered`` with no row in the table."""
    writes = {
        name
        for name in registered
        if TOOL_KINDS.get(name, ToolKind.READ) is not ToolKind.READ
    } - _extension_tool_names()
    return writes - set(MAIL_EFFECTS)


async def _registered_tools():
    """Enumerate tools exactly as the server does."""
    from redmine_mcp_server.server import mcp
    import redmine_mcp_server.tools  # noqa: F401  triggers registration
    import redmine_mcp_server.apps  # noqa: F401  triggers registration

    return await mcp.list_tools()


class TestMailTable:
    def test_notifying_tool_has_a_hint(self):
        assert mail_hint("update_redmine_issue") == (
            f"{HINT_PREFIX} every successful call makes Redmine email the "
            "people involved in the issue, also when nobody watches it. Put "
            "every change to one issue (fields, status, assignee, note) into "
            "one call: three calls send three emails. A subtask also mails "
            "its parent issue."
        )

    def test_silent_tool_has_no_hint(self):
        # manage_issue_note edits an existing journal entry, and Journal
        # notifies after_create_commit only.
        assert mail_hint("manage_issue_note") is None

    def test_unverified_tool_has_no_hint(self):
        assert MAIL_EFFECTS["manage_document"].effect is MailEffect.UNVERIFIED
        assert mail_hint("manage_document") is None

    def test_read_tool_and_unknown_tool_have_no_hint(self):
        assert mail_hint("list_redmine_issues") is None
        assert mail_hint("no_such_tool_exists") is None

    def test_event_that_ships_switched_off_has_no_hint(self):
        """Redmine's defaults notify for issues only."""
        for name in ("manage_redmine_wiki_page", "manage_redmine_news", "upload_file"):
            assert MAIL_EFFECTS[name].effect is MailEffect.OFF_BY_DEFAULT, name
            assert mail_hint(name) is None, name

    def test_hint_names_the_actions_that_mail(self):
        hint = mail_hint("manage_issue_relation")
        assert "a successful `create` or `delete` action" in hint
        # list reads, so it is not named.
        assert "`list`" not in hint

    def test_relation_hint_does_not_ask_for_a_bundle(self):
        """A relation is its own request, so "one call" is not on offer."""
        hint = mail_hint("manage_issue_relation")
        assert "into one call" not in hint
        assert "cannot be bundled" in hint
        # Creating an issue cannot carry its relations either.
        assert "Relations cannot go in this call" in mail_hint("create_redmine_issue")

    def test_issue_hints_warn_against_reading_the_watcher_list(self):
        """A member who gets mail "for any event" is mailed without watching."""
        for name in (
            "create_redmine_issue",
            "update_redmine_issue",
            "copy_issue",
            "manage_issue_relation",
            "create_checklist_item",
            "update_checklist_item",
        ):
            assert "also when nobody watches" in mail_hint(name), name

    def test_condition_is_named_where_the_mail_depends_on_one(self):
        for name in ("create_checklist_item", "update_checklist_item"):
            assert "RedmineUP Checklists setting" in mail_hint(name), name

    def test_deleting_a_subtask_mails_its_parent(self):
        assert mail_hint("delete_redmine_issue") == (
            f"{HINT_PREFIX} every successful call makes Redmine email the "
            "people involved in the parent issue, if the deleted issue is a "
            "subtask."
        )

    def test_reply_to_the_customer_is_one_sentence(self):
        assert mail_hint("send_helpdesk_email_reply") == (
            f"{HINT_PREFIX} every successful call makes Redmine email the "
            "ticket's customer."
        )

    def test_copy_hint_names_its_own_parameters(self):
        hint = mail_hint("copy_issue")
        assert "`field_overrides`" in hint and "`copy_subtasks`" in hint
        assert "status, assignee, note" not in hint

    def test_checklist_update_does_not_talk_about_adding(self):
        assert "adding five items" in mail_hint("create_checklist_item")
        assert "changing five items" in mail_hint("update_checklist_item")

    def test_no_hint_is_longer_than_a_few_sentences(self):
        """The hint rides in tools/list on every session, so it stays short."""
        for name in MAIL_EFFECTS:
            assert len(mail_hint(name) or "") <= 360, name

    @pytest.mark.asyncio
    async def test_listed_actions_exist_and_write(self):
        """An action renamed in its tool must not survive here unnoticed."""
        await _registered_tools()  # ACTION_SPECS fills at decoration time
        for name, spec in MAIL_EFFECTS.items():
            if spec.actions is None:
                continue
            assert name in ACTION_SPECS, name
            for action in spec.actions:
                assert action in ACTION_SPECS[name], f"{name}: {action}"
                assert (
                    ACTION_SPECS[name][action] is ActionMode.WRITE
                ), f"{name}: {action} is a read action"

    def test_table_size_and_effect_counts(self):
        own = {
            name: spec
            for name, spec in MAIL_EFFECTS.items()
            if name not in _extension_tool_names()
        }
        assert len(own) == 31
        counts = {effect: 0 for effect in MailEffect}
        for spec in own.values():
            counts[spec.effect] += 1
        assert counts[MailEffect.NOTIFIES] == 8
        assert counts[MailEffect.OFF_BY_DEFAULT] == 3
        assert counts[MailEffect.NONE] == 12
        assert counts[MailEffect.UNVERIFIED] == 8


class TestAntiDrift:
    @pytest.mark.asyncio
    async def test_every_write_tool_is_classified(self):
        """A new write tool must say whether it mails anyone."""
        registered = {tool.name for tool in await _registered_tools()}
        missing = _unclassified_write_tools(registered)
        assert not missing, f"write tools missing from MAIL_EFFECTS: {missing}"

    def test_extension_write_tool_needs_no_entry(self, monkeypatch):
        """A third-party module must not break the built-in check."""
        kinds = {"manage_widget": ToolKind.WRITE_DESTRUCTIVE}
        monkeypatch.setitem(TOOL_KINDS, "manage_widget", kinds["manage_widget"])
        this_module = sys.modules[__name__]
        monkeypatch.setattr(
            this_module,
            "REGISTERED_EXTENSIONS",
            [SimpleNamespace(tool_kinds=kinds)],
        )
        assert _unclassified_write_tools({"manage_widget"}) == set()
        # The same tool without an extension behind it is a real gap.
        monkeypatch.setattr(this_module, "REGISTERED_EXTENSIONS", [])
        assert _unclassified_write_tools({"manage_widget"}) == {"manage_widget"}

    @pytest.mark.asyncio
    async def test_no_stale_or_read_only_entries(self):
        registered = {tool.name for tool in await _registered_tools()}
        # cleanup_attachment_files registers only when
        # REDMINE_MCP_EXPOSE_ADMIN_TOOLS is truthy; it must still be mapped.
        conditional = {"cleanup_attachment_files"}
        stale = set(MAIL_EFFECTS) - registered - conditional
        assert not stale, f"stale MAIL_EFFECTS entries: {stale}"
        reads = {name for name in MAIL_EFFECTS if TOOL_KINDS.get(name) is ToolKind.READ}
        assert not reads, f"read tools in MAIL_EFFECTS: {reads}"


class TestRegisteredDescriptions:
    @pytest.mark.asyncio
    async def test_notifying_tools_carry_the_hint_once(self):
        tools = {tool.name: tool for tool in await _registered_tools()}
        for name, spec in MAIL_EFFECTS.items():
            if spec.effect is not MailEffect.NOTIFIES or name not in tools:
                continue
            description = tools[name].description or ""
            assert description.count(mail_hint(name)) == 1, name

    @pytest.mark.asyncio
    async def test_silent_tools_keep_their_description(self):
        tools = {tool.name: tool for tool in await _registered_tools()}
        for name in (
            "manage_issue_watcher",
            "manage_time_entry",
            "manage_redmine_wiki_page",
            "list_files",
        ):
            assert HINT_PREFIX not in (tools[name].description or ""), name

    @pytest.mark.asyncio
    async def test_hint_sits_after_the_summary_and_keeps_the_body(self):
        tools = {tool.name: tool for tool in await _registered_tools()}
        description = tools["update_redmine_issue"].description
        paragraphs = description.split("\n\n")
        assert paragraphs[0] == "Update an existing Redmine issue."
        assert paragraphs[1] == mail_hint("update_redmine_issue")
        # The rest of the description has to survive the insertion.
        assert "status_name" in description

    @pytest.mark.asyncio
    async def test_parameter_docs_stay_out_of_the_description(self):
        """FastMCP serves the docstring up to ``Args``; the hint keeps that."""
        tools = {tool.name: tool for tool in await _registered_tools()}
        for name, spec in MAIL_EFFECTS.items():
            if spec.effect is not MailEffect.NOTIFIES or name not in tools:
                continue
            assert "Args:" not in tools[name].description, name

    @pytest.mark.asyncio
    async def test_registered_tool_is_not_mutated(self):
        from redmine_mcp_server.server import mcp

        await _registered_tools()
        registered = await mcp.get_tool("update_redmine_issue")
        assert HINT_PREFIX not in (registered.description or "")

    def test_middleware_is_registered_in_every_mode(self):
        from fastmcp import FastMCP

        from redmine_mcp_server.server import _register_middlewares

        for provider in (None, object()):
            instance = FastMCP("wiring")
            _register_middlewares(instance, auth_provider=provider)
            names = [type(middleware).__name__ for middleware in instance.middleware]
            assert "MailHintMiddleware" in names
            # The hint has to be in place before the formatting block is added.
            assert names.index("MailHintMiddleware") > names.index(
                "TextFormattingMiddleware"
            )


class TestWithMailHint:
    def test_leaves_a_tool_without_hint_alone(self):
        assert with_mail_hint("manage_issue_watcher", "Add a watcher.") == (
            "Add a watcher."
        )
        assert with_mail_hint("manage_issue_watcher", None) is None

    def test_hint_stands_alone_without_a_description(self):
        hint = mail_hint("update_redmine_issue")
        assert with_mail_hint("update_redmine_issue", None) == hint
        assert with_mail_hint("update_redmine_issue", "") == hint

    def test_appends_to_a_one_paragraph_description(self):
        result = with_mail_hint("update_redmine_issue", "Update an issue.")
        assert result == f"Update an issue.\n\n{mail_hint('update_redmine_issue')}"
