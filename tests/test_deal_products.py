"""Unit tests for add_deal_product and deal ``lines`` serialization."""

import json
import os
import sys
from unittest.mock import patch

import pytest
from redminelib.exceptions import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.deals import (  # noqa: E402
    _deal_line_to_dict,
    _deal_to_dict,
    add_deal_product,
)

ON = {
    "REDMINE_DEALS_ENABLED": "true",
    "REDMINE_PRODUCTS_ENABLED": "true",
    "REDMINE_MCP_READ_ONLY": "false",
}
URL = "http://localhost:3000"
LINE = {
    "id": 1,
    "position": 1,
    "product": {"id": 1, "name": "E2E widget"},
    "description": "Consulting",
    "quantity": "3.0",
    "tax": "20.0",
    "discount": None,
    "price": "10.5",
    "total": 31.5,
}


class TestLines:
    def test_line_to_dict(self):
        d = _deal_line_to_dict(LINE)
        assert d["product"] == {"id": 1, "name": "E2E widget"}
        assert (
            "Consulting" in d["description"]
            and "<insecure-content-" in d["description"]
        )
        assert d["quantity"] == "3.0" and d["total"] == 31.5 and d["discount"] is None

    def test_line_without_product(self):
        d = _deal_line_to_dict({**LINE, "product": None})
        assert d["product"] is None

    def test_deal_lines_passthrough_only_when_present(self):
        assert "lines" not in _deal_to_dict({"id": 1, "name": "x"})
        d = _deal_to_dict({"id": 1, "name": "x", "lines": [LINE]})
        assert len(d["lines"]) == 1 and d["lines"][0]["id"] == 1


class TestGating:
    @pytest.mark.asyncio
    async def test_deals_off(self):
        with patch.dict(os.environ, {**ON, "REDMINE_DEALS_ENABLED": "false"}):
            r = await add_deal_product(deal_id=1, product_id=1)
        assert "REDMINE_DEALS_ENABLED" in r["error"]

    @pytest.mark.asyncio
    async def test_products_off(self):
        with patch.dict(os.environ, {**ON, "REDMINE_PRODUCTS_ENABLED": "false"}):
            r = await add_deal_product(deal_id=1, product_id=1)
        assert "REDMINE_PRODUCTS_ENABLED" in r["error"]

    @pytest.mark.asyncio
    async def test_read_only(self):
        with patch.dict(os.environ, {**ON, "REDMINE_MCP_READ_ONLY": "true"}):
            r = await add_deal_product(deal_id=1, product_id=1)
        assert "read-only" in r["error"].lower()


class TestAdd:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_product_line(self, mock):
        mock.engine.request.return_value = None
        with patch.dict(os.environ, ON):
            r = await add_deal_product(deal_id=11, product_id=1, quantity=3)
        assert r == {
            "success": True,
            "deal_id": 11,
            "line": {"product_id": 1, "quantity": 3},
        }
        args = mock.engine.request.call_args
        assert args.args == ("put", f"{URL}/deals/11/add_product.json")
        assert args.kwargs["headers"] == {"Content-Type": "application/json"}
        assert json.loads(args.kwargs["data"]) == {
            "product": {"product_id": 1, "quantity": 3}
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_free_form_line_coerces_price(self, mock):
        mock.engine.request.return_value = None
        with patch.dict(os.environ, ON):
            r = await add_deal_product(
                deal_id=11,
                description="Consulting",
                quantity=2,
                price=100.0,
                tax=20,
                discount=10,
            )
        assert r["success"] is True
        body = json.loads(mock.engine.request.call_args.kwargs["data"])["product"]
        assert body == {
            "description": "Consulting",
            "quantity": 2,
            "price": "100.0",
            "tax": 20,
            "discount": 10,
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs,field",
        [
            ({"product_id": 1}, "deal_id"),
            ({"deal_id": 1}, "product_id"),
            ({"deal_id": 1, "product_id": 0}, "product_id"),
            ({"deal_id": 1, "description": "x", "quantity": 0}, "quantity"),
            ({"deal_id": 1, "description": "x", "tax": 101}, "tax"),
            ({"deal_id": 1, "description": "x", "discount": -1}, "discount"),
            ({"deal_id": 1, "description": "x", "price": float("nan")}, "price"),
        ],
    )
    async def test_validation(self, kwargs, field):
        with patch.dict(os.environ, ON):
            r = await add_deal_product(**kwargs)
        assert field in r["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_422_passes_through(self, mock):
        mock.engine.request.side_effect = ValidationError(
            "Tax must be less than or equal to 100"
        )
        with patch.dict(os.environ, ON):
            r = await add_deal_product(deal_id=11, product_id=1)
        assert "Tax must be" in r["error"]
