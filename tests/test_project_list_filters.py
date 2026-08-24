"""Server-side narrowing for ``list_redmine_projects``.

``GET /projects.json`` runs the request through Redmine's ``ProjectQuery``,
so the tool can hand it ``limit``, ``offset`` and a ``filters`` dict instead
of fetching every visible project and filtering locally.

See https://github.com/jztan/redmine-mcp-server/issues/ISSUE (#ISSUE).
"""

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from redminelib import Redmine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.projects import (  # noqa: E402
    list_redmine_projects,
)


# Keys of one entry in the ``projects`` array of ``GET /projects.json``.
# Building the fakes below from a payload rather than from ``Mock()`` keeps a
# test from passing on an attribute Redmine never sends.
def _payload(project_id: int, **extra: Any) -> Dict[str, Any]:
    return {
        "id": project_id,
        "name": f"Project {project_id}",
        "identifier": f"project-{project_id}",
        "description": f"Description {project_id}",
        "created_on": "2026-01-02T03:04:05Z",
        **extra,
    }


class _FakeProject:
    """A python-redmine resource's attribute access, nothing more.

    Absent keys raise ``AttributeError`` the way ``ResourceAttrError`` does,
    so the tool's ``getattr(..., default)`` reads are exercised for real.
    """

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def __getattr__(self, name: str) -> Any:
        try:
            return self._payload[name]
        except KeyError:
            raise AttributeError(name)


class _RecordingProjectManager:
    """Records the params ``project.all()`` was handed."""

    def __init__(self, payloads: Optional[List[Dict[str, Any]]] = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._payloads = [_payload(1)] if payloads is None else payloads

    def all(self, **params: Any) -> List[_FakeProject]:
        self.calls.append(params)
        return [_FakeProject(p) for p in self._payloads]


class _RaisingProjectManager:
    def __init__(self, exc: Exception) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._exc = exc

    def all(self, **params: Any) -> List[_FakeProject]:
        self.calls.append(params)
        raise self._exc


class _FakeClient:
    """Only the attribute ``list_redmine_projects`` reaches for."""

    def __init__(self, project_manager: Any) -> None:
        self.project = project_manager


def _patched(manager: Any) -> Any:
    return patch("redmine_mcp_server._client.redmine", _FakeClient(manager))


class TestFiltersReachRedmine:
    @pytest.mark.asyncio
    async def test_custom_field_filter_is_forwarded(self):
        """The motivating case: narrow on a project custom field."""
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={"cf_42": "Gold"})
        assert manager.calls == [{"cf_42": "Gold"}]
        assert [p["id"] for p in result] == [1]

    @pytest.mark.asyncio
    async def test_named_project_query_filters_are_forwarded(self):
        """``ProjectQuery``'s own filter names pass through unrenamed."""
        manager = _RecordingProjectManager()
        sent = {"status": "1|5", "is_public": "0", "parent_id": "7"}
        with _patched(manager):
            await list_redmine_projects(filters=dict(sent))
        assert manager.calls == [sent]

    @pytest.mark.asyncio
    async def test_filters_merge_with_limit_and_offset(self):
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(limit=5, offset=10, filters={"cf_42": "Gold"})
        assert manager.calls == [{"limit": 5, "offset": 10, "cf_42": "Gold"}]


