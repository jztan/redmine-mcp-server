"""``manage_contact(action="list")`` pagination metadata.

The bare array the ``list`` action returns by default says nothing about the
size of the collection it came from, so a caller cannot tell a complete read
from a truncated one. ``include_pagination_info=True`` returns the envelope the
issue tools return, with ``total`` taken from the ``total_count`` Redmine
reports as a sibling of ``contacts`` in the same response.

The fixtures here are the response dict ``engine.request`` actually hands back
-- a decoded JSON envelope -- rather than a ``Mock`` that answers every
attribute, because a ``Mock`` would answer ``total_count`` whether the payload
carried one or not, which is the one thing these tests are about.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.contacts import manage_contact  # noqa: E402

CRM_ON = {"REDMINE_CRM_ENABLED": "true"}

# The keys `list_redmine_issues` puts in its `pagination` block. Pinned so the
# two tools cannot drift into two shapes a caller has to tell apart.
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


def _api_contact(contact_id: int) -> dict:
    """A contact as the CRM API renders it inside a collection response."""
    return {
        "id": contact_id,
        "first_name": f"Contact {contact_id}",
        "last_name": "Example",
        "emails": [{"address": f"c{contact_id}@example.com"}],
        "tag_list": [],
        "created_on": "2026-04-20T10:00:00Z",
        "updated_on": "2026-04-20T11:00:00Z",
    }


def _collection(count: int, *, limit: int = 100, offset: int = 0, **meta) -> dict:
    """The decoded ``GET /contacts.json`` envelope.

    Redmine renders ``total_count``, ``offset`` and ``limit`` as siblings of the
    collection, so the metadata this feature reads arrives in the same dict as
    the contacts. Pass ``total_count=None`` to drop it.
    """
    payload = {
        "contacts": [_api_contact(offset + i + 1) for i in range(count)],
        "offset": offset,
        "limit": limit,
    }
    if "total_count" in meta:
        if meta["total_count"] is not None:
            payload["total_count"] = meta["total_count"]
    else:
        payload["total_count"] = offset + count
    return payload


class TestTheDefaultIsUnchanged:
    """Existing callers must keep getting the bare array."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_flag_off_returns_a_bare_list(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(2, total_count=250)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list")

        assert isinstance(result, list)
        assert [c["id"] for c in result] == [1, 2]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_metadata_does_not_leak_into_the_default(self, mock_redmine):
        """A payload rich in metadata still serializes to contacts alone."""
        mock_redmine.engine.request.return_value = _collection(2, total_count=250)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list")

        assert all("pagination" not in c for c in result)
        assert all("total_count" not in c for c in result)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_flag_is_not_sent_to_redmine(self, mock_redmine):
        """It is a response-shape switch, not a query parameter."""
        mock_redmine.engine.request.return_value = _collection(1, total_count=1)
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", include_pagination_info=True)

        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert "include_pagination_info" not in params


class TestTheEnvelope:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_contacts_are_returned_under_the_resource_key(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(2, total_count=250)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert set(result) == {"contacts", "pagination"}
        assert [c["id"] for c in result["contacts"]] == [1, 2]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_pagination_keys_match_the_issue_tools(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(2, total_count=250)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert set(result["pagination"]) == PAGINATION_KEYS

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_total_comes_from_the_payloads_total_count(self, mock_redmine):
        """The number the caller needs is in the dict the connector parsed."""
        mock_redmine.engine.request.return_value = _collection(2, total_count=250)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert result["pagination"]["total"] == 250
        assert result["pagination"]["count"] == 2

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_limit_is_the_one_that_was_sent(self, mock_redmine):
        """A clamped `limit` is reported as clamped, so `next_offset` lands."""
        mock_redmine.engine.request.return_value = _collection(100, total_count=250)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", limit=500, include_pagination_info=True
            )

        assert mock_redmine.engine.request.call_args.kwargs["params"]["limit"] == 100
        assert result["pagination"]["limit"] == 100
        assert result["pagination"]["next_offset"] == 100

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_count_is_the_contacts_actually_returned(self, mock_redmine):
        """The local slice caps an oversized page; `count` follows it."""
        mock_redmine.engine.request.return_value = _collection(200, total_count=200)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", limit=25, include_pagination_info=True
            )

        assert result["pagination"]["count"] == 25
        assert len(result["contacts"]) == 25


