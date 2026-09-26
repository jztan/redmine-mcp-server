"""Unit tests for RedmineUP Products plugin support."""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._env import _is_products_enabled  # noqa: E402
from redmine_mcp_server.tools.products import (  # noqa: E402
    manage_product,
)


def _make_product(product_id: int = 1, name: str = "Widget") -> dict:
    """A product in the shape ``products/show.api.rsb`` renders.

    The plugin names the tags ``tag_list`` and the timestamps ``created_at``
    and ``updated_at``, and renders ``author`` and ``custom_fields``.
    """
    return {
        "id": product_id,
        "name": name,
        "description": "A widget",
        "code": f"W-{product_id}",
        "price": 9.99,
        "currency": "USD",
        "status_id": 1,
        "project": {"id": 5, "name": "Catalog"},
        "category": {"id": 2, "code": "HW", "name": "Hardware"},
        "author": {"id": 3, "name": "Product Owner"},
        "tag_list": ["alpha"],
        "custom_fields": [{"id": 1, "name": "Warranty", "value": "2 years"}],
        "created_at": "2026-04-20T10:00:00Z",
        "updated_at": "2026-04-20T11:00:00Z",
    }


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


class TestIsProductsEnabled:
    def test_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDMINE_PRODUCTS_ENABLED", None)
            assert _is_products_enabled() is False

    def test_true_when_env_set(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            assert _is_products_enabled() is True


# ---------------------------------------------------------------------------
# list_products
# ---------------------------------------------------------------------------


class TestManageProductList:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_all(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "products": [_make_product(1), _make_product(2, "Gadget")]
        }
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="list",
            )

        assert isinstance(result, list)
        assert len(result) == 2
        assert "Widget" in result[0]["name"]
        mock_redmine.engine.request.assert_called_once_with(
            "get",
            "http://localhost:3000/products.json",
            params={"limit": 100},
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_by_project(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"products": []}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            await manage_product(action="list", project_id="catalog")

        mock_redmine.engine.request.assert_called_once_with(
            "get",
            "http://localhost:3000/projects/catalog/products.json",
            params={"limit": 100},
        )

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "false"}):
            result = await manage_product(
                action="list",
            )
        assert "error" in result
        assert "REDMINE_PRODUCTS_ENABLED" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_limit(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", limit=0)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_handles_api_error(self, mock_redmine):
        mock_redmine.engine.request.side_effect = Exception("boom")
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="list",
            )
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_clamps_limit_to_100(self, mock_redmine):
        """Redmine caps `limit` at 100 server-side; values above are clamped."""
        mock_redmine.engine.request.return_value = {"products": []}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            await manage_product(action="list", limit=500)

        call_kwargs = mock_redmine.engine.request.call_args.kwargs
        assert call_kwargs["params"]["limit"] == 100

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_slices_oversized_response(self, mock_redmine):
        """Defensive slice: even if Redmine returned more than `limit`, the
        tool truncates to `limit`."""
        many = [_make_product(i) for i in range(200)]
        mock_redmine.engine.request.return_value = {"products": many}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", limit=50)

        assert isinstance(result, list)
        assert len(result) == 50

    @pytest.mark.asyncio
    async def test_rejects_empty_project_id(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", project_id="")
        assert "error" in result
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_project_id_with_slash(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", project_id="foo/../bar")
        assert "error" in result
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_project_id_with_query_chars(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", project_id="foo?x=1")
        assert "error" in result
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_project_id_with_uppercase(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", project_id="MyProject")
        assert "error" in result
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_accepts_valid_string_project_id(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"products": []}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", project_id="my-project_42")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_accepts_integer_project_id(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"products": []}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list", project_id=42)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# get_product
# ---------------------------------------------------------------------------


class TestManageProductGet:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"product": _make_product(42)}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="get", product_id=42)
        assert result["id"] == 42
        assert "Widget" in result["name"]

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "false"}):
            result = await manage_product(action="get", product_id=1)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_id(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="get", product_id=-5)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_not_found(self, mock_redmine):
        mock_redmine.engine.request.return_value = {}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="get", product_id=999)
        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# add_product
# ---------------------------------------------------------------------------


class TestManageProductCreate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_add_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"product": _make_product(1)}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="create", name="Widget", price=9.99)

        assert result["id"] == 1
        # Verify POST body shape
        call_kwargs = mock_redmine.engine.request.call_args.kwargs
        body = json.loads(call_kwargs["data"])
        assert body["product"]["name"] == "Widget"
        assert body["product"]["price"] == 9.99
        assert body["product"]["status_id"] == 1

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {
                "REDMINE_MCP_READ_ONLY": "true",
                "REDMINE_PRODUCTS_ENABLED": "true",
            },
        ):
            result = await manage_product(action="create", name="X")
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "false"}):
            result = await manage_product(action="create", name="X")
        assert "REDMINE_PRODUCTS_ENABLED" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_name(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="create", name="")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_status_id(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="create", name="X", status_id=-1)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_unknown_status_id(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="create", name="Widget", status_id=999)
        assert "error" in result
        assert "status_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_zero_status_id(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="create", name="Widget", status_id=0)
        assert "error" in result
        assert "status_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_bool_status_id(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="create", name="Widget", status_id=True
            )
        assert "error" in result
        assert "status_id" in result["error"]


# ---------------------------------------------------------------------------
# edit_product
# ---------------------------------------------------------------------------


