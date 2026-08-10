"""Tests for MCP ToolAnnotations classification (#204)."""

import pytest

from redmine_mcp_server._annotations import (
    TOOL_KINDS,
    ToolKind,
    annotations_for,
)
from redmine_mcp_server._decorators import ACTION_SPECS, ActionMode
from redmine_mcp_server.oauth_scopes import (
    READ_SCOPES,
    TOOL_SCOPES,
    WRITE_SCOPES,
)


class TestAnnotationsTable:
    def test_read_tool_is_read_only(self):
        ann = annotations_for("list_redmine_projects")
        assert ann.readOnlyHint is True
        assert ann.destructiveHint is False

    def test_additive_write_is_not_destructive(self):
        ann = annotations_for("create_redmine_issue")
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is False

    def test_destructive_write_omits_spec_defaults(self):
        # destructiveHint defaults to true and idempotentHint to false in the
        # MCP schema, so a destructive tool only needs readOnlyHint.
        ann = annotations_for("manage_redmine_wiki_page")
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is None
        assert ann.idempotentHint is None

    def test_idempotent_destructive_write(self):
        ann = annotations_for("delete_redmine_issue")
        assert ann.readOnlyHint is False
        assert ann.idempotentHint is True

    def test_unknown_tool_returns_none(self):
        assert annotations_for("no_such_tool_exists") is None

    def test_returns_independent_copies(self):
        # ToolAnnotations is a mutable pydantic model. Handing the same
        # instance to 31 tools would let one mutation leak across all of them.
        first = annotations_for("list_redmine_projects")
        first.readOnlyHint = False
        assert annotations_for("list_redmine_projects").readOnlyHint is True

    def test_table_size_and_kind_counts(self):
        assert len(TOOL_KINDS) == 52
        counts = {kind: 0 for kind in ToolKind}
        for kind in TOOL_KINDS.values():
            counts[kind] += 1
        assert counts[ToolKind.READ] == 31
        assert counts[ToolKind.WRITE_ADDITIVE] == 5
        assert counts[ToolKind.WRITE_DESTRUCTIVE] == 12
        assert counts[ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT] == 4


async def _registered_tools():
    """Enumerate tools exactly as the server does.

    Importing only ``tools`` sees 47 of the 51; ``apps`` registers 4 more.
    """
    from redmine_mcp_server.server import mcp
    import redmine_mcp_server.tools  # noqa: F401  triggers registration
    import redmine_mcp_server.apps  # noqa: F401  triggers registration

    return await mcp.list_tools()


class TestRegisteredToolAnnotations:
    @pytest.mark.asyncio
    async def test_every_registered_tool_is_classified(self):
        """Anti-drift: a new @mcp.tool() must get a TOOL_KINDS entry."""
        registered = {tool.name for tool in await _registered_tools()}
        classified = set(TOOL_KINDS)
        assert (
            registered <= classified
        ), f"tools missing from TOOL_KINDS: {registered - classified}"
        # cleanup_attachment_files registers only when
        # REDMINE_MCP_EXPOSE_ADMIN_TOOLS is truthy; it must still be mapped.
        conditional = {"cleanup_attachment_files"}
        stale = classified - registered - conditional
        assert not stale, f"stale TOOL_KINDS entries: {stale}"

    @pytest.mark.asyncio
    async def test_emitted_annotations_match_table(self):
        """The wire output must match the table, not merely exist.

        Table membership alone would not catch a tool registered under an
        explicit name= that never received its annotation.
        """
        for tool in await _registered_tools():
            expected = annotations_for(tool.name)
            assert expected is not None, f"{tool.name} is unclassified"
            assert tool.annotations is not None, f"{tool.name} has no annotations"
            assert tool.annotations.model_dump(
                exclude_none=True
            ) == expected.model_dump(exclude_none=True), tool.name

    @pytest.mark.asyncio
    async def test_read_tools_are_advertised_read_only(self):
        by_name = {tool.name: tool for tool in await _registered_tools()}
        assert by_name["list_redmine_projects"].annotations.readOnlyHint is True
        assert by_name["get_redmine_issue"].annotations.readOnlyHint is True
        assert by_name["search_entire_redmine"].annotations.readOnlyHint is True
        assert by_name["delete_redmine_issue"].annotations.readOnlyHint is False


