"""Unit tests for list_deal_statuses (CRM PRO deal statuses and categories)."""

import os
import sys
from unittest.mock import patch

import pytest
from redminelib.exceptions import ForbiddenError, ResourceNotFoundError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.deals import (  # noqa: E402
    _deal_category_to_dict,
    _deal_status_to_dict,
    list_deal_statuses,
)

ENABLED = {"REDMINE_DEALS_ENABLED": "true"}


def _status(status_id=1, name="New", status_type=0):
    """Shaped like the plugin's app/views/deal_statuses/index.api.rsb."""
    return {
        "id": status_id,
        "name": name,
        "position": status_id,
        "is_default": status_id == 1,
        "status_type": status_type,
        "color": "FFFFFF",
    }


class TestSerializers:
    def test_status_renders_type_label_and_keeps_id(self):
        d = _deal_status_to_dict(_status(3, "Won", 1))
        assert d == {
            "id": 3,
            "name": "Won",
            "position": 3,
            "is_default": False,
            "status_type": "won",
            "status_type_id": 1,
            "color": "FFFFFF",
        }

    @pytest.mark.parametrize("code,label", [(0, "open"), (1, "won"), (2, "lost")])
    def test_status_type_labels(self, code, label):
        assert _deal_status_to_dict(_status(1, "x", code))["status_type"] == label

    def test_unknown_status_type_is_none_not_crash(self):
        d = _deal_status_to_dict(_status(1, "x", 9))
        assert d["status_type"] is None and d["status_type_id"] == 9

    def test_status_missing_fields(self):
        assert _deal_status_to_dict({"id": 5})["name"] == ""

    def test_category(self):
        assert _deal_category_to_dict({"id": 7, "name": "Upsell"}) == {
            "id": 7,
            "name": "Upsell",
        }


def _route(statuses=None, categories=None, statuses_exc=None, categories_exc=None):
    """Side effect for engine.request keyed on the URL."""

    def handler(method, url, **kwargs):
        assert method == "get"
        if url.endswith("/deal_statuses.json"):
            if statuses_exc:
                raise statuses_exc
            return {"deal_statuses": statuses or []}
        if url.endswith("/deal_categories.json"):
            if categories_exc:
                raise categories_exc
            return {"deal_categories": categories or [], "total_count": 0}
        raise AssertionError(f"unexpected url {url}")

    return handler


class TestListDealStatuses:
    @pytest.mark.asyncio
    async def test_disabled_flag_returns_error(self):
        with patch.dict(os.environ, {"REDMINE_DEALS_ENABLED": "false"}):
            result = await list_deal_statuses()
        assert "REDMINE_DEALS_ENABLED" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_statuses_only_without_project(self, mock_redmine):
        mock_redmine.engine.request.side_effect = _route(
            statuses=[_status(1, "New", 0), _status(2, "Won", 1)]
        )
        with patch.dict(os.environ, ENABLED):
            result = await list_deal_statuses()
        assert [s["name"] for s in result["statuses"]] == ["New", "Won"]
        assert "categories" not in result
        assert "statuses_error" not in result
        assert mock_redmine.engine.request.call_count == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_project_adds_categories(self, mock_redmine):
        mock_redmine.engine.request.side_effect = _route(
            statuses=[_status()], categories=[{"id": 7, "name": "Upsell"}]
        )
        with patch.dict(os.environ, ENABLED):
            result = await list_deal_statuses(project_id="sales")
        assert result["categories"] == [{"id": 7, "name": "Upsell"}]
        assert result["project_id"] == "sales"
        urls = [c.args[1] for c in mock_redmine.engine.request.call_args_list]
        assert urls == [
            "http://localhost:3000/deal_statuses.json",
            "http://localhost:3000/projects/sales/deal_categories.json",
        ]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_admin_only_statuses_is_partial_success(self, mock_redmine):
        """The plugin's DealStatusesController#index is require_admin."""
        mock_redmine.engine.request.side_effect = _route(
            statuses_exc=ForbiddenError(), categories=[{"id": 7, "name": "Upsell"}]
        )
        with patch.dict(os.environ, ENABLED):
            result = await list_deal_statuses(project_id=3)
        assert "error" not in result
        assert result["statuses"] is None
        assert "administrator" in result["statuses_error"]
        assert result["categories"] == [{"id": 7, "name": "Upsell"}]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_unknown_project_is_error(self, mock_redmine):
        mock_redmine.engine.request.side_effect = _route(
            statuses=[_status()], categories_exc=ResourceNotFoundError()
        )
        with patch.dict(os.environ, ENABLED):
            result = await list_deal_statuses(project_id="nope")
        assert result == {"error": "Project nope not found."}

    @pytest.mark.asyncio
    async def test_rejects_bad_project_id(self):
        with patch.dict(os.environ, ENABLED):
            result = await list_deal_statuses(project_id="a/../b")
        assert "project_id" in result["error"]
