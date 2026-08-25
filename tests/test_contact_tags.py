"""Unit tests for list_contact_tags (RedmineUP CRM contact tags)."""

import os
import sys
from unittest.mock import patch

import pytest
from redminelib.exceptions import ForbiddenError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.contacts import (  # noqa: E402
    _contact_tag_to_dict,
    list_contact_tags,
)

ENABLED = {"REDMINE_CRM_ENABLED": "true"}


def test_tag_to_dict():
    assert _contact_tag_to_dict({"id": 3, "name": "vip", "color": "FF0000"}) == {
        "id": 3,
        "name": "vip",
        "color": "FF0000",
    }


def test_tag_to_dict_missing_fields():
    assert _contact_tag_to_dict({"id": 3}) == {"id": 3, "name": "", "color": None}


@pytest.mark.asyncio
async def test_disabled_flag_returns_error():
    with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
        result = await list_contact_tags()
    assert "REDMINE_CRM_ENABLED" in result["error"]


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
@patch("redmine_mcp_server._client.redmine")
async def test_lists_tags(mock_redmine):
    mock_redmine.engine.request.return_value = {
        "tags": [{"id": 1, "name": "vip", "color": "FF0000"}, {"id": 2, "name": "x"}],
        "total_count": 2,
    }
    with patch.dict(os.environ, ENABLED):
        result = await list_contact_tags()
    assert result == [
        {"id": 1, "name": "vip", "color": "FF0000"},
        {"id": 2, "name": "x", "color": None},
    ]
    assert mock_redmine.engine.request.call_args.args == (
        "get",
        "http://localhost:3000/contacts_tags.json",
    )


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
@patch("redmine_mcp_server._client.redmine")
async def test_empty(mock_redmine):
    mock_redmine.engine.request.return_value = {"tags": [], "total_count": 0}
    with patch.dict(os.environ, ENABLED):
        assert await list_contact_tags() == []


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
@patch("redmine_mcp_server._client.redmine")
async def test_forbidden_maps_to_error(mock_redmine):
    mock_redmine.engine.request.side_effect = ForbiddenError()
    with patch.dict(os.environ, ENABLED):
        result = await list_contact_tags()
    assert "Access denied" in result["error"]
