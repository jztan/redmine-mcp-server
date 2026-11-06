"""Unit tests for list_contact_tags (RedmineUP CRM contact tags)."""

import os
import sys
from unittest.mock import patch

import pytest
from redminelib.exceptions import ForbiddenError, ResourceNotFoundError

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


# --------------------------------------------------------------------------
# CRM 4.5.1 removed GET /contacts_tags.json (#448): fall back to the
# tag_list of each visible contact.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
@patch("redmine_mcp_server._client.redmine")
async def test_404_falls_back_to_contact_tag_lists(mock_redmine):
    mock_redmine.engine.request.side_effect = [
        ResourceNotFoundError(),
        {
            "contacts": [
                {"id": 1, "tag_list": ["vip", "Beta"]},
                {"id": 2, "tag_list": []},
                {"id": 3},
            ],
            "total_count": 3,
        },
    ]
    with patch.dict(os.environ, ENABLED):
        result = await list_contact_tags()
    assert result == [
        {"id": None, "name": "Beta", "color": None},
        {"id": None, "name": "vip", "color": None},
    ]
    calls = mock_redmine.engine.request.call_args_list
    assert calls[1].args == ("get", "http://localhost:3000/contacts.json")
    assert calls[1].kwargs["params"] == {"limit": 100, "offset": 0}


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
@patch("redmine_mcp_server._client.redmine")
async def test_fallback_pages_until_total_and_dedupes(mock_redmine):
    page1 = {"contacts": [{"tag_list": ["a"]}] * 100, "total_count": 101}
    page2 = {"contacts": [{"tag_list": ["a", "b"]}], "total_count": 101}
    mock_redmine.engine.request.side_effect = [ResourceNotFoundError(), page1, page2]
    with patch.dict(os.environ, ENABLED):
        result = await list_contact_tags()
    assert [t["name"] for t in result] == ["a", "b"]
    calls = mock_redmine.engine.request.call_args_list
    assert len(calls) == 3
    assert calls[2].kwargs["params"] == {"limit": 100, "offset": 100}


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
@patch("redmine_mcp_server._client.redmine")
async def test_fallback_stops_on_empty_page_without_total(mock_redmine):
    mock_redmine.engine.request.side_effect = [
        ResourceNotFoundError(),
        {"contacts": [{"tag_list": ["x"]}]},
        {"contacts": []},
    ]
    with patch.dict(os.environ, ENABLED):
        result = await list_contact_tags()
    assert [t["name"] for t in result] == ["x"]
    assert mock_redmine.engine.request.call_count == 3


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
@patch("redmine_mcp_server._client.redmine")
async def test_fallback_forbidden_maps_to_error(mock_redmine):
    mock_redmine.engine.request.side_effect = [
        ResourceNotFoundError(),
        ForbiddenError(),
    ]
    with patch.dict(os.environ, ENABLED):
        result = await list_contact_tags()
    assert "Access denied" in result["error"]
