"""``list_redmine_projects`` pagination metadata.

The bare list the tool returns says nothing about the size of the collection
it came from, so a caller cannot state a count without counting, and a
narrowed read cannot be told from a complete one.
``include_pagination_info=True`` returns the envelope the issue tools return.

Unlike the contacts endpoint, this total is honest under every filter.
Redmine builds ``@project_count`` from ``@query.result_count`` and the rows
from ``project_scope(:offset, :limit)`` -- the same query -- so the number
measures exactly the collection being paged. There is no equivalent of the
searched-contact-list case where the count and the rows come from different
scopes, and so nothing here suppresses the total.

Driven through python-redmine with only the HTTP layer stubbed, because
``total_count`` is read off the evaluated ``ResourceSet`` and that is the
library's arithmetic, not the tool's.

See https://github.com/jztan/redmine-mcp-server/issues/ISSUE (#ISSUE).
"""

import os
import sys
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from redminelib import Redmine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.projects import list_redmine_projects  # noqa: E402

# The keys `list_redmine_issues` puts in its `pagination` block. Pinned so the
# tools cannot drift into two shapes a caller has to tell apart.
PAGINATION_KEYS = {
    "total",
    "limit",
    "offset",
    "count",
    "has_next",
    "has_previous",
    "next_offset",
    "previous_offset",
}


def _payload(project_id: int) -> Dict[str, Any]:
    return {
        "id": project_id,
        "name": f"Project {project_id}",
        "identifier": f"project-{project_id}",
        "description": f"Description {project_id}",
        "created_on": "2026-01-02T03:04:05Z",
    }


def _client(total: int, page_cap: int = 100):
    """A real client with only ``engine.request`` stubbed."""
    client = Redmine("https://redmine.example.test", key="unused")
    client.engine.chunk = page_cap
    all_projects = [_payload(n) for n in range(1, total + 1)]
    requested: List[Dict[str, Any]] = []

    def _request(method, url, headers=None, params=None, data=None):
        params = dict(params or {})
        requested.append(params)
        offset = params.get("offset", 0)
        limit = min(params.get("limit", page_cap), page_cap)
        return {
            "projects": all_projects[offset : offset + limit],
            "total_count": total,
            "limit": limit,
            "offset": offset,
        }

    client.engine.request = _request
    return client, requested


class TestTheDefaultIsUnchanged:
    @pytest.mark.asyncio
    async def test_flag_off_returns_a_bare_list(self):
        client, _ = _client(total=3)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects()

        assert isinstance(result, list)
        assert [p["id"] for p in result] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_the_flag_is_not_sent_to_redmine(self):
        """It selects the response shape; it is not a query parameter."""
        client, requested = _client(total=1)
        with patch("redmine_mcp_server._client.redmine", client):
            await list_redmine_projects(include_pagination_info=True)

        assert all("include_pagination_info" not in r for r in requested)

    @pytest.mark.asyncio
    async def test_it_cannot_be_smuggled_through_filters(self):
        client, requested = _client(total=1)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                filters={"include_pagination_info": True}
            )

        assert "include_pagination_info" in result["error"]
        assert requested == []


class TestTheEnvelope:
    @pytest.mark.asyncio
    async def test_projects_are_returned_under_the_resource_key(self):
        client, _ = _client(total=3)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(include_pagination_info=True)

        assert set(result) == {"projects", "pagination"}
        assert [p["id"] for p in result["projects"]] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_the_pagination_keys_match_the_issue_tools(self):
        client, _ = _client(total=3)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(include_pagination_info=True)

        assert set(result["pagination"]) == PAGINATION_KEYS

    @pytest.mark.asyncio
    async def test_custom_fields_still_ride_along(self):
        client, _ = _client(total=1)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                include_pagination_info=True, include_custom_fields=True
            )

        assert "custom_fields" in result["projects"][0]

    @pytest.mark.asyncio
    async def test_the_total_costs_no_extra_request(self):
        """``total_count`` rides the pages already fetched.

        ``ResourceSet.total_count`` is populated by the same ``bulk_request``
        that produced the rows, so reading it after the loop adds nothing. A
        separate count query -- what ``list_redmine_issues`` does -- would
        show up here as another request.
        """
        client, requested = _client(total=3)
        with patch("redmine_mcp_server._client.redmine", client):
            with_envelope = await list_redmine_projects(include_pagination_info=True)
        with_envelope_calls = len(requested)

        client, requested = _client(total=3)
        with patch("redmine_mcp_server._client.redmine", client):
            await list_redmine_projects()

        assert with_envelope["pagination"]["total"] == 3
        assert with_envelope_calls == len(requested)


