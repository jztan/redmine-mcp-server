"""Server-side narrowing for ``list_redmine_projects``.

``GET /projects.json`` runs the request through Redmine's ``ProjectQuery``,
so the tool can hand it ``limit``, ``offset`` and a ``filters`` dict instead
of fetching every visible project and filtering locally.

See https://github.com/jztan/redmine-mcp-server/issues/ISSUE (#ISSUE).
"""

import builtins
import os
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from redminelib import Redmine
from redminelib.engines import SyncEngine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.projects import (  # noqa: E402
    _PROJECT_QUERY_FILTER_NAMES,
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
    @pytest.mark.parametrize("key", ["limit", "offset", "include_custom_fields"])
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

    @pytest.mark.asyncio
    async def test_the_response_shape_flag_gets_the_useful_message(self):
        """`include_custom_fields` is not a query parameter at all.

        The unregistered-key allowlist would refuse it too, but its message
        lists Redmine's filter names -- which is not the answer to "why did
        my key not work" when the answer is "it is a named argument". Owning
        the key puts that guard first.
        """
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(
                filters={"include_custom_fields": True}
            )
        assert result["error"] == (
            "filters may not contain include_custom_fields: pass it as the "
            "named parameter instead, so it is validated."
        )
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
    async def test_default_keys_are_the_full_rendered_set(self):
        """Every key `index.api.rsb` renders, and nothing invented.

        Was five keys; the six Redmine also sends were being dropped.
        """
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects()
        assert set(result[0]) == {
            "id",
            "name",
            "identifier",
            "description",
            "homepage",
            "parent",
            "status",
            "is_public",
            "inherit_members",
            "created_on",
            "updated_on",
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


# --- Real python-redmine, real Redmine URL shapes, no socket -----------------
#
# The guards below are about what never leaves the process, so the fakes above
# are not enough: `_RecordingProjectManager` replaces the very layer that would
# act on a filter before the request. These tests keep python-redmine whole --
# `ResourceManager.all`, `Project.bulk_decode`, `Redmine.upload` -- and cut the
# socket at the one place every HTTP call funnels through.

_SECRET = b"SUPER-SECRET-LOCAL-FILE\n"


class _SpyEngine(SyncEngine):
    """The real engine with ``request`` recorded instead of sent.

    Every call out of python-redmine goes through ``request``: ``bulk_request``
    fetches a collection through it, and ``Redmine.upload`` POSTs an opened
    file's bytes through it. Recording here therefore catches an upload
    whichever layer started it, which is what lets a test assert that none
    happened rather than only that an error came back.
    """

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.calls: List[Dict[str, Any]] = []
        self.projects: List[Dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        stream = kwargs.get("data")
        body = stream.read() if hasattr(stream, "read") else stream
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": kwargs.get("params"),
                "body": body,
            }
        )
        if url.endswith("/uploads.json"):
            return {"upload": {"token": "spy-token"}}
        return {
            "projects": list(self.projects),
            "total_count": len(self.projects),
            "offset": 0,
            "limit": 25,
        }

    @property
    def uploads(self) -> List[Dict[str, Any]]:
        return [call for call in self.calls if call["url"].endswith("/uploads.json")]


def _spy_client(payloads: Optional[List[Dict[str, Any]]] = None) -> Redmine:
    client = Redmine(
        "https://redmine.example.com",
        key="configured-key",
        engine=_SpyEngine,
    )
    client.engine.projects = [_payload(1)] if payloads is None else payloads
    return client


class _OpenSpy:
    """Records opens of one path, passing every other open straight through."""

    def __init__(self, path: Any) -> None:
        self.path = str(path)
        self.opened: List[str] = []
        self._patcher: Any = None

    def __enter__(self) -> "_OpenSpy":
        real_open = builtins.open

        def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
            if str(file) == self.path:
                self.opened.append(str(file))
            return real_open(file, *args, **kwargs)

        self._patcher = patch("builtins.open", spy)
        self._patcher.start()
        return self

    def __exit__(self, *exc: Any) -> bool:
        self._patcher.stop()
        return False


def _secret_file(tmp_path: Any) -> Any:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(_SECRET)
    return secret


class TestNoFilterCanCarryALocalFile:
    """A value must be one scalar, so no key can name a file to send."""

    @pytest.mark.asyncio
    async def test_uploads_filter_neither_reads_nor_sends_the_file(self, tmp_path):
        secret = _secret_file(tmp_path)
        client = _spy_client()
        with _OpenSpy(secret) as opens:
            with patch("redmine_mcp_server._client.redmine", client):
                result = await list_redmine_projects(
                    filters={"uploads": [{"path": str(secret), "filename": "leak.txt"}]}
                )
        # Side effects first: a regression should fail on the file and the
        # socket, not on the shape of what came back.
        assert opens.opened == []
        assert client.engine.calls == []
        assert isinstance(result, dict)
        assert "uploads" in result["error"]

    @pytest.mark.asyncio
    async def test_the_spy_does_fire_when_python_redmine_gets_the_payload(
        self, tmp_path
    ):
        """Anchors the assertion above rather than repeating the exploit.

        ``engine.calls == []`` and ``opens.opened == []`` would pass just as
        well against a spy that could never record anything, so this shows the
        same payload does read the file and does POST its bytes once it reaches
        python-redmine -- which is the thing the guard stops it doing.
        """
        secret = _secret_file(tmp_path)
        client = _spy_client()
        with _OpenSpy(secret) as opens:
            client.project.all(uploads=[{"path": str(secret), "filename": "leak.txt"}])
        assert opens.opened == [str(secret)]
        assert len(client.engine.uploads) == 1
        assert client.engine.uploads[0]["body"] == _SECRET


class TestNoFilterCanSubstituteTheCredential:
    """`key` is not a filter name, so it cannot ride in through `filters`."""

    @pytest.mark.asyncio
    async def test_key_is_refused_before_the_request(self):
        client = _spy_client()
        with patch("redmine_mcp_server._client.redmine", client):
            result = await list_redmine_projects(filters={"key": "someone-elses-key"})
        assert client.engine.calls == []
        assert isinstance(result, dict)
        assert "key" in result["error"]

    def test_a_forwarded_key_would_travel_beside_the_configured_one(self):
        """Anchors the refusal: it reaches the query string, not nowhere.

        Redmine reads ``params[:key]`` ahead of the ``X-Redmine-API-Key``
        header python-redmine sets, so both arriving together is the whole
        problem -- the request is authenticated as whoever the parameter names.
        """
        client = _spy_client()
        list(client.project.all(key="someone-elses-key"))
        assert client.engine.calls[0]["params"]["key"] == "someone-elses-key"
        headers = client.engine.requests["headers"]
        assert headers["X-Redmine-API-Key"] == "configured-key"


# The filter names `ProjectQuery` registers, spelled out rather than imported,
# so adding one to the set without covering it here fails a test.
_ALLOWLISTED_KEYS = [
    "created_on",
    "description",
    "id",
    "is_public",
    "name",
    "parent_id",
    "status",
    "updated_on",
]


class TestKeyAllowlist:
    def test_the_names_here_are_the_whole_allowlist(self):
        assert set(_ALLOWLISTED_KEYS) == set(_PROJECT_QUERY_FILTER_NAMES)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", _ALLOWLISTED_KEYS)
    async def test_each_allowlisted_key_is_forwarded(self, key):
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(filters={key: "1"})
        assert manager.calls == [{key: "1"}]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key",
        [
            "cf_42",
            "cf_1",
            "cf_42.cf_7",
            "cf_42.due_date",
            "cf_42.status",
        ],
    )
    async def test_custom_field_spellings_are_forwarded(self, key):
        """`cf_<id>` plus the chained forms Redmine registers for it."""
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(filters={key: "Gold"})
        assert manager.calls == [{key: "Gold"}]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key",
        [
            "cf_abc",
            "cf_",
            "cf",
            "cf_42x",
            "cf_42.name",
            "cf_42.cf_abc",
            "cf_42.due_date.status",
            "nonsense",
            "uploads",
            "key",
            "include",
            "set_filter",
            "sort",
            "STATUS",
            "status ",
        ],
    )
    async def test_anything_else_is_refused_before_the_request(self, key):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={key: "x"})
        assert isinstance(result, dict)
        assert key in result["error"]
        assert "the accepted keys are" in result["error"]
        assert "cf_<id>" in result["error"]
        assert manager.calls == []

    @pytest.mark.asyncio
    async def test_a_non_string_key_is_refused(self):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={7: "x"})
        assert isinstance(result, dict)
        assert "7" in result["error"]
        assert manager.calls == []

    @pytest.mark.asyncio
    async def test_one_bad_key_refuses_the_whole_call(self):
        """No partial forwarding: the good key does not get sent either."""
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(
                filters={"status": "1|5", "nonsense": "x"}
            )
        assert isinstance(result, dict)
        assert manager.calls == []


