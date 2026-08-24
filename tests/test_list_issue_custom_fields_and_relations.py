"""Tests for custom fields and relations in issue list output.

Redmine returns issue custom field values on ``GET /issues.json``
unconditionally (``render_api_custom_values`` in ``issues/index.api.rsb``) and
renders relations there under ``include=relations``. ``list_redmine_issues``
discarded both, so reading a custom field or a relation across a project cost
one request per issue.

Relations are read from the payload rather than through ``issue.relations``,
which is a lazy relation in python-redmine -- see
``_serialization._included_list``. The fakes here raise on that attribute so a
regression cannot pass.

See https://github.com/jztan/redmine-mcp-server/issues/228.
"""

import os
import sys
from unittest.mock import Mock, PropertyMock, patch

import pytest
from redminelib.exceptions import ForbiddenError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.issues import (  # noqa: E402
    list_redmine_issues,
    search_redmine_issues,
)

_CF = [{"id": 12, "name": "Size", "value": "S"}]
_REL = [
    {
        "id": 5,
        "issue_id": 1,
        "issue_to_id": 2,
        "relation_type": "precedes",
        "delay": 0,
    }
]


def _named(id, name):
    """A {id, name} reference.

    ``name`` is assigned rather than passed to the constructor: ``Mock(name=)``
    sets the mock's own name instead of an attribute.
    """
    ref = Mock(id=id)
    ref.name = name
    return ref


def _mock_issue(issue_id=1, custom_fields=None, relations=None):
    issue = Mock()
    issue.id = issue_id
    issue.subject = f"Issue {issue_id}"
    issue.description = ""
    issue.project = _named(1, "Test Project")
    issue.status = _named(1, "New")
    issue.priority = _named(2, "Normal")
    issue.author = _named(10, "Alice")
    issue.assigned_to = None
    issue.created_on = None
    issue.updated_on = None
    issue.custom_fields = list(custom_fields or [])
    issue.raw.return_value = {"relations": list(relations or [])}
    type(issue).relations = PropertyMock(side_effect=ForbiddenError)
    return issue


@pytest.fixture
def mock_redmine():
    with patch("redmine_mcp_server._client.redmine") as mock:
        yield mock


class TestIssueCustomFields:
    @pytest.mark.asyncio
    async def test_absent_by_default(self, mock_redmine):
        mock_redmine.issue.filter.return_value = [_mock_issue(custom_fields=_CF)]
        result = await list_redmine_issues(project_id=1)
        assert "custom_fields" not in result[0]

    @pytest.mark.asyncio
    async def test_included_on_request(self, mock_redmine):
        mock_redmine.issue.filter.return_value = [_mock_issue(custom_fields=_CF)]
        result = await list_redmine_issues(project_id=1, include_custom_fields=True)
        assert result[0]["custom_fields"] == _CF

    @pytest.mark.asyncio
    async def test_each_issue_gets_its_own_values(self, mock_redmine):
        """One page, one request, and the values are not shared between issues."""
        mock_redmine.issue.filter.return_value = [
            _mock_issue(n, custom_fields=[{"id": 12, "name": "Size", "value": f"S{n}"}])
            for n in (1, 2, 3)
        ]
        result = await list_redmine_issues(project_id=1, include_custom_fields=True)
        assert [i["custom_fields"][0]["value"] for i in result] == ["S1", "S2", "S3"]
        assert mock_redmine.issue.filter.call_count == 1

    @pytest.mark.asyncio
    async def test_selecting_the_field_name_is_enough(self, mock_redmine):
        """Naming it in `fields` used to be dropped silently."""
        mock_redmine.issue.filter.return_value = [_mock_issue(custom_fields=_CF)]
        result = await list_redmine_issues(project_id=1, fields=["id", "custom_fields"])
        assert result[0] == {"id": 1, "custom_fields": _CF}