# The 11 tools whose TOOL_SCOPES entry is empty. Scope membership cannot
# classify these, so each one is a reviewed, hand-made decision. Three of
# them mutate state despite looking exactly like the eight pure reads.
_EMPTY_SCOPE_KINDS = {
    "cleanup_attachment_files": ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT,
    "get_current_user": ToolKind.READ,
    "get_mcp_server_info": ToolKind.READ,
    "list_project_issue_custom_fields": ToolKind.READ,
    "list_redmine_issue_priorities": ToolKind.READ,
    "list_redmine_issue_statuses": ToolKind.READ,
    "list_redmine_roles": ToolKind.READ,
    "list_redmine_trackers": ToolKind.READ,
    "list_redmine_users": ToolKind.READ,
    "manage_contact": ToolKind.WRITE_DESTRUCTIVE,
    "manage_product": ToolKind.WRITE_DESTRUCTIVE,
}


def _required_scopes(entry) -> set:
    """Flatten a TOOL_SCOPES entry to the set of scopes it can demand."""
    if isinstance(entry, dict):
        required: set = set()
        for scopes in entry.values():
            required |= scopes
        return required
    return set(entry or ())


class TestClassificationCrossChecks:
    def test_write_scoped_tools_are_never_read_only(self):
        writes = set(WRITE_SCOPES)
        for name, entry in TOOL_SCOPES.items():
            if _required_scopes(entry) & writes:
                assert (
                    TOOL_KINDS[name] is not ToolKind.READ
                ), f"{name} needs a write scope but is classified READ"

    def test_read_scoped_tools_are_read_only(self):
        reads = set(READ_SCOPES)
        for name, entry in TOOL_SCOPES.items():
            required = _required_scopes(entry)
            if required and required <= reads:
                assert (
                    TOOL_KINDS[name] is ToolKind.READ
                ), f"{name} needs only read scopes but is not classified READ"

    def test_mixed_action_tools_are_not_read_only(self):
        for name, spec in ACTION_SPECS.items():
            # Skip test artifacts from other test modules that may pollute
            # ACTION_SPECS during test runs (e.g., dispatcher in test_decorators.py).
            if name not in TOOL_KINDS:
                continue
            if ActionMode.WRITE in spec.values():
                assert (
                    TOOL_KINDS[name] is not ToolKind.READ
                ), f"{name} has WRITE actions but is classified READ"

    def test_all_mixed_tools_are_covered(self):
        """Guard against a rename silently dropping cross-check coverage.

        contacts, products and documents route through a separate
        _manage_X_dispatch helper rather than stacking the decorator under
        @mcp.tool(), so they are the ones a naive lookup would miss.
        """
        expected = {
            "manage_contact",
            "manage_document",
            "manage_issue_category",
            "manage_issue_note",
            "manage_issue_relation",
            "manage_issue_watcher",
            "manage_product",
            "manage_project_member",
            "manage_redmine_version",
            "manage_redmine_wiki_page",
            "manage_time_entry",
        }
        assert expected <= set(ACTION_SPECS), (
            f"mixed tools missing from ACTION_SPECS: " f"{expected - set(ACTION_SPECS)}"
        )

    def test_empty_scope_tools_match_reviewed_map(self):
        actual = {
            name
            for name, entry in TOOL_SCOPES.items()
            if not isinstance(entry, dict) and not entry
        }
        assert actual == set(_EMPTY_SCOPE_KINDS), (
            "the set of empty-scope tools changed; each one needs a reviewed "
            "annotation decision"
        )
        for name, kind in _EMPTY_SCOPE_KINDS.items():
            assert TOOL_KINDS[name] is kind, name