class TestValueTypes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value",
        [
            "Gold",
            42,
            2.5,
            date(2026, 1, 2),
            datetime(2026, 1, 2, 3, 4, 5),
        ],
    )
    async def test_scalars_are_forwarded(self, value):
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(filters={"cf_42": value})
        assert manager.calls == [{"cf_42": value}]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [True, False])
    async def test_a_bool_is_refused_rather_than_matching_nothing(self, value):
        # A bool passes any reasonable "is this a scalar" test and then fails
        # silently: requests urlencodes it as `is_public=True`, and the values
        # a `:list` filter accepts are "1" and "0"
        # (Query#operators_by_filter_type gives :list only "=" and "!"), so
        # Redmine builds `IN ('True')` and matches nothing -- a 200 with an
        # empty list, indistinguishable from a filter that legitimately found
        # nothing. Refusing it names the spelling that works instead.
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={"is_public": value})
        assert isinstance(result, dict) and "error" in result
        assert '"1" or "0"' in result["error"]
        assert manager.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value",
        [
            ["Gold"],
            ("Gold",),
            {"path": "/etc/passwd"},
            [{"path": "/etc/passwd", "filename": "leak.txt"}],
            None,
            set(),
            b"Gold",
        ],
    )
    async def test_non_scalars_are_refused_for_an_allowed_key(self, value):
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={"cf_42": value})
        assert isinstance(result, dict)
        assert "cf_42" in result["error"]
        assert "single scalar" in result["error"]
        assert manager.calls == []

    @pytest.mark.asyncio
    async def test_none_is_refused_rather_than_dropped(self):
        """`requests` omits a None param, so the filter would silently vanish.

        The collection would come back unnarrowed with a 200, which reads
        exactly like a filter that matched everything.
        """
        manager = _RecordingProjectManager()
        with _patched(manager):
            result = await list_redmine_projects(filters={"status": None})
        assert isinstance(result, dict)
        assert "status" in result["error"]
        assert manager.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "filters",
        [
            {"created_on": ">=2024-01-01"},
            {"created_on": "><2024-01-01|2024-12-31"},
            {"status": "1|5"},
            {"status": "!1"},
            {"name": "~foo"},
            {"name": "!~foo"},
            {"description": "*"},
            {"parent_id": "!*"},
            {"cf_42": ">=2024-01-01"},
        ],
    )
    async def test_operator_carrying_values_are_untouched(self, filters):
        """An operator rides in the value, so nothing here needs a key rule.

        `Query#add_short_filter` matches the operator against the start of the
        value and splits the remainder on `|`, so these are ordinary strings as
        far as this tool is concerned and must arrive byte-for-byte.
        """
        manager = _RecordingProjectManager()
        with _patched(manager):
            await list_redmine_projects(filters=dict(filters))
        assert manager.calls == [filters]
