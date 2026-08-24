"""The project fields ``list_redmine_projects`` used to drop.

``app/views/projects/index.api.rsb`` renders ``homepage``, ``parent``,
``status``, ``is_public``, ``inherit_members`` and ``updated_on`` alongside
the five keys this tool already returned, and the serializer discarded all
six. The renderer is byte-identical on ``6.1-stable``, ``7.0-stable`` and
``master``, so none of this is version-contingent.

Two of them are why the absent case matters. ``is_public`` and
``inherit_members`` are booleans, so a ``getattr`` default of ``False`` would
be indistinguishable from Redmine having said so; and ``parent`` is rendered
only ``if project.parent && project.parent.visible?``, so its absence is
genuinely ambiguous and must not be reported as "top-level".

See https://github.com/jztan/redmine-mcp-server/issues/238 (#238).
"""

import os
import sys
from typing import Any, Dict
from unittest.mock import patch

import pytest
from redminelib import Redmine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.projects import list_redmine_projects  # noqa: E402

# Every key `index.api.rsb` renders for a project, as Redmine sends them.
FULL_PAYLOAD: Dict[str, Any] = {
    "id": 1,
    "name": "Website",
    "identifier": "website",
    "description": "The public site",
    "homepage": "https://example.test",
    "parent": {"id": 7, "name": "Umbrella"},
    "status": 1,
    "is_public": True,
    "inherit_members": True,
    "created_on": "2026-01-02T03:04:05Z",
    "updated_on": "2026-03-04T05:06:07Z",
}


def _client(payload: Dict[str, Any]):
    client = Redmine("https://redmine.example.test", key="unused")

    def _request(method, url, headers=None, params=None, data=None):
        return {
            "projects": [payload],
            "total_count": 1,
            "limit": 100,
            "offset": 0,
        }

    client.engine.request = _request
    return client


async def _one(payload: Dict[str, Any]) -> Dict[str, Any]:
    with patch("redmine_mcp_server._client.redmine", _client(payload)):
        result = await list_redmine_projects()
    return result[0]


class TestTheFieldsRedmineSends:
    @pytest.mark.asyncio
    async def test_every_rendered_key_survives(self):
        entry = await _one(FULL_PAYLOAD)

        assert entry["homepage"] == "https://example.test"
        assert entry["parent"] == {"id": 7, "name": "Umbrella"}
        assert entry["status"] == 1
        assert entry["is_public"] is True
        assert entry["inherit_members"] is True
        assert entry["updated_on"] == "2026-03-04T05:06:07"

    @pytest.mark.asyncio
    async def test_the_original_five_are_unchanged(self):
        entry = await _one(FULL_PAYLOAD)

        assert entry["id"] == 1
        assert entry["name"] == "Website"
        assert entry["identifier"] == "website"
        assert entry["description"] == "The public site"
        assert entry["created_on"] == "2026-01-02T03:04:05"

    @pytest.mark.asyncio
    async def test_status_5_is_carried_as_redmine_codes_it(self):
        """Closed projects are only reachable via `filters={"status": "1|5"}`,
        so the code has to arrive intact for a caller to tell them apart."""
        entry = await _one({**FULL_PAYLOAD, "status": 5})

        assert entry["status"] == 5

    @pytest.mark.asyncio
    async def test_parent_is_a_named_ref_like_the_other_serializers(self):
        entry = await _one(FULL_PAYLOAD)

        assert set(entry["parent"]) == {"id", "name"}


class TestAnAbsentKeyIsNeverInvented:
    """Redmine omits rather than nulls, and a default would read as a value."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key", ["homepage", "parent", "status", "is_public", "inherit_members"]
    )
    async def test_a_missing_key_reads_as_null(self, key):
        payload = {k: v for k, v in FULL_PAYLOAD.items() if k != key}
        entry = await _one(payload)

        assert entry[key] is None

    @pytest.mark.asyncio
    async def test_a_missing_updated_on_reads_as_null(self):
        payload = {k: v for k, v in FULL_PAYLOAD.items() if k != "updated_on"}
        entry = await _one(payload)

        assert entry["updated_on"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["is_public", "inherit_members"])
    async def test_an_absent_boolean_is_not_false(self, key):
        """The one that matters: `False` is a setting, `null` is silence."""
        payload = {k: v for k, v in FULL_PAYLOAD.items() if k != key}
        entry = await _one(payload)

        assert entry[key] is not False
        assert entry[key] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["is_public", "inherit_members"])
    async def test_a_real_false_is_carried_through(self, key):
        entry = await _one({**FULL_PAYLOAD, key: False})

        assert entry[key] is False

    @pytest.mark.asyncio
    async def test_an_empty_homepage_is_kept_as_the_empty_string(self):
        """Redmine renders `homepage` always; unset it is empty, not absent."""
        entry = await _one({**FULL_PAYLOAD, "homepage": ""})

        assert entry["homepage"] == ""

    @pytest.mark.asyncio
    async def test_an_invisible_parent_is_indistinguishable_from_top_level(self):
        """Redmine renders `parent` only when it exists and is visible.

        Both a genuine top-level project and a child whose parent the caller
        cannot see arrive with the key absent, so `null` is the only honest
        answer and the docstring must not promise "top-level".
        """
        top_level = await _one({k: v for k, v in FULL_PAYLOAD.items() if k != "parent"})
        hidden_parent = await _one(
            {k: v for k, v in FULL_PAYLOAD.items() if k != "parent"}
        )

        assert top_level["parent"] is None
        assert hidden_parent["parent"] is None
        assert top_level["parent"] == hidden_parent["parent"]