class TestWhereTheCallerIsInTheCollection:
    @pytest.mark.asyncio
    async def test_first_page_with_more_to_come(self):
        client, _ = _client(total=7)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(limit=3, include_pagination_info=True)

        assert result["pagination"] == {
            "total": 7,
            "limit": 3,
            "offset": 0,
            "count": 3,
            "has_next": True,
            "has_previous": False,
            "next_offset": 3,
            "previous_offset": None,
        }

    @pytest.mark.asyncio
    async def test_middle_page(self):
        client, _ = _client(total=7)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                limit=3, offset=3, include_pagination_info=True
            )

        assert result["pagination"] == {
            "total": 7,
            "limit": 3,
            "offset": 3,
            "count": 3,
            "has_next": True,
            "has_previous": True,
            "next_offset": 6,
            "previous_offset": 0,
        }

    @pytest.mark.asyncio
    async def test_last_page_is_short(self):
        client, _ = _client(total=7)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                limit=3, offset=6, include_pagination_info=True
            )

        assert result["pagination"]["count"] == 1
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["next_offset"] is None

    @pytest.mark.asyncio
    async def test_a_full_last_page_is_not_reported_as_having_a_next(self):
        """The boundary the issue tools' full-page inference gets wrong.

        ``list_redmine_issues`` infers ``has_next`` from ``len == limit``, so
        a collection sized an exact multiple of the page reports one page too
        many. A real total settles it.
        """
        client, _ = _client(total=6)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                limit=3, offset=3, include_pagination_info=True
            )

        assert result["pagination"]["count"] == result["pagination"]["limit"]
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["next_offset"] is None


class TestWithoutALimit:
    """No ``limit`` means every visible project, which is the default.

    There is then no page size, so the envelope describes one complete read
    rather than a window: nothing further to ask for, and the only meaningful
    predecessor is the start of the collection.
    """

    @pytest.mark.asyncio
    async def test_the_whole_collection_reports_no_next_page(self):
        client, _ = _client(total=7, page_cap=2)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(include_pagination_info=True)

        assert result["pagination"] == {
            "total": 7,
            "limit": 7,
            "offset": 0,
            "count": 7,
            "has_next": False,
            "has_previous": False,
            "next_offset": None,
            "previous_offset": None,
        }

    @pytest.mark.asyncio
    async def test_an_offset_read_points_back_at_the_start(self):
        client, _ = _client(total=7, page_cap=2)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(offset=3, include_pagination_info=True)

        assert result["pagination"]["count"] == 4
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_previous"] is True
        assert result["pagination"]["previous_offset"] == 0

    @pytest.mark.asyncio
    async def test_an_offset_past_the_end_never_points_at_itself(self):
        """The regression: `previous_offset` must not be the current offset.

        With no limit the row count is the window, and past the end that
        count is zero -- so a naive ``offset - limit`` hands back the offset
        the caller is already on, and a client walking backwards never moves.
        """
        client, _ = _client(total=7, page_cap=2)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                offset=100, include_pagination_info=True
            )

        assert result["projects"] == []
        assert result["pagination"]["count"] == 0
        assert result["pagination"]["previous_offset"] == 0
        assert result["pagination"]["has_next"] is False


class TestTheTotalIsNeverSuppressed:
    """A filtered read still reports a total, unlike a searched contact list.

    ``@project_count`` comes from ``@query.result_count``, the same query the
    rows come from, so a filter narrows the count with the collection.
    """

    @pytest.mark.asyncio
    async def test_a_filtered_read_still_carries_its_total(self):
        client, requested = _client(total=4)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                filters={"status": "1|5"}, include_pagination_info=True
            )

        assert result["pagination"]["total"] == 4
        assert all(r.get("status") == "1|5" for r in requested)

    @pytest.mark.asyncio
    async def test_a_custom_field_filter_keeps_its_total(self):
        client, _ = _client(total=2)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                filters={"cf_42": "Gold"}, include_pagination_info=True
            )

        assert result["pagination"]["total"] == 2
        assert result["pagination"]["has_next"] is False


