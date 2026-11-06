"""Unit tests for RedmineUP Products plugin orders support (manage_order)."""

import os
import sys
from unittest.mock import patch

import pytest
from fastmcp import Client
from redminelib.exceptions import ForbiddenError, ResourceNotFoundError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server import server as _server  # noqa: E402
from redmine_mcp_server._decorators import ACTION_SPECS, ActionMode  # noqa: E402
from redmine_mcp_server._env import (  # noqa: E402
    SERVER_INFO_PLUGIN_FLAGS,
    _is_orders_enabled,
)
from redmine_mcp_server._plugin_visibility import (  # noqa: E402
    apply_plugin_visibility,
    enable_all_plugin_tools,
)
from redmine_mcp_server.oauth_scopes import (  # noqa: E402
    ORDERS_READ_SCOPES,
    READ_SCOPES,
    TOOL_SCOPES,
    WRITE_SCOPES,
    advertised_scopes,
    scopes_for_action,
)
from redmine_mcp_server.tools.orders import (  # noqa: E402
    _order_to_dict,
    manage_order,
)

ON = {"REDMINE_ORDERS_ENABLED": "true"}
_ORDER_SCOPES = {"view_orders", "view_orders_list"}
_URL = "http://localhost:3000"


def _make_order(order_id: int = 1, number: str = "ORD-1", **extra) -> dict:
    """An order shaped like the plugin's app/views/orders/index.api.rsb."""
    order = {
        "id": order_id,
        "number": number,
        "subject": "Annual licence",
        "order_date": "2026-10-01",
        "completed_date": None,
        "amount": 1200.5,
        "currency": "USD",
        "description": "Seats for 2027",
        "contact": {"id": 42, "name": "ACME"},
        "project": {"id": 3, "name": "Sales"},
        "status": {"id": 1, "name": "New", "is_closed": False},
        "author": {"id": 1, "name": "Admin"},
        "assigned_to": {"id": 5, "name": "Bob"},
        "custom_fields": [
            {"id": 7, "name": "Region", "value": "EMEA"},
            {"id": 8, "name": "PO", "value": "PO-9"},
        ],
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-02T11:00:00Z",
    }
    order.update(extra)
    return order


def _line(line_id: int = 11, description: str = "Seats") -> dict:
    return {
        "id": line_id,
        "position": 1,
        "product": {"id": 4, "name": "Widget Pro"},
        "description": description,
        "quantity": 2.0,
        "tax": 10.0,
        "discount": 0.0,
        "price": 600.25,
        "total": 1200.5,
    }


def _wrapped(value) -> bool:
    return isinstance(value, str) and value.startswith("<insecure-content-")


def _params(mock_redmine) -> dict:
    return mock_redmine.engine.request.call_args.kwargs["params"]


def _url(mock_redmine) -> str:
    return mock_redmine.engine.request.call_args.args[1]


# ---------------------------------------------------------------------------
# Flag, visibility, dispatch
# ---------------------------------------------------------------------------


