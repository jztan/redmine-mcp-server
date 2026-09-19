"""Issue attributes and query filters an out-of-tree extension registers.

#295 gave an extension a door for new tools. These two seams are for a
distribution that extends a resource the server already has, and both exist
because the alternative is silent:

- An update key the server does not know is taken for a custom field
  *label*, and labels are matched with every non-alphanumeric stripped. So
  an attribute named ``acme_sprint_id`` and a custom field called "Acme
  Sprint ID" normalize to one string, and the value goes wherever the
  lookup landed.
- A filter name the server does not know is refused, and rightly: Redmine
  drops an unregistered filter and answers 200 with the collection
  unnarrowed, which a caller cannot tell apart from a filter that matched
  everything. So the list has to be widened, not opened.

Both are read per call from the enabled extensions, so a family's flag
decides them the same way it decides its tools.
"""

import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastmcp import Client
from redminelib import Redmine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server import _client  # noqa: E402
from redmine_mcp_server import server as _server  # noqa: E402,F401
from redmine_mcp_server import tools  # noqa: E402,F401
from redmine_mcp_server._annotations import TOOL_KINDS, ToolKind  # noqa: E402
from redmine_mcp_server._custom_fields import (  # noqa: E402
    _is_standard_issue_update_key,
    _payload_has_named_candidates,
    _resolve_named_custom_fields,
)
from redmine_mcp_server._extension_registry import (  # noqa: E402
    REGISTERED_EXTENSIONS,
    extension_issue_query_filters,
    extension_issue_update_keys,
)
from redmine_mcp_server._plugin_visibility import PLUGIN_FLAGS  # noqa: E402
from redmine_mcp_server.extensions import (  # noqa: E402
    ExtensionSpec,
    register_extension,
)
from redmine_mcp_server.oauth_scopes import TOOL_SCOPES  # noqa: E402
from redmine_mcp_server.tools.issues import (  # noqa: E402
    _reject_issue_filters,
    create_redmine_issue,
    list_redmine_issues,
)

REDMINE_URL = "https://redmine.example.invalid"
FLAG = "REDMINE_ACME_ENABLED"


@pytest.fixture
def registry(monkeypatch):
    """Register specs and undo every table they touched afterwards.

    Registration merges into four module-level tables. The fixture yields a
    ``register(**fields)`` that fills in the parts every spec needs, so a
    test states only the seam it is about.
    """
    tables = (PLUGIN_FLAGS, TOOL_KINDS, TOOL_SCOPES)
    snapshots = [dict(table) for table in tables]
    registered_before = list(REGISTERED_EXTENSIONS)
    monkeypatch.setenv(FLAG, "true")
    counter = {"n": 0}

    def register(**fields):
        counter["n"] += 1
        family = fields.pop("family", f"acme{counter['n']}")
        tool = fields.pop("tool", f"manage_acme_{counter['n']}")
        spec = ExtensionSpec(
            family=family,
            enabled=fields.pop("enabled", lambda: os.environ.get(FLAG) == "true"),
            tool_kinds={tool: ToolKind.WRITE_DESTRUCTIVE},
            tool_scopes={tool: frozenset({"edit_issues"})},
            **fields,
        )
        register_extension(spec)
        return spec

    yield register

    REGISTERED_EXTENSIONS[:] = registered_before
    for table, snapshot in zip(tables, snapshots):
        table.clear()
        table.update(snapshot)


@pytest.fixture
def sent(monkeypatch):
    """The query parameters of each request the call issued."""
    calls: List[Dict[str, Any]] = []

    def record(method: str, url: str, **kwargs: Any) -> Any:
        calls.append(dict(kwargs.get("params") or {}))
        return {"issues": [], "total_count": 0}

    client = Redmine(REDMINE_URL, key="k")
    monkeypatch.setattr(client.engine, "request", record)
    monkeypatch.setattr(_client, "redmine", client)
    return calls