class TestManageProductUpdate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_edit_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="update", product_id=1, fields={"name": "New", "price": 19.99}
            )

        assert result["success"] is True
        assert set(result["updated_fields"]) == {"name", "price"}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_filters_unknown_fields(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="update",
                product_id=1,
                fields={"name": "New", "evil_field": "bad", "rogue": "x"},
            )

        # Only "name" should be in updated_fields
        assert result["updated_fields"] == ["name"]
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert "evil_field" not in body["product"]

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_PRODUCTS_ENABLED": "true"},
        ):
            result = await manage_product(
                action="update", product_id=1, fields={"name": "X"}
            )
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_writable_fields(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="update", product_id=1, fields={"unknown": "x", "rogue": "y"}
            )
        assert "error" in result
        assert "writable fields" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_id(self):
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="update", product_id=-1, fields={"name": "X"}
            )
        assert "error" in result


# ---------------------------------------------------------------------------
# Payload keys: the fields the products API renders under its own names
# ---------------------------------------------------------------------------


class TestProductPayloadKeys:
    """The serializer reads the keys ``products/*.api.rsb`` actually renders.

    It read ``tags``, ``created_on`` and ``updated_on``, which the plugin
    never sends, so all three came back empty for every product; ``author``
    and ``custom_fields`` were dropped outright, though ``custom_fields`` and
    ``tag_list`` are writable through the tool (#ISSUE).
    """

    def _serialize(self, product):
        from redmine_mcp_server.tools.products import _product_to_dict

        return _product_to_dict(product)

    def test_tag_list_is_read(self):
        result = self._serialize(_make_product())
        assert result["tags"] == ["alpha"]

    def test_tag_list_as_comma_separated_string(self):
        product = _make_product()
        product["tag_list"] = "alpha, beta,,"
        assert self._serialize(product)["tags"] == ["alpha", "beta"]

    def test_legacy_tags_key_still_read(self):
        product = _make_product()
        del product["tag_list"]
        product["tags"] = ["legacy"]
        assert self._serialize(product)["tags"] == ["legacy"]

    def test_no_tags_is_empty_list(self):
        product = _make_product()
        del product["tag_list"]
        assert self._serialize(product)["tags"] == []

    def test_empty_tag_list_is_empty(self):
        product = _make_product()
        product["tag_list"] = []
        assert self._serialize(product)["tags"] == []

    def test_timestamps_read_from_created_at_and_updated_at(self):
        result = self._serialize(_make_product())
        assert result["created_on"] == "2026-04-20T10:00:00Z"
        assert result["updated_on"] == "2026-04-20T11:00:00Z"

    def test_legacy_timestamp_keys_still_read(self):
        product = _make_product()
        del product["created_at"], product["updated_at"]
        product["created_on"] = "2026-01-01T00:00:00Z"
        product["updated_on"] = "2026-01-02T00:00:00Z"
        result = self._serialize(product)
        assert result["created_on"] == "2026-01-01T00:00:00Z"
        assert result["updated_on"] == "2026-01-02T00:00:00Z"

    def test_missing_timestamps_are_none(self):
        product = _make_product()
        del product["created_at"], product["updated_at"]
        result = self._serialize(product)
        assert result["created_on"] is None
        assert result["updated_on"] is None

    def test_author_is_returned(self):
        result = self._serialize(_make_product())
        assert result["author"] == {"id": 3, "name": "Product Owner"}

    def test_missing_or_malformed_author_is_none(self):
        product = _make_product()
        del product["author"]
        assert self._serialize(product)["author"] is None
        product["author"] = "not a ref"
        assert self._serialize(product)["author"] is None

    def test_custom_fields_are_returned(self):
        result = self._serialize(_make_product())
        assert result["custom_fields"] == [
            {"id": 1, "name": "Warranty", "value": "2 years"}
        ]

    def test_multiple_custom_field_value_is_kept_as_list(self):
        product = _make_product()
        product["custom_fields"] = [
            {"id": 4, "name": "Regions", "multiple": True, "value": ["EU", "US"]}
        ]
        assert self._serialize(product)["custom_fields"] == [
            {"id": 4, "name": "Regions", "value": ["EU", "US"]}
        ]

    def test_no_custom_fields_key_is_empty_list(self):
        """``render_api_custom_values`` omits the key when there are none."""
        product = _make_product()
        del product["custom_fields"]
        assert self._serialize(product)["custom_fields"] == []

    def test_scalar_custom_fields_is_not_iterated(self):
        product = _make_product()
        product["custom_fields"] = "garbage"
        assert self._serialize(product)["custom_fields"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_returns_the_fields(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"product": _make_product(42)}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="get", product_id=42)
        assert result["tags"] == ["alpha"]
        assert result["custom_fields"][0]["value"] == "2 years"
        assert result["author"]["id"] == 3
        assert result["created_on"] == "2026-04-20T10:00:00Z"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_create_reads_back_what_it_wrote(self, mock_redmine):
        """A tag or custom field set through ``create`` is in its response."""
        mock_redmine.engine.request.return_value = {"product": _make_product(7)}
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(
                action="create",
                name="Widget",
                tag_list="alpha",
                custom_fields=[{"id": 1, "value": "2 years"}],
            )
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert body["product"]["tag_list"] == "alpha"
        assert body["product"]["custom_fields"] == [{"id": 1, "value": "2 years"}]
        assert result["tags"] == ["alpha"]
        assert result["custom_fields"] == [
            {"id": 1, "name": "Warranty", "value": "2 years"}
        ]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_returns_the_fields_on_every_row(self, mock_redmine):
        """``products/index.api.rsb`` renders the same keys on each row."""
        mock_redmine.engine.request.return_value = {
            "products": [_make_product(1), _make_product(2, "Gadget")]
        }
        with patch.dict(os.environ, {"REDMINE_PRODUCTS_ENABLED": "true"}):
            result = await manage_product(action="list")
        assert [row["tags"] for row in result] == [["alpha"], ["alpha"]]
        assert all(row["custom_fields"] for row in result)
        assert all(row["updated_on"] for row in result)
        assert mock_redmine.engine.request.call_count == 1
