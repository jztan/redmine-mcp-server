"""Tests for MCP ToolAnnotations classification (#204)."""

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