class TestOrdersFlag:
    def test_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDMINE_ORDERS_ENABLED", None)
            assert _is_orders_enabled() is False

    def test_true_when_env_set(self):
        with patch.dict(os.environ, ON):
            assert _is_orders_enabled() is True

    def test_not_implied_by_the_products_flag(self):
        """Orders are their own project module, so their own flag."""
        with patch.dict(
            os.environ,
            {"REDMINE_PRODUCTS_ENABLED": "true", "REDMINE_ORDERS_ENABLED": "false"},
        ):
            assert _is_orders_enabled() is False

    def test_reported_in_server_info_flags(self):
        assert SERVER_INFO_PLUGIN_FLAGS["orders"] is _is_orders_enabled

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["list", "get"])
    async def test_disabled_returns_error(self, action):
        with patch.dict(os.environ, {"REDMINE_ORDERS_ENABLED": "false"}):
            result = await manage_order(action=action, order_id=1)
        assert "REDMINE_ORDERS_ENABLED" in result["error"]

    @pytest.mark.asyncio
    async def test_hidden_from_tools_list_when_off(self):
        try:
            with patch.dict(os.environ, {"REDMINE_ORDERS_ENABLED": "false"}):
                apply_plugin_visibility(_server.mcp)
            async with Client(_server.mcp) as client:
                hidden = {t.name for t in await client.list_tools()}
            with patch.dict(os.environ, ON):
                apply_plugin_visibility(_server.mcp)
            async with Client(_server.mcp) as client:
                shown = {t.name for t in await client.list_tools()}
        finally:
            enable_all_plugin_tools(_server.mcp)
        assert "manage_order" not in hidden
        assert "manage_order" in shown

    def test_both_actions_are_reads(self):
        assert ACTION_SPECS["manage_order"] == {
            "list": ActionMode.READ,
            "get": ActionMode.READ,
        }

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="create")
        assert "Invalid action" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_read_only_mode_leaves_both_actions_working(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": [], "total_count": 0}
        with patch.dict(os.environ, {**ON, "REDMINE_MCP_READ_ONLY": "true"}):
            result = await manage_order(action="list")
        assert result["orders"] == []


# ---------------------------------------------------------------------------
# OAuth scopes
# ---------------------------------------------------------------------------


class TestOrderScopes:
    @pytest.mark.parametrize("read_only", ["true", "false"])
    def test_flag_adds_exactly_the_order_scopes(self, read_only):
        base_env = {
            "REDMINE_ORDERS_ENABLED": "false",
            "REDMINE_MCP_READ_ONLY": read_only,
        }
        with patch.dict(os.environ, base_env):
            without = advertised_scopes()
        with patch.dict(os.environ, {**base_env, "REDMINE_ORDERS_ENABLED": "true"}):
            with_orders = advertised_scopes()
        assert set(with_orders) - set(without) == _ORDER_SCOPES
        assert set(without) <= set(with_orders)

    def test_nothing_advertised_when_off(self):
        with patch.dict(os.environ, {"REDMINE_ORDERS_ENABLED": "false"}):
            scopes = set(advertised_scopes())
        assert not (_ORDER_SCOPES & scopes)

    def test_products_flag_alone_advertises_no_order_scope(self):
        with patch.dict(
            os.environ,
            {"REDMINE_PRODUCTS_ENABLED": "true", "REDMINE_ORDERS_ENABLED": "false"},
        ):
            scopes = set(advertised_scopes())
        assert not (_ORDER_SCOPES & scopes)

    def test_order_scopes_absent_from_core_scope_lists(self):
        core = set(READ_SCOPES) | set(WRITE_SCOPES)
        assert not (_ORDER_SCOPES & core)

    def test_each_action_requires_the_scope_its_controller_checks(self):
        # orders#index authorizes view_orders_list against the token; the
        # view_orders filter on its rows reads the user's roles, not the
        # token, so list must not demand view_orders as a scope.
        entry = TOOL_SCOPES["manage_order"]
        assert entry == {
            "list": frozenset({"view_orders_list"}),
            "get": frozenset({"view_orders"}),
        }
        assert scopes_for_action(entry, {"action": "list"}) == {"view_orders_list"}
        assert set(ORDERS_READ_SCOPES) == _ORDER_SCOPES


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestOrderToDict:
    def test_keys_match_the_plugin_template(self):
        result = _order_to_dict(_make_order(), include_custom_fields=True)
        assert result["id"] == 1
        assert result["number"] == "ORD-1"
        assert result["order_date"] == "2026-10-01"
        assert result["completed_date"] is None
        assert result["amount"] == 1200.5
        assert result["currency"] == "USD"
        assert result["contact"] == {"id": 42, "name": "ACME"}
        assert result["project"] == {"id": 3, "name": "Sales"}
        assert result["status"] == {"id": 1, "name": "New", "is_closed": False}
        assert result["author"] == {"id": 1, "name": "Admin"}
        assert result["assigned_to"] == {"id": 5, "name": "Bob"}
        assert result["created_at"] == "2026-10-01T10:00:00Z"
        assert result["updated_at"] == "2026-10-02T11:00:00Z"
        assert result["custom_fields"] == [
            {"id": 7, "name": "Region", "value": "EMEA"},
            {"id": 8, "name": "PO", "value": "PO-9"},
        ]

    def test_description_is_wrapped(self):
        result = _order_to_dict(_make_order())
        assert _wrapped(result["description"])
        assert "Seats for 2027" in result["description"]

    def test_label_fields_are_verbatim(self):
        """number, subject and ref names are label-shaped (#109)."""
        result = _order_to_dict(_make_order())
        assert result["number"] == "ORD-1"
        assert result["subject"] == "Annual licence"
        assert result["contact"]["name"] == "ACME"

    def test_absent_refs_become_none(self):
        order = _make_order()
        for key in ("contact", "project", "status", "author", "assigned_to"):
            del order[key]
        result = _order_to_dict(order)
        for key in ("contact", "project", "status", "author", "assigned_to"):
            assert result[key] is None

    def test_lines_absent_when_payload_has_none(self):
        result = _order_to_dict(_make_order())
        assert "lines" not in result
        assert "comments" not in result
        assert "attachments" not in result

    def test_lines_serialized_with_product_refs(self):
        result = _order_to_dict(_make_order(lines=[_line()]))
        (line,) = result["lines"]
        assert line["id"] == 11
        assert line["position"] == 1
        assert line["product"] == {"id": 4, "name": "Widget Pro"}
        assert line["quantity"] == 2.0
        assert line["tax"] == 10.0
        assert line["discount"] == 0.0
        assert line["price"] == 600.25
        assert line["total"] == 1200.5
        assert _wrapped(line["description"])

    def test_free_form_line_has_no_product(self):
        line = _line()
        del line["product"]
        result = _order_to_dict(_make_order(lines=[line]))
        assert result["lines"][0]["product"] is None

    def test_non_dict_payload_is_survivable(self):
        assert _order_to_dict(None) == {}
        assert _order_to_dict("nope") == {}

    def test_custom_fields_elided_by_default(self):
        result = _order_to_dict(_make_order())
        assert result["custom_fields"] is None
        assert result["custom_fields_count"] == 2

    def test_custom_field_ids_narrow_and_imply_inclusion(self):
        result = _order_to_dict(_make_order(), custom_field_ids=[8])
        assert result["custom_fields"] == [{"id": 8, "name": "PO", "value": "PO-9"}]
        assert "custom_fields_count" not in result

    def test_no_custom_fields_key_reads_as_empty(self):
        """render_api_custom_values omits the key when there are none."""
        order = _make_order()
        del order["custom_fields"]
        assert _order_to_dict(order, include_custom_fields=True)["custom_fields"] == []
        assert _order_to_dict(order)["custom_fields_count"] == 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestManageOrderList:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_default_call_sends_no_status_filter(self, mock_redmine):
        """No status_id sent, so OrderQuery applies its own open-only default."""
        mock_redmine.engine.request.return_value = {
            "orders": [_make_order(1), _make_order(2, "ORD-2")],
            "total_count": 2,
            "offset": 0,
            "limit": 100,
        }
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list")

        assert _url(mock_redmine) == f"{_URL}/orders.json"
        assert _params(mock_redmine) == {"limit": 100}
        assert [o["number"] for o in result["orders"]] == ["ORD-1", "ORD-2"]
        assert result["pagination"]["total"] == 2
        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    @pytest.mark.parametrize("operator", ["o", "c", "*"])
    async def test_status_operators_forwarded(self, mock_redmine, operator):
        mock_redmine.engine.request.return_value = {"orders": []}
        with patch.dict(os.environ, ON):
            await manage_order(action="list", status_id=operator)
        assert _params(mock_redmine)["status_id"] == operator

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_numeric_status_forwarded(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": []}
        with patch.dict(os.environ, ON):
            await manage_order(action="list", status_id=3)
        assert _params(mock_redmine)["status_id"] == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", ["open", "!", 0, -1, True])
    async def test_rejects_bad_status(self, bad):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", status_id=bad)
        assert "status_id" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_contact_id_sent_as_the_contact_filter(self, mock_redmine):
        """OrderQuery registers the filter as ``contact``, not ``contact_id``."""
        mock_redmine.engine.request.return_value = {"orders": []}
        with patch.dict(os.environ, ON):
            await manage_order(action="list", contact_id=42)
        params = _params(mock_redmine)
        assert params["contact"] == 42
        assert "contact_id" not in params

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [0, -3, True, "42"])
    async def test_rejects_bad_contact_id(self, bad):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", contact_id=bad)
        assert "contact_id" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_project_scoping(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": []}
        with patch.dict(os.environ, ON):
            await manage_order(action="list", project_id="sales")
        assert _url(mock_redmine) == f"{_URL}/orders.json"
        assert _params(mock_redmine)["project_id"] == "sales"

    @pytest.mark.asyncio
    async def test_rejects_path_unsafe_project_id(self):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", project_id="foo/../bar")
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_search_forwarded(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": []}
        with patch.dict(os.environ, ON):
            await manage_order(action="list", search="acme")
        assert _params(mock_redmine)["search"] == "acme"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_offset_and_limit_passed_through(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "orders": [_make_order(i) for i in range(10)],
            "total_count": 35,
            "offset": 20,
            "limit": 10,
        }
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", limit=10, offset=20)
        params = _params(mock_redmine)
        assert params["limit"] == 10
        assert params["offset"] == 20
        page = result["pagination"]
        assert page["total"] == 35
        assert page["offset"] == 20
        assert page["limit"] == 10
        assert page["count"] == 10
        assert page["has_next"] is True
        assert page["next_offset"] == 30
        assert page["previous_offset"] == 10

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_zero_offset_not_sent(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": []}
        with patch.dict(os.environ, ON):
            await manage_order(action="list")
        assert "offset" not in _params(mock_redmine)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_total_is_kept_under_search(self, mock_redmine):
        """OrdersController counts with the search applied, unlike contacts."""
        mock_redmine.engine.request.return_value = {
            "orders": [_make_order(1)],
            "total_count": 1,
        }
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", search="acme", limit=1)
        assert result["pagination"]["total"] == 1
        assert result["pagination"]["has_next"] is False
        # No limit/offset in the envelope: the requested values stand in.
        assert result["pagination"]["limit"] == 1
        assert result["pagination"]["offset"] == 0

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_clamps_limit_to_100(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": []}
        with patch.dict(os.environ, ON):
            await manage_order(action="list", limit=500)
        assert _params(mock_redmine)["limit"] == 100

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [0, -1, True])
    async def test_rejects_bad_limit(self, bad):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", limit=bad)
        assert "limit" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [-1, True])
    async def test_rejects_bad_offset(self, bad):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", offset=bad)
        assert "offset" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_slices_oversized_response(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "orders": [_make_order(i) for i in range(200)]
        }
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", limit=25)
        assert len(result["orders"]) == 25

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_include_lines(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "orders": [_make_order(1, lines=[_line()]), _make_order(2)]
        }
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", include="lines")
        assert _params(mock_redmine)["include"] == "lines"
        first, second = result["orders"]
        assert first["lines"][0]["product"] == {"id": 4, "name": "Widget Pro"}
        # The plugin renders no ``lines`` key for an order without lines.
        assert "lines" not in second

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", ["comments", "attachments", "lines,notes"])
    async def test_list_refuses_includes_index_does_not_render(self, bad):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", include=bad)
        assert "include" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_custom_fields_elided_by_default(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": [_make_order()]}
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list")
        (order,) = result["orders"]
        assert order["custom_fields"] is None
        assert order["custom_fields_count"] == 2

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_include_custom_fields(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": [_make_order()]}
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", include_custom_fields=True)
        (order,) = result["orders"]
        assert [cf["id"] for cf in order["custom_fields"]] == [7, 8]
        # A response-shape switch, never a query parameter.
        assert "include_custom_fields" not in _params(mock_redmine)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_custom_field_ids(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"orders": [_make_order()]}
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", custom_field_ids=[7])
        (order,) = result["orders"]
        assert order["custom_fields"] == [{"id": 7, "name": "Region", "value": "EMEA"}]
        assert "custom_field_ids" not in _params(mock_redmine)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [[], [0], [True], ["7"]])
    async def test_rejects_bad_custom_field_ids(self, bad):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", custom_field_ids=bad)
        assert "custom_field_ids" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_forbidden(self, mock_redmine):
        mock_redmine.engine.request.side_effect = ForbiddenError()
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list")
        assert result["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_unknown_project(self, mock_redmine):
        mock_redmine.engine.request.side_effect = ResourceNotFoundError()
        with patch.dict(os.environ, ON):
            result = await manage_order(action="list", project_id="nope")
        assert result["code"] == "NOT_FOUND"
        assert result["error"] == "Project nope not found."


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestManageOrderGet:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"order": _make_order(9)}
        with patch.dict(os.environ, ON):
            result = await manage_order(action="get", order_id=9)
        assert _url(mock_redmine) == f"{_URL}/orders/9.json"
        assert _params(mock_redmine) == {}
        assert result["id"] == 9
        # A single read keeps every custom field, as manage_contact's get does.
        assert [cf["id"] for cf in result["custom_fields"]] == [7, 8]
        assert "custom_fields_count" not in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_with_every_include(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "order": _make_order(
                9,
                lines=[_line()],
                comments=[
                    {
                        "id": 3,
                        "text": "Customer asked for an invoice",
                        "author": {"id": 5, "name": "Bob"},
                        "created_on": "2026-10-03T09:00:00Z",
                        "updated_on": "2026-10-03T09:30:00Z",
                    }
                ],
                attachments=[
                    {
                        "id": 70,
                        "filename": "po.pdf",
                        "filesize": 1024,
                        "content_type": "application/pdf",
                        "description": "Signed PO",
                        "content_url": f"{_URL}/attachments/download/70/po.pdf",
                        "author": {"id": 1, "name": "Admin"},
                        "created_on": "2026-10-01T10:05:00Z",
                    }
                ],
            )
        }
        with patch.dict(os.environ, ON):
            result = await manage_order(
                action="get", order_id=9, include="lines, comments,attachments"
            )

        assert _params(mock_redmine)["include"] == "lines,comments,attachments"
        assert result["lines"][0]["product"]["name"] == "Widget Pro"
        (comment,) = result["comments"]
        assert comment["id"] == 3
        assert _wrapped(comment["text"])
        assert "invoice" in comment["text"]
        assert comment["author"] == {"id": 5, "name": "Bob"}
        assert comment["created_on"] == "2026-10-03T09:00:00Z"
        (attachment,) = result["attachments"]
        assert attachment["id"] == 70
        assert attachment["filename"] == "po.pdf"
        assert attachment["author"] == {"id": 1, "name": "Admin"}
        assert _wrapped(attachment["description"])

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_empty_comments_stay_an_empty_list(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "order": _make_order(9, comments=[])
        }
        with patch.dict(os.environ, ON):
            result = await manage_order(action="get", order_id=9, include="comments")
        assert result["comments"] == []

    @pytest.mark.asyncio
    async def test_rejects_unknown_include(self):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="get", order_id=9, include="notes")
        assert "include" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [None, 0, -1, True, "9"])
    async def test_invalid_order_id(self, bad):
        with patch.dict(os.environ, ON):
            result = await manage_order(action="get", order_id=bad)
        assert "order_id" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_not_found(self, mock_redmine):
        mock_redmine.engine.request.side_effect = ResourceNotFoundError()
        with patch.dict(os.environ, ON):
            result = await manage_order(action="get", order_id=404)
        assert result["code"] == "NOT_FOUND"
        assert result["error"] == "Order 404 not found."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_empty_payload_is_not_found(self, mock_redmine):
        mock_redmine.engine.request.return_value = {}
        with patch.dict(os.environ, ON):
            result = await manage_order(action="get", order_id=5)
        assert result["error"] == "Order 5 not found."

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", _URL)
    @patch("redmine_mcp_server._client.redmine")
    async def test_forbidden(self, mock_redmine):
        mock_redmine.engine.request.side_effect = ForbiddenError()
        with patch.dict(os.environ, ON):
            result = await manage_order(action="get", order_id=9)
        assert result["code"] == "FORBIDDEN"