class TestReservedQueryKeys:
    """``fields``/``f``/``query_id`` would silently return the wrong set."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["fields", "f", "query_id", "f[]", "fields[]"])
    async def test_rejected_before_the_request(self, key):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={key: "name"})
        assert isinstance(result, dict)
        assert key in result["error"]
        assert "every other filter would be lost" in result["error"]
        assert manager.calls == []


class TestOwnedQueryKeys:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["limit", "offset"])
    async def test_signature_owned_key_is_rejected(self, key):
        """Routing around the named parameter would skip its validation."""
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={key: 5})
        assert isinstance(result, dict)
        assert result["error"] == (
            f"filters may not contain {key}: pass it as the named parameter "
            "instead, so it is validated."
        )
        assert manager.calls == []

    @pytest.mark.asyncio
    async def test_both_owned_keys_are_named_together(self):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={"offset": 1, "limit": 5})
        assert "limit, offset" in result["error"]
        assert manager.calls == []


class TestFiltersType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [["cf_42"], "cf_42=Gold", 42, ("cf_42", "Gold")])
    async def test_non_dict_is_rejected(self, bad):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters=bad)
        assert result == {
            "error": "filters must be a dict of Redmine query parameters."
        }
        assert manager.calls == []

    @pytest.mark.asyncio
    async def test_empty_dict_forwards_nothing(self):
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(filters={})
        assert manager.calls == [{}]


class TestLimitAndOffset:
    @pytest.mark.asyncio
    async def test_default_imposes_no_limit(self):
        """The backward-compatibility guarantee, at the params level.

        A `limit` key with any value here would truncate every existing
        caller, since python-redmine reads a missing one as "all of them".
        """
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects()
        assert manager.calls == [{}]

    @pytest.mark.asyncio
    async def test_limit_and_offset_are_forwarded(self):
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(limit=25, offset=50)
        assert manager.calls == [{"limit": 25, "offset": 50}]

    @pytest.mark.asyncio
    async def test_limit_above_one_page_is_not_clamped(self):
        """python-redmine pages past 100 itself, so no page cap applies."""
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(limit=250)
        assert manager.calls == [{"limit": 250}]

    @pytest.mark.asyncio
    async def test_offset_zero_is_omitted(self):
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(offset=0)
        assert manager.calls == [{}]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [0, -1, True, "25", 2.5])
    async def test_invalid_limit_is_rejected(self, bad):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(limit=bad)
        assert result == {"error": "limit must be a positive integer."}
        assert manager.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [-1, True, "0", 1.5])
    async def test_invalid_offset_is_rejected(self, bad):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(offset=bad)
        assert result == {"error": "offset must be a non-negative integer."}
        assert manager.calls == []


class TestPaginationThroughTheRealClient:
    """Driven through python-redmine with only the HTTP layer stubbed.

    Asserting on the params the tool builds cannot show what the library
    does with them, and the "no limit fetches everything" guarantee lives in
    the library's ``bulk_request``. These exercise it.
    """

    @staticmethod
    def _client(total: int, page_cap: int = 2):
        client = Redmine("https://redmine.example.test", key="unused")
        client.engine.chunk = page_cap
        all_projects = [_payload(n) for n in range(1, total + 1)]
        requested: List[Dict[str, Any]] = []

        def _request(method, url, headers=None, params=None, data=None):
            params = dict(params or {})
            requested.append(params)
            offset = params.get("offset", 0)
            # Redmine caps `limit` itself; without that the library's own
            # arithmetic would re-request rows it already has.
            limit = min(params.get("limit", page_cap), page_cap)
            return {
                "projects": all_projects[offset : offset + limit],
                "total_count": total,
                "limit": limit,
                "offset": offset,
            }

        client.engine.request = _request
        return client, requested

    @pytest.mark.asyncio
    async def test_default_walks_every_page(self):
        client, requested = self._client(total=5)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects()
        assert [p["id"] for p in result] == [1, 2, 3, 4, 5]
        assert len(requested) > 1, "one page only -- the rest were dropped"

    @pytest.mark.asyncio
    async def test_explicit_limit_stops_there(self):
        client, requested = self._client(total=5)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(limit=3)
        assert [p["id"] for p in result] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_offset_skips_from_the_front(self):
        client, requested = self._client(total=5)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(limit=2, offset=2)
        assert [p["id"] for p in result] == [3, 4]
        assert requested[0]["offset"] == 2

    @pytest.mark.asyncio
    async def test_filters_ride_along_on_every_page(self):
        client, requested = self._client(total=5)
        with patch("redmine_mcp_server._client.redmine", client):
            await list_redmine_projects(filters={"cf_42": "Gold"})
        assert len(requested) > 1
        assert all(r.get("cf_42") == "Gold" for r in requested)

    @pytest.mark.asyncio
    async def test_created_on_is_serialized(self):
        """The datetime the library decodes still round-trips."""
        client, _ = self._client(total=1)
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects()
        assert result[0]["created_on"] == "2026-01-02T03:04:05"


class TestUnchangedBehaviour:
    @pytest.mark.asyncio
    async def test_default_keys_are_unchanged(self):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects()
        assert set(result[0]) == {
            "id",
            "name",
            "identifier",
            "description",
            "created_on",
        }

    @pytest.mark.asyncio
    async def test_include_custom_fields_still_adds_values(self):
        manager = _RecordingProjectManager(
            [
                _payload(
                    1,
                    custom_fields=[{"id": 42, "name": "Tier", "value": "Gold"}],
                )
            ]
        )
        with _patched(manager):
            result = await list_redmine_projects(
                include_custom_fields=True, filters={"cf_42": "Gold"}
            )
        assert result[0]["custom_fields"] == [
            {"id": 42, "name": "Tier", "value": "Gold"}
        ]
        assert manager.calls == [{"cf_42": "Gold"}]

    @pytest.mark.asyncio
    async def test_missing_optional_attributes_still_default(self):
        payload = _payload(1)
        del payload["description"]
        del payload["created_on"]
        manager = _RecordingProjectManager([payload])
        with _patched(manager):
            result = await list_redmine_projects()
        assert result[0]["description"] == ""
        assert result[0]["created_on"] is None

    @pytest.mark.asyncio
    async def test_error_path_returns_the_envelope(self):
        manager = _RaisingProjectManager(Exception("Connection error"))
        with _patched(manager):
            result = await list_redmine_projects(filters={"cf_42": "Gold"})
        assert isinstance(result, dict)
        assert "listing projects" in result["error"]
        assert "Connection error" in result["error"]