class TestIssueRelations:
    @pytest.mark.asyncio
    async def test_absent_by_default_and_include_not_requested(self, mock_redmine):
        mock_redmine.issue.filter.return_value = [_mock_issue(relations=_REL)]
        result = await list_redmine_issues(project_id=1)
        assert "relations" not in result[0]
        assert "include" not in mock_redmine.issue.filter.call_args[1]

    @pytest.mark.asyncio
    async def test_included_on_request(self, mock_redmine):
        mock_redmine.issue.filter.return_value = [_mock_issue(relations=_REL)]
        result = await list_redmine_issues(project_id=1, include_relations=True)
        assert result[0]["relations"] == _REL
        assert mock_redmine.issue.filter.call_args[1]["include"] == "relations"

    @pytest.mark.asyncio
    async def test_one_request_for_a_whole_page(self, mock_redmine):
        """The N+1 this removes. The fakes raise on issue.relations, so a
        regression to the lazy attribute fails rather than slowing down."""
        mock_redmine.issue.filter.return_value = [
            _mock_issue(n, relations=_REL) for n in range(1, 11)
        ]
        result = await list_redmine_issues(project_id=1, include_relations=True)
        assert [len(i["relations"]) for i in result] == [1] * 10
        assert mock_redmine.issue.filter.call_count == 1

    @pytest.mark.asyncio
    async def test_selecting_the_field_name_requests_the_include(self, mock_redmine):
        """`fields` alone has to reach the request, or the key comes back
        empty and the caller cannot tell why."""
        mock_redmine.issue.filter.return_value = [_mock_issue(relations=_REL)]
        result = await list_redmine_issues(project_id=1, fields=["id", "relations"])
        assert result[0] == {"id": 1, "relations": _REL}
        assert "relations" in mock_redmine.issue.filter.call_args[1]["include"]

    @pytest.mark.parametrize(
        "supplied",
        [
            "attachments",
            " attachments ",
            ["attachments"],
            ("attachments",),
            ["attachments", ""],
        ],
        ids=["str", "padded-str", "list", "tuple", "list-with-blank"],
    )
    @pytest.mark.asyncio
    async def test_caller_supplied_include_is_preserved(self, mock_redmine, supplied):
        """python-redmine accepts `include` as a list too, so stringifying one
        would put a Python repr on the wire and silently drop the caller's
        includes."""
        mock_redmine.issue.filter.return_value = [_mock_issue(relations=_REL)]
        await list_redmine_issues(
            project_id=1,
            include_relations=True,
            filters={"include": supplied},
        )
        include = mock_redmine.issue.filter.call_args[1]["include"]
        assert include.split(",") == ["attachments", "relations"]

    @pytest.mark.asyncio
    async def test_include_not_duplicated(self, mock_redmine):
        mock_redmine.issue.filter.return_value = [_mock_issue(relations=_REL)]
        await list_redmine_issues(
            project_id=1,
            include_relations=True,
            filters={"include": "relations"},
        )
        assert mock_redmine.issue.filter.call_args[1]["include"] == "relations"

    @pytest.mark.asyncio
    async def test_flag_adds_the_key_to_a_narrowed_fields_list(self, mock_redmine):
        """The advertised flag says "add relations"; narrowing `fields` used to
        request the include, pay for it, and drop the result."""
        mock_redmine.issue.filter.return_value = [
            _mock_issue(custom_fields=_CF, relations=_REL)
        ]
        result = await list_redmine_issues(
            project_id=1,
            fields=["id", "subject"],
            include_relations=True,
            include_custom_fields=True,
        )
        assert set(result[0]) == {"id", "subject", "relations", "custom_fields"}
        assert result[0]["relations"] == _REL

    @pytest.mark.asyncio
    async def test_fields_as_a_tuple_still_requests_the_include(self, mock_redmine):
        """The guard and the serializer must agree on what counts as a
        sequence, or the key is emitted without the include behind it."""
        mock_redmine.issue.filter.return_value = [_mock_issue(relations=_REL)]
        result = await list_redmine_issues(project_id=1, fields=("id", "relations"))
        assert result[0] == {"id": 1, "relations": _REL}
        assert "relations" in mock_redmine.issue.filter.call_args[1]["include"]

    @pytest.mark.asyncio
    async def test_star_sentinel_works_as_a_tuple_too(self, mock_redmine):
        """The guard accepts any sequence, so the sentinel comparison must not
        be list-only or ("*",) would silently select nothing."""
        mock_redmine.issue.filter.return_value = [_mock_issue(custom_fields=_CF)]
        as_list = await list_redmine_issues(project_id=1, fields=["*"])
        mock_redmine.issue.filter.return_value = [_mock_issue(custom_fields=_CF)]
        as_tuple = await list_redmine_issues(project_id=1, fields=("*",))
        assert set(as_tuple[0]) == set(as_list[0])

    @pytest.mark.asyncio
    async def test_search_does_not_offer_an_empty_relations_key(self, mock_redmine):
        """search_redmine_issues shares the serializer but never requests the
        include, so offering `relations` there could only ever return []."""
        mock_redmine.issue.search.return_value = [_mock_issue(relations=_REL)]
        result = await search_redmine_issues(query="x", fields=["id", "relations"])
        assert isinstance(result, list)
        assert result and "relations" not in result[0]

    @pytest.mark.asyncio
    async def test_search_can_select_custom_fields(self, mock_redmine):
        """The other half of the shared serializer: unlike `relations`, custom
        field values are rendered without an include, so search can select
        them. Documented rather than suppressed."""
        mock_redmine.issue.search.return_value = [_mock_issue(custom_fields=_CF)]
        result = await search_redmine_issues(query="x", fields=["id", "custom_fields"])
        assert result[0] == {"id": 1, "custom_fields": _CF}

    @pytest.mark.asyncio
    async def test_pagination_total_needs_no_count_query(self, mock_redmine):
        """The total reads off the page response; no second request.

        There used to be a separate ``limit=1`` count query (which had to
        drop the ``include``); since #240 the total comes from the same
        response the rows did, so the one request keeps its include.
        """
        mock_redmine.issue.filter.return_value = [_mock_issue(relations=_REL)]
        await list_redmine_issues(
            project_id=1, include_relations=True, include_pagination_info=True
        )
        assert mock_redmine.issue.filter.call_count == 1
        only_call = mock_redmine.issue.filter.call_args_list[0][1]
        assert only_call["include"] == "relations"