class TestSpecShape:
    def test_a_bare_string_of_update_keys_is_refused(self, registry):
        """A str is a sequence of its characters: this would declare five
        single-letter attributes."""
        with pytest.raises(RuntimeError, match="bare str as issue_update_keys"):
            registry(issue_update_keys="acme")

    def test_update_keys_have_to_be_names(self, registry):
        with pytest.raises(RuntimeError, match="issue_update_keys"):
            registry(issue_update_keys=("", "acme_sprint_id"))

    def test_query_filters_have_to_be_a_mapping(self, registry):
        with pytest.raises(RuntimeError, match="not a mapping"):
            registry(issue_query_filters=("acme_sprint_id",))

    def test_a_filters_value_has_to_be_a_mapping_of_parameters(self, registry):
        with pytest.raises(RuntimeError, match=r"issue_query_filters\['acme'\]"):
            registry(issue_query_filters={"acme": 1})

    def test_a_non_scalar_parameter_is_refused(self, registry):
        """It goes on the wire as a query parameter, so a list cannot."""
        with pytest.raises(RuntimeError, match="query parameter"):
            registry(issue_query_filters={"acme": {"set_filter": [1, 2]}})


class TestCollisions:
    def test_an_update_key_redmine_defines_is_refused(self, registry):
        with pytest.raises(RuntimeError, match="Redmine itself defines"):
            registry(issue_update_keys=("subject",))

    def test_a_filter_redmine_registers_is_refused(self, registry):
        with pytest.raises(RuntimeError, match="Redmine itself registers"):
            registry(issue_query_filters={"assigned_to_id": {}})

    def test_two_families_cannot_claim_one_attribute(self, registry):
        registry(issue_update_keys=("acme_sprint_id",))
        with pytest.raises(RuntimeError, match="already claimed by family"):
            registry(issue_update_keys=("acme_sprint_id",))

    def test_two_families_cannot_claim_one_filter(self, registry):
        registry(issue_query_filters={"acme_sprint_id": {}})
        with pytest.raises(RuntimeError, match="already claimed by family"):
            registry(issue_query_filters={"acme_sprint_id": {"set_filter": 1}})

    @pytest.mark.parametrize("key", ["fields", "f", "query_id"])
    def test_a_reserved_query_key_is_refused_as_a_parameter(self, registry, key):
        """Redmine reads those as the query's own filter definition and
        discards everything built from the rest of the request."""
        with pytest.raises(RuntimeError, match="discards every filter"):
            registry(issue_query_filters={"acme_sprint_id": {key: 1}})

    @pytest.mark.parametrize("key", ["limit", "offset", "sort", "include"])
    def test_a_parameter_the_tool_owns_is_refused(self, registry, key):
        with pytest.raises(RuntimeError, match="list_redmine_issues owns"):
            registry(issue_query_filters={"acme_sprint_id": {key: 1}})

    def test_a_companion_parameter_may_not_be_a_built_in_filter(self, registry):
        """It rides along unasked, so it would narrow every call that uses
        the filter -- and the caller never wrote it."""
        with pytest.raises(RuntimeError, match="itself a filter name"):
            registry(issue_query_filters={"acme_sprint_id": {"status_id": "open"}})

    def test_a_companion_parameter_may_not_be_the_specs_own_filter(self, registry):
        with pytest.raises(RuntimeError, match="itself a filter name"):
            registry(
                issue_query_filters={
                    "acme_sprint_id": {"acme_mode": 1},
                    "acme_mode": {},
                }
            )

    def test_a_companion_parameter_may_not_be_another_familys_filter(self, registry):
        registry(issue_query_filters={"acme_mode": {}})
        with pytest.raises(RuntimeError, match="itself a filter name"):
            registry(issue_query_filters={"acme_sprint_id": {"acme_mode": 1}})

    def test_a_rejected_spec_registers_nothing(self, registry):
        before = list(REGISTERED_EXTENSIONS)
        with pytest.raises(RuntimeError):
            registry(issue_update_keys=("subject",))
        assert REGISTERED_EXTENSIONS == before
        assert extension_issue_update_keys() == frozenset()