class TestWhereTheCallerIsInTheCollection:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_first_page_with_more_to_come(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(100, total_count=250)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert result["pagination"] == {
            "total": 250,
            "limit": 100,
            "offset": 0,
            "count": 100,
            "has_next": True,
            "has_previous": False,
            "next_offset": 100,
            "previous_offset": None,
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_middle_page(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(
            100, offset=100, total_count=250
        )
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", offset=100, include_pagination_info=True
            )

        assert result["pagination"] == {
            "total": 250,
            "limit": 100,
            "offset": 100,
            "count": 100,
            "has_next": True,
            "has_previous": True,
            "next_offset": 200,
            "previous_offset": 0,
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_last_page(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(
            50, offset=200, total_count=250
        )
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", offset=200, include_pagination_info=True
            )

        assert result["pagination"] == {
            "total": 250,
            "limit": 100,
            "offset": 200,
            "count": 50,
            "has_next": False,
            "has_previous": True,
            "next_offset": None,
            "previous_offset": 100,
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_full_last_page_is_not_reported_as_having_a_next(
        self, mock_redmine
    ):
        """The divergence from the issue tools, and the reason for it.

        `list_redmine_issues` infers `has_next` from `len(issues) == limit`, so
        a collection whose size is an exact multiple of the page size is
        reported as having one more page than it has. `total_count` settles it
        without the guess.
        """
        mock_redmine.engine.request.return_value = _collection(
            100, offset=100, total_count=200
        )
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", offset=100, include_pagination_info=True
            )

        assert result["pagination"]["count"] == result["pagination"]["limit"]
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["next_offset"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_past_the_end(self, mock_redmine):
        """Redmine answers an out-of-range offset with an empty collection."""
        mock_redmine.engine.request.return_value = _collection(
            0, offset=300, total_count=250
        )
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", offset=300, include_pagination_info=True
            )

        assert result["contacts"] == []
        assert result["pagination"] == {
            "total": 250,
            "limit": 100,
            "offset": 300,
            "count": 0,
            "has_next": False,
            "has_previous": True,
            "next_offset": None,
            "previous_offset": 200,
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_short_first_page_is_the_whole_collection(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(3, total_count=3)
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_previous"] is False
        assert result["pagination"]["next_offset"] is None
        assert result["pagination"]["previous_offset"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_previous_offset_never_goes_negative(self, mock_redmine):
        mock_redmine.engine.request.return_value = _collection(
            10, limit=25, offset=10, total_count=100
        )
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", limit=25, offset=10, include_pagination_info=True
            )

        assert result["pagination"]["previous_offset"] == 0


class TestAPayloadWithNoTotalCount:
    """An absent total is reported as absent, not filled in with a guess."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_total_is_null_and_nothing_is_fabricated(self, mock_redmine):
        payload = _collection(100, total_count=None)
        assert "total_count" not in payload
        mock_redmine.engine.request.return_value = payload
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert result["pagination"] == {
            "total": None,
            "limit": 100,
            "offset": 0,
            "count": 100,
            # Unknown, not "no further page": a full page proves nothing here.
            "has_next": None,
            "has_previous": False,
            "next_offset": None,
            "previous_offset": None,
        }
        assert len(result["contacts"]) == 100

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_keys_that_do_not_need_a_total_are_still_exact(
        self, mock_redmine
    ):
        mock_redmine.engine.request.return_value = _collection(
            40, offset=40, total_count=None
        )
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", offset=40, include_pagination_info=True
            )

        assert result["pagination"]["offset"] == 40
        assert result["pagination"]["count"] == 40
        assert result["pagination"]["has_previous"] is True
        assert result["pagination"]["previous_offset"] == 0

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    @pytest.mark.parametrize("bad", ["250", 250.5, True, None, {"count": 250}])
    async def test_a_non_integer_total_count_is_not_trusted(self, mock_redmine, bad):
        payload = _collection(2, total_count=None)
        payload["total_count"] = bad
        mock_redmine.engine.request.return_value = payload
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert result["pagination"]["total"] is None
        assert result["pagination"]["has_next"] is None
        assert result["pagination"]["next_offset"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_response_that_is_not_a_dict_still_answers(self, mock_redmine):
        """The endpoint's own envelope is the only source of the metadata."""
        mock_redmine.engine.request.return_value = []
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert result["contacts"] == []
        assert result["pagination"]["total"] is None
        assert result["pagination"]["count"] == 0


class TestTheErrorEnvelopeIsUnaffected:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_rejected_offset_is_still_an_error(self, mock_redmine):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", offset=-1, include_pagination_info=True
            )

        assert "offset" in result["error"]
        assert "pagination" not in result
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_failed_request_is_still_an_error(self, mock_redmine):
        mock_redmine.engine.request.side_effect = Exception("boom")
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert "error" in result
        assert "contacts" not in result

    @pytest.mark.asyncio
    async def test_the_disabled_error_still_wins(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await manage_contact(action="list", include_pagination_info=True)

        assert "REDMINE_CRM_ENABLED" in result["error"]
