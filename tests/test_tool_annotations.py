"""Tests for MCP ToolAnnotations classification (#204)."""

import pytest

from redmine_mcp_server._annotations import (
    TOOL_KINDS,
    ToolKind,
    annotations_for,
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