class TestTheFlagDecides:
    def test_entries_are_reported_while_the_family_is_enabled(self, registry):
        registry(
            issue_update_keys=("acme_sprint_id",),
            issue_query_filters={"acme_sprint_id": {"set_filter": 1}},
        )
        assert extension_issue_update_keys() == frozenset({"acme_sprint_id"})
        assert extension_issue_query_filters() == {"acme_sprint_id": {"set_filter": 1}}

    def test_a_disabled_family_contributes_nothing(self, registry, monkeypatch):
        registry(
            issue_update_keys=("acme_sprint_id",),
            issue_query_filters={"acme_sprint_id": {}},
        )
        monkeypatch.setenv(FLAG, "false")
        assert extension_issue_update_keys() == frozenset()
        assert extension_issue_query_filters() == {}

    def test_the_flag_is_read_per_call(self, registry, monkeypatch):
        """Not cached at registration: the tests flip it between calls, and
        so does an operator between restarts of the same image."""
        registry(issue_update_keys=("acme_sprint_id",))
        monkeypatch.setenv(FLAG, "false")
        assert extension_issue_update_keys() == frozenset()
        monkeypatch.setenv(FLAG, "true")
        assert extension_issue_update_keys() == frozenset({"acme_sprint_id"})

    def test_two_families_merge(self, registry):
        registry(issue_update_keys=("acme_sprint_id",))
        registry(issue_update_keys=("acme_story_points",))
        assert extension_issue_update_keys() == frozenset(
            {"acme_sprint_id", "acme_story_points"}
        )


class TestUpdateKeys:
    def test_an_unregistered_attribute_is_still_a_custom_field_name(self):
        assert not _is_standard_issue_update_key("acme_sprint_id")

    def test_a_registered_attribute_passes_through(self, registry):
        registry(issue_update_keys=("acme_sprint_id",))
        assert _is_standard_issue_update_key("acme_sprint_id")

    def test_a_registered_attribute_alone_needs_no_custom_field_lookup(self, registry):
        """The predicate also decides whether the project's custom fields are
        fetched at all, so registering removes a round-trip as well."""
        registry(issue_update_keys=("acme_sprint_id",))
        assert not _payload_has_named_candidates({"acme_sprint_id": 12})

    def test_the_label_collision_this_exists_for(self, registry):
        """A custom field named "Acme Sprint ID" normalizes to the same
        string as the attribute acme_sprint_id. Unregistered, the value is
        popped into custom_fields and the attribute never reaches Redmine.
        """

        class Field:
            id = 7
            name = "Acme Sprint ID"

        payload = _resolve_named_custom_fields({"acme_sprint_id": 12}, [Field()])
        assert payload == {"custom_fields": [{"id": 7, "value": 12}]}

        registry(issue_update_keys=("acme_sprint_id",))
        payload = _resolve_named_custom_fields({"acme_sprint_id": 12}, [Field()])
        assert payload == {"acme_sprint_id": 12}

    def test_a_real_custom_field_still_resolves_beside_a_registered_one(self, registry):
        class Field:
            id = 9
            name = "Severity"

        registry(issue_update_keys=("acme_sprint_id",))
        payload = _resolve_named_custom_fields(
            {"acme_sprint_id": 12, "Severity": "high"}, [Field()]
        )
        assert payload == {
            "acme_sprint_id": 12,
            "custom_fields": [{"id": 9, "value": "high"}],
        }


