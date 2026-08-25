"""Unit tests for list_crm_queries (saved RedmineUP CRM contact/deal queries)."""

import os
import sys
from unittest.mock import patch

import pytest
from redminelib.exceptions import ResourceNotFoundError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.crm_queries import list_crm_queries  # noqa: E402

CRM_ON = {"REDMINE_CRM_ENABLED": "true", "REDMINE_DEALS_ENABLED": "false"}
DEALS_ON = {"REDMINE_CRM_ENABLED": "false", "REDMINE_DEALS_ENABLED": "true"}
BOTH_ON = {"REDMINE_CRM_ENABLED": "true", "REDMINE_DEALS_ENABLED": "true"}
BOTH_OFF = {"REDMINE_CRM_ENABLED": "false", "REDMINE_DEALS_ENABLED": "false"}
URL = "http://localhost:3000"
PAYLOAD = {
    "queries": [
        {"id": 4, "name": "Hot deals", "is_public": True, "project_id": None},
        {"id": 5, "name": "Mine", "is_public": False, "project_id": 3},
    ],
    "total_count": 2,
    "offset": 0,
    "limit": 25,
}


@pytest.mark.asyncio
async def test_both_off():
    with patch.dict(os.environ, BOTH_OFF):
        r = await list_crm_queries(object_type="deal")
    assert "REDMINE_CRM_ENABLED" in r["error"]


@pytest.mark.asyncio
async def test_deal_queries_need_deals_flag():
    with patch.dict(os.environ, CRM_ON):
        r = await list_crm_queries(object_type="deal")
    assert "REDMINE_DEALS_ENABLED" in r["error"]


@pytest.mark.asyncio
async def test_contact_queries_need_crm_flag():
    with patch.dict(os.environ, DEALS_ON):
        r = await list_crm_queries(object_type="contact")
    assert "REDMINE_CRM_ENABLED" in r["error"]


@pytest.mark.asyncio
async def test_rejects_unknown_type():
    with patch.dict(os.environ, BOTH_ON):
        r = await list_crm_queries(object_type="issue")
    assert "object_type" in r["error"]


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", URL)
@patch("redmine_mcp_server._client.redmine")
async def test_lists_with_params(mock):
    mock.engine.request.return_value = PAYLOAD
    with patch.dict(os.environ, BOTH_ON):
        r = await list_crm_queries(object_type="deal", limit=10, offset=20)
    assert r == [
        {"id": 4, "name": "Hot deals", "is_public": True, "project_id": None},
        {"id": 5, "name": "Mine", "is_public": False, "project_id": 3},
    ]
    args = mock.engine.request.call_args
    assert args.args == ("get", f"{URL}/crm_queries.json")
    assert args.kwargs["params"] == {"object_type": "deal", "limit": 10, "offset": 20}


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_rejects_bad_paging(kwargs):
    with patch.dict(os.environ, BOTH_ON):
        r = await list_crm_queries(object_type="deal", **kwargs)
    assert "error" in r


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.REDMINE_URL", URL)
@patch("redmine_mcp_server._client.redmine")
async def test_not_found_maps(mock):
    mock.engine.request.side_effect = ResourceNotFoundError()
    with patch.dict(os.environ, BOTH_ON):
        r = await list_crm_queries(object_type="contact")
    assert "not found" in r["error"]
