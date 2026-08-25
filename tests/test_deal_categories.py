"""Unit tests for manage_deal_category (RedmineUP CRM deal categories)."""

import json
import os
import sys
from unittest.mock import patch

import pytest
from redminelib.exceptions import ResourceNotFoundError, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.deals import manage_deal_category  # noqa: E402

ON = {"REDMINE_DEALS_ENABLED": "true", "REDMINE_MCP_READ_ONLY": "false"}
URL = "http://localhost:3000"


def _body(mock):
    return json.loads(mock.engine.request.call_args.kwargs["data"])


class TestGating:
    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_DEALS_ENABLED": "false"}):
            r = await manage_deal_category(action="list", project_id=1)
        assert "REDMINE_DEALS_ENABLED" in r["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["create", "update", "delete"])
    async def test_writes_blocked_in_read_only(self, action):
        with patch.dict(os.environ, {**ON, "REDMINE_MCP_READ_ONLY": "true"}):
            r = await manage_deal_category(
                action=action, project_id=1, category_id=1, name="x"
            )
        assert "read-only" in r["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="get")
        assert "Invalid action" in r["error"]


class TestList:
    @pytest.mark.asyncio
    async def test_requires_project(self):
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="list")
        assert "project_id" in r["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_lists(self, mock):
        mock.engine.request.return_value = {
            "deal_categories": [{"id": 1, "name": "A"}],
            "total_count": 1,
        }
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="list", project_id="sales")
        assert r == [{"id": 1, "name": "A"}]
        assert mock.engine.request.call_args.args == (
            "get",
            f"{URL}/projects/sales/deal_categories.json",
        )


class TestCreate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_creates(self, mock):
        mock.engine.request.return_value = {"category": {"id": 7, "name": "Upsell"}}
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(
                action="create", project_id="sales", name="Upsell"
            )
        assert r == {"id": 7, "name": "Upsell", "project_id": "sales"}
        args = mock.engine.request.call_args
        assert args.args == ("post", f"{URL}/projects/sales/deal_categories.json")
        assert args.kwargs["headers"] == {"Content-Type": "application/json"}
        assert _body(mock) == {"category": {"name": "Upsell"}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs,field",
        [
            ({"name": "x"}, "project_id"),
            ({"project_id": 1}, "name"),
            ({"project_id": 1, "name": "  "}, "name"),
            ({"project_id": 1, "name": "x" * 31}, "30"),
        ],
    )
    async def test_validation(self, kwargs, field):
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="create", **kwargs)
        assert field in r["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_duplicate_422_passes_through(self, mock):
        mock.engine.request.side_effect = ValidationError("Name has already been taken")
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="create", project_id=1, name="A")
        assert "already been taken" in r["error"]


class TestUpdate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_updates(self, mock):
        mock.engine.request.return_value = None
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="update", category_id=7, name="B")
        assert r == {"success": True, "category_id": 7, "updated_fields": ["name"]}
        args = mock.engine.request.call_args
        assert args.args == ("put", f"{URL}/deal_categories/7.json")
        assert _body(mock) == {"category": {"name": "B"}}

    @pytest.mark.asyncio
    async def test_requires_id_and_name(self):
        with patch.dict(os.environ, ON):
            assert (
                "category_id"
                in (await manage_deal_category(action="update", name="x"))["error"]
            )
            assert (
                "name"
                in (await manage_deal_category(action="update", category_id=1))["error"]
            )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_not_found(self, mock):
        mock.engine.request.side_effect = ResourceNotFoundError()
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="update", category_id=9, name="B")
        assert r == {"error": "Deal category 9 not found."}


class TestDelete:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_delete_without_reassign(self, mock):
        mock.engine.request.return_value = None
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(action="delete", category_id=7)
        assert r["success"] is True and r["category_id"] == 7
        assert "uncategorised" in r["message"]
        args = mock.engine.request.call_args
        assert args.args == ("delete", f"{URL}/deal_categories/7.json")
        assert not args.kwargs.get("params")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_delete_with_reassign(self, mock):
        mock.engine.request.return_value = None
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(
                action="delete", category_id=7, reassign_to_id=1
            )
        assert "reassigned to category 1" in r["message"]
        assert mock.engine.request.call_args.kwargs["params"] == {"reassign_to_id": 1}

    @pytest.mark.asyncio
    async def test_rejects_bad_reassign(self):
        with patch.dict(os.environ, ON):
            r = await manage_deal_category(
                action="delete", category_id=7, reassign_to_id=0
            )
        assert "reassign_to_id" in r["error"]
