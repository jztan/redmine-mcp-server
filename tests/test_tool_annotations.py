"""Tests for MCP ToolAnnotations classification (#204)."""

from types import SimpleNamespace

import pytest

import redmine_mcp_server._scope_middleware as scope_mw
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


@pytest.fixture(autouse=True)
def _full_surface(all_plugin_tools_visible):
    """Enumerating tests must see every plugin tool (see conftest)."""
    yield


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
        assert len(TOOL_KINDS) == 58
        counts = {kind: 0 for kind in ToolKind}
        for kind in TOOL_KINDS.values():
            counts[kind] += 1
        assert counts[ToolKind.READ] == 34
        assert counts[ToolKind.WRITE_ADDITIVE] == 5
        assert counts[ToolKind.WRITE_DESTRUCTIVE] == 15
        assert counts[ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT] == 4


async def _registered_tools():
    """Enumerate tools exactly as the server does.

    Importing only ``tools`` sees 48 of the 52; ``apps`` registers 4 more.
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


# The 12 tools whose TOOL_SCOPES entry is empty. Scope membership cannot
# classify these, so each one is a reviewed, hand-made decision. Four of
# them mutate state despite looking exactly like the eight pure reads.
_EMPTY_SCOPE_KINDS = {
    "cleanup_attachment_files": ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT,
    "get_current_user": ToolKind.READ,
    "get_mcp_server_info": ToolKind.READ,
    "list_redmine_issue_priorities": ToolKind.READ,
    "list_redmine_issue_statuses": ToolKind.READ,
    "list_redmine_roles": ToolKind.READ,
    "list_redmine_trackers": ToolKind.READ,
    "list_redmine_users": ToolKind.READ,
    "manage_contact": ToolKind.WRITE_DESTRUCTIVE,
    "list_contact_tags": ToolKind.READ,
    "manage_deal": ToolKind.WRITE_DESTRUCTIVE,
    "list_deal_statuses": ToolKind.READ,
    "manage_deal_category": ToolKind.WRITE_DESTRUCTIVE,
    "manage_crm_note": ToolKind.WRITE_DESTRUCTIVE,
    "list_crm_queries": ToolKind.READ,
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
            # A name missing from TOOL_KINDS can only be a synthetic
            # artifact from tests/test_decorators.py polluting the shared
            # ACTION_SPECS registry: test_every_registered_tool_is_classified
            # bounds every registered tool into TOOL_KINDS, and
            # test_all_mixed_tools_are_covered pins the 11 real mixed tools
            # into ACTION_SPECS, so no genuine mixed tool can reach this
            # branch.
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
            "mixed tools missing from ACTION_SPECS: " f"{expected - set(ACTION_SPECS)}"
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


class TestAnnotationInteractions:
    @pytest.mark.asyncio
    async def test_annotations_stable_in_read_only_mode(self, monkeypatch):
        """Classification describes the tool, not the deployment's policy.

        Flipping write tools to readOnlyHint=true when writes are disabled
        would be technically true but would corrupt an agent's planning: it
        would fold a "safe" create into a plan that can only ever error.

        Annotations are computed once at decoration time, inside
        ``_AnnotatingFastMCP.tool``, when a tool module is first imported.
        By the time this test runs, `redmine_mcp_server.tools` and `.apps`
        are already imported and cached in ``sys.modules``, so re-reading
        the already-registered tools after monkeypatching the environment
        would prove nothing: registration already happened and will not
        re-run. The only way to actually exercise the decoration-time
        decision under read-only mode is to set the env var first, then
        register a fresh probe tool on a brand new ``_AnnotatingFastMCP``
        instance, so the decorator runs while the env var is in effect.
        """
        from redmine_mcp_server.server import _AnnotatingFastMCP

        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        probe = _AnnotatingFastMCP("probe")

        @probe.tool()
        async def create_redmine_issue(project_id: int) -> dict:
            """Probe registered while read-only mode is active."""
            return {}

        registered = {t.name: t for t in await probe.list_tools()}
        annotations = registered["create_redmine_issue"].annotations
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is False

    @pytest.mark.asyncio
    async def test_explicit_annotations_none_is_honored_not_raised(self):
        """An explicit ``annotations=None`` must degrade safely, not raise.

        ``kwargs.get("annotations")`` treats an explicit ``None`` the same
        as an absent key, so it used to fall into the deferred branch and
        then pass ``annotations=`` a second time on top of the one already
        in ``**kwargs``, raising ``TypeError: got multiple values for
        keyword argument 'annotations'``. The guard must instead test for
        key presence so a caller's explicit override is delegated to
        ``super().tool(...)`` untouched.
        """
        from redmine_mcp_server.server import _AnnotatingFastMCP

        probe = _AnnotatingFastMCP("probe-explicit-none")

        @probe.tool(annotations=None)
        async def some_probe_tool() -> dict:
            """Probe registered with an explicit annotations=None."""
            return {}

        registered = {t.name: t for t in await probe.list_tools()}
        assert registered["some_probe_tool"].annotations is None

    @pytest.mark.asyncio
    async def test_scope_middleware_preserves_annotations(self):
        """The scope filter must not strip or rebuild annotations."""
        from redmine_mcp_server._scope_middleware import (
            ScopeEnforcementMiddleware,
        )

        tools = await _registered_tools()
        middleware = ScopeEnforcementMiddleware()

        async def call_next(_context):
            return tools

        # No access token in context: the middleware returns tools untouched.
        result = await middleware.on_list_tools(None, call_next)
        by_name = {tool.name: tool for tool in result}
        assert by_name["list_redmine_projects"].annotations.readOnlyHint is True
        assert by_name["delete_redmine_issue"].annotations.readOnlyHint is False

    @pytest.mark.asyncio
    async def test_scope_middleware_filters_and_preserves_annotations(
        self, monkeypatch
    ):
        """The filtering branch (a real token) must not touch annotations.

        Unlike the no-token test above, this exercises the loop in
        ``on_list_tools`` that actually walks and rebuilds the tool list,
        which is the code path that could plausibly drop or rebuild
        annotations. ``view_project`` grants ``list_redmine_projects`` but
        not ``delete_redmine_issue`` (which needs ``delete_issues``), so the
        token both admits a tool and filters one out.
        """
        from redmine_mcp_server._scope_middleware import (
            ScopeEnforcementMiddleware,
        )

        tools = await _registered_tools()
        middleware = ScopeEnforcementMiddleware()

        async def call_next(_context):
            return tools

        monkeypatch.setattr(
            scope_mw,
            "get_access_token",
            lambda: SimpleNamespace(token="t", scopes=["view_project"]),
        )

        result = await middleware.on_list_tools(None, call_next)
        by_name = {tool.name: tool for tool in result}

        # The filter actually ran: the unscoped tool was dropped.
        assert "delete_redmine_issue" not in by_name
        assert len(result) < len(tools)

        # The survivor kept its correct annotations, unmodified.
        assert "list_redmine_projects" in by_name
        assert by_name["list_redmine_projects"].annotations.readOnlyHint is True
        expected = annotations_for("list_redmine_projects")
        assert by_name["list_redmine_projects"].annotations.model_dump(
            exclude_none=True
        ) == expected.model_dump(exclude_none=True)