class TestAMetadataSuppressingDeployment:
    """`nometa` truncates the list and makes the total agree with it.

    `api_meta` returns nil when `nometa` is in the request or the
    `X-Redmine-Nometa` header is set, so the response carries no
    `total_count`, `limit` or `offset`. `bulk_request` then takes its
    fallback branch, sets `total_count = len(first page)` and stops paging.

    This pins the behaviour rather than endorsing it: the envelope reads as a
    complete collection when it is one chunk of a larger one, and nothing
    reachable from this tool can tell that apart from a genuinely small
    instance. It is documented in the tool, and the test exists so the day
    someone finds a signal for it, this is the assertion that changes.
    """

    @staticmethod
    def _client(real_total: int, chunk: int = 100):
        client = Redmine("https://redmine.example.test", key="unused")
        client.engine.chunk = chunk
        rows = [_payload(n) for n in range(1, real_total + 1)]

        def _request(method, url, headers=None, params=None, data=None):
            params = dict(params or {})
            offset = params.get("offset", 0)
            limit = min(params.get("limit", chunk), chunk)
            # No total_count, limit or offset: api_meta returned nil.
            return {"projects": rows[offset : offset + limit]}

        client.engine.request = _request
        return client

    @pytest.mark.asyncio
    async def test_the_total_describes_the_page_not_the_collection(self):
        with patch("redmine_mcp_server._client.redmine", self._client(5000)):
            result = await list_redmine_projects(include_pagination_info=True)

        # Truncated at one chunk -- which it was before this tool reported
        # anything, since `bulk_request` cannot page without the metadata.
        assert len(result["projects"]) == 100
        # And the total agrees with the truncation, so it reads as complete.
        assert result["pagination"]["total"] == 100
        assert result["pagination"]["count"] == 100

    @pytest.mark.asyncio
    async def test_nometa_cannot_be_requested_through_filters(self):
        """The allowlist keeps a caller from inducing this deliberately."""
        with patch("redmine_mcp_server._client.redmine", self._client(5)):
            result = await list_redmine_projects(
                filters={"nometa": "1"}, include_pagination_info=True
            )

        assert "nometa" in result["error"]


class TestTheErrorEnvelopeIsUnaffected:
    @pytest.mark.asyncio
    async def test_a_rejected_offset_is_still_an_error(self):
        client, requested = _client(total=1)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                offset=-1, include_pagination_info=True
            )

        assert "offset" in result["error"]
        assert "pagination" not in result
        assert requested == []

    @pytest.mark.asyncio
    async def test_a_failed_request_is_still_an_error(self):
        client = Redmine("https://redmine.example.test", key="unused")

        def _boom(*a, **k):
            raise Exception("boom")

        client.engine.request = _boom
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(include_pagination_info=True)

        assert "error" in result
        assert "projects" not in result


class TestAnUnboundedOffsetCostsWhatReadingFromZeroCosts:
    """``offset`` with no ``limit`` pages past the end of the collection.

    ``bulk_request`` computes ``limit = limit or total_count`` and then pages
    that many rows *from* ``offset``, rather than up to the end of the
    collection. The requests past the end come back empty but are still
    issued, so the request count is ``ceil(total_count / chunk)`` whatever
    the offset is.

    The rows are right either way -- this is a cost, not a correctness bug,
    and it belongs to python-redmine rather than to this tool. It is pinned
    because the parameter description makes a promise about that cost, and
    an earlier wording claimed paging "runs to the end of the collection
    from ``offset``", which reads as though a late offset were cheap.
    """

    @pytest.mark.asyncio
    async def test_a_late_offset_costs_the_same_as_reading_everything(self):
        client, requested = _client(total=250)
        with patch("redmine_mcp_server._client.redmine", client):
            everything = await list_redmine_projects()
        from_zero = len(requested)

        client, requested = _client(total=250)
        with patch("redmine_mcp_server._client.redmine", client):
            tail = await list_redmine_projects(offset=240)

        assert len(everything) == 250
        assert len(tail) == 10
        # Ten rows cost what all 250 cost.
        assert len(requested) == from_zero == 3
        # Two of the three asked for rows that cannot exist.
        assert [p["offset"] for p in requested] == [240, 340, 440]

    @pytest.mark.asyncio
    async def test_an_offset_past_the_end_still_pages(self):
        client, requested = _client(total=250)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                offset=300, include_pagination_info=True
            )

        assert result["projects"] == []
        assert len(requested) == 3
        # The envelope is still honest about the collection behind it.
        assert result["pagination"]["total"] == 250
        assert result["pagination"]["count"] == 0
        assert result["pagination"]["has_next"] is False
        # And the caller is sent back to the start, not to the offset they
        # are already sitting on -- there is no page size to step back by.
        assert result["pagination"]["previous_offset"] == 0

    @pytest.mark.asyncio
    async def test_pairing_the_offset_with_a_limit_is_the_cheap_form(self):
        client, requested = _client(total=250)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(
                limit=10, offset=240, include_pagination_info=True
            )

        assert len(result["projects"]) == 10
        assert len(requested) == 1
        assert result["pagination"]["previous_offset"] == 230