class TestCreatePath:
    """The predicate is shared with the create path, so a registered
    attribute reaches Redmine on a create as much as on an update."""

    @staticmethod
    def _issue_stub():
        return SimpleNamespace(
            id=42,
            project=SimpleNamespace(id=1, name="Test"),
            tracker=SimpleNamespace(id=1, name="Bug"),
            status=SimpleNamespace(id=1, name="New"),
            priority=SimpleNamespace(id=1, name="Normal"),
            author=SimpleNamespace(id=1, name="Test User"),
            subject="X",
            description="",
            created_on=None,
            updated_on=None,
            custom_fields=[],
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_registered_attribute_is_created_as_an_attribute(
        self, mock_redmine, registry
    ):
        registry(issue_update_keys=("acme_sprint_id",))
        mock_redmine.project.get.return_value = SimpleNamespace(
            issue_custom_fields=[SimpleNamespace(id=7, name="Acme Sprint ID")]
        )
        mock_redmine.issue.create.return_value = self._issue_stub()

        result = await create_redmine_issue(
            project_id=1, subject="X", fields={"acme_sprint_id": 12}
        )

        assert "error" not in result, result
        assert mock_redmine.issue.create.call_args.kwargs["acme_sprint_id"] == 12
        assert "custom_fields" not in mock_redmine.issue.create.call_args.kwargs
        # Nothing to rule out, so the project's custom fields are not fetched.
        mock_redmine.project.get.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_without_the_registration_the_custom_field_wins(self, mock_redmine):
        """The same collision the update path has, on create: the label
        "Acme Sprint ID" normalizes to the attribute's own name."""
        mock_redmine.project.get.return_value = SimpleNamespace(
            issue_custom_fields=[SimpleNamespace(id=7, name="Acme Sprint ID")]
        )
        mock_redmine.issue.create.return_value = self._issue_stub()

        result = await create_redmine_issue(
            project_id=1, subject="X", fields={"acme_sprint_id": 12}
        )

        assert "error" not in result, result
        kwargs = mock_redmine.issue.create.call_args.kwargs
        assert "acme_sprint_id" not in kwargs
        assert kwargs["custom_fields"] == [{"id": 7, "value": 12}]


class TestQueryFilters:
    def test_an_unregistered_filter_is_still_refused(self):
        assert _reject_issue_filters({"acme_sprint_id": 5})

    def test_a_registered_filter_is_accepted(self, registry):
        registry(issue_query_filters={"acme_sprint_id": {}})
        assert _reject_issue_filters({"acme_sprint_id": 5}) is None

    def test_a_disabled_family_refuses_it_again(self, registry, monkeypatch):
        registry(issue_query_filters={"acme_sprint_id": {}})
        monkeypatch.setenv(FLAG, "false")
        assert _reject_issue_filters({"acme_sprint_id": 5})

    def test_the_value_rules_still_apply(self, registry):
        """Registering a name says nothing about what may be sent under it."""
        registry(issue_query_filters={"acme_sprint_id": {}})
        assert _reject_issue_filters({"acme_sprint_id": {"nested": 1}})

    @pytest.mark.asyncio
    async def test_the_companion_parameter_rides_along(self, registry, sent):
        registry(issue_query_filters={"acme_sprint_id": {"set_filter": 1}})

        result = await list_redmine_issues(filters={"acme_sprint_id": 5})

        assert not isinstance(result, dict) or "error" not in result, result
        assert sent[0]["acme_sprint_id"] == 5
        assert sent[0]["set_filter"] == 1

    @pytest.mark.asyncio
    async def test_a_request_without_that_filter_is_unchanged(self, registry, sent):
        registry(issue_query_filters={"acme_sprint_id": {"set_filter": 1}})

        result = await list_redmine_issues(project_id="demo")

        assert not isinstance(result, dict) or "error" not in result, result
        assert "set_filter" not in sent[0]

    @pytest.mark.asyncio
    async def test_a_stock_server_sends_what_it_always_sent(self, sent):
        """No extension loaded: the request has to be the one it is today."""
        result = await list_redmine_issues(project_id="demo", status_id="open")

        assert not isinstance(result, dict) or "error" not in result, result
        assert set(sent[0]) == {"project_id", "status_id", "limit", "offset"}

    @pytest.mark.asyncio
    async def test_the_tool_boundary_accepts_a_registered_filter(self, registry, sent):
        """Through the MCP surface, not only the function: the filter travels
        as an argument a client sends.
        """
        registry(issue_query_filters={"acme_sprint_id": {"set_filter": 1}})

        async with Client(_server.mcp) as client:
            result = await client.call_tool(
                "list_redmine_issues", {"filters": {"acme_sprint_id": 5}}
            )

        assert not result.is_error, result
        assert sent[0]["set_filter"] == 1
