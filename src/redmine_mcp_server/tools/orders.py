"""RedmineUP Products plugin orders tool (REDMINE_ORDERS_ENABLED gated).

Orders ship inside the RedmineUP Products plugin but get their own feature
flag, because the plugin declares them as a separate Redmine *project module*
(``project_module :orders``) with its own permissions, next to
``project_module :products``. A deployment may enable one module without the
other; see :func:`.._env._is_orders_enabled`.

Read-only: the tool exposes ``list`` and ``get`` and no write action.
"""

from types import SimpleNamespace
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._env import _is_orders_enabled
from .._errors import _handle_redmine_error
from .._offload import offloaded
from .._serialization import (
    _REDMINE_API_PAGE_CAP,
    _attachment_to_dict,
    _custom_fields_to_list,
    _named_ref,
    _normalize_csv_list,
    _pagination_info,
    _payload_int,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int, _is_valid_project_id
from .._plugin_visibility import plugin_tag
from ..server import mcp

_ORDERS_DISABLED_ERROR = {
    "error": (
        "Orders support is disabled. "
        "Set REDMINE_ORDERS_ENABLED=true to enable it. "
        "Requires the RedmineUP Products plugin and its orders module."
    )
}

# Redmine's :list_status filter operators, which is the type OrderQuery gives
# ``status_id``. Passing one of these escapes the open-only default; a bare id
# falls through to the ``=`` operator in Query#add_short_filter.
_ORDER_STATUS_OPERATORS = frozenset({"o", "c", "*"})

# What each action may ask the plugin to render. ``orders/index.api.rsb``
# honours only ``lines``; ``orders/show.api.rsb`` adds ``comments`` and
# ``attachments``. Redmine ignores any other name without an error, so an
# unknown one is refused here rather than answered as if it had been applied.
_ORDER_LIST_INCLUDES = ("lines",)
_ORDER_GET_INCLUDES = ("lines", "comments", "attachments")


def _validate_include(
    include: Optional[str], allowed: tuple, action: str
) -> Union[Optional[str], Dict[str, Any]]:
    """Normalize ``include`` to a comma-separated string, or an error dict."""
    if include is None:
        return None
    if not isinstance(include, str):
        return {"error": "include must be a comma-separated string."}
    names = _normalize_csv_list(include)
    unknown = [name for name in names if name not in allowed]
    if unknown:
        return {
            "error": (
                f"include on {action} accepts {', '.join(allowed)}; "
                f"got {', '.join(unknown)}."
            )
        }
    return ",".join(dict.fromkeys(names)) or None


def _order_line_to_dict(line: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize one product line of an order (``include=lines``).

    Mirrors ``api.line_attributes`` in the plugin's order templates: in JSON
    each line is a plain object in the ``lines`` array. ``description`` is
    free text and is wrapped in boundary tags.
    """
    if not isinstance(line, dict):
        return {}
    return {
        "id": line.get("id"),
        "position": line.get("position"),
        "product": _named_ref(line.get("product")),
        "description": (
            wrap_insecure_content(line["description"])
            if line.get("description")
            else None
        ),
        "quantity": line.get("quantity"),
        "tax": line.get("tax"),
        "discount": line.get("discount"),
        "price": line.get("price"),
        "total": line.get("total"),
    }


def _order_comment_to_dict(comment: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize one order comment (``include=comments``, ``get`` only).

    ``text`` is free text and is wrapped in boundary tags.
    """
    if not isinstance(comment, dict):
        return {}
    return {
        "id": comment.get("id"),
        "text": wrap_insecure_content(comment.get("text", "")),
        "author": _named_ref(comment.get("author")),
        "created_on": _safe_isoformat(comment.get("created_on")),
        "updated_on": _safe_isoformat(comment.get("updated_on")),
    }


def _order_status_to_dict(status: Any) -> Optional[Dict[str, Any]]:
    """The ``status`` ref, keeping the plugin's ``is_closed`` beside id/name."""
    if not isinstance(status, dict):
        return None
    return {**_named_ref(status), "is_closed": status.get("is_closed")}


def _order_to_dict(
    order: Dict[str, Any],
    include_custom_fields: bool = False,
    custom_field_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Serialize a RedmineUP Products order API response into a stable dict.

    Keys mirror the plugin's own ``app/views/orders/index.api.rsb`` and
    ``show.api.rsb`` templates, including ``created_at`` / ``updated_at``.

    ``description`` is the free-text field and is wrapped in
    ``<insecure-content>`` boundary tags. ``subject`` and ``number`` are
    short, label-shaped fields and are returned verbatim, matching how issue
    ``subject`` and the ``id``/``name`` refs are treated (#109).

    The plugin omits a ref entirely when the association is nil, so a
    missing key becomes ``None`` rather than an empty dict.

    ``lines`` is rendered only under ``include=lines`` *and* only when the
    order has lines, so the key is omitted rather than reported as an empty
    list when the plugin sent none. ``comments`` and ``attachments`` are
    rendered (possibly empty) whenever ``get`` asked for them.

    Custom fields follow ``manage_contact``: the plugin renders every one on
    every row, so a ``list`` row carries ``custom_fields: None`` plus
    ``custom_fields_count`` unless they were asked for, and
    ``custom_field_ids`` narrows the values to the fields named.
    """
    if not isinstance(order, dict):
        return {}
    result: Dict[str, Any] = {
        "id": order.get("id"),
        "number": order.get("number"),
        "subject": order.get("subject", ""),
        "order_date": _safe_isoformat(order.get("order_date")),
        "completed_date": _safe_isoformat(order.get("completed_date")),
        "amount": order.get("amount"),
        "currency": order.get("currency"),
        "description": wrap_insecure_content(order.get("description", "")),
        "contact": _named_ref(order.get("contact")),
        "project": _named_ref(order.get("project")),
        "status": _order_status_to_dict(order.get("status")),
        "author": _named_ref(order.get("author")),
        "assigned_to": _named_ref(order.get("assigned_to")),
        "created_at": _safe_isoformat(order.get("created_at")),
        "updated_at": _safe_isoformat(order.get("updated_at")),
    }
    custom_fields = _custom_fields_to_list(order)
    if custom_field_ids is not None:
        wanted = set(custom_field_ids)
        custom_fields = [cf for cf in custom_fields if cf["id"] in wanted]
        include_custom_fields = True
    if include_custom_fields:
        result["custom_fields"] = custom_fields
    else:
        result["custom_fields"] = None
        result["custom_fields_count"] = len(custom_fields)
    lines = order.get("lines")
    if isinstance(lines, list):
        result["lines"] = [_order_line_to_dict(line) for line in lines]
    comments = order.get("comments")
    if isinstance(comments, list):
        result["comments"] = [_order_comment_to_dict(c) for c in comments]
    attachments = order.get("attachments")
    if isinstance(attachments, list):
        # One attachment shape across the server: the shared serializer reads
        # attributes, so each decoded dict is given attribute access.
        result["attachments"] = [
            _attachment_to_dict(SimpleNamespace(**a))
            for a in attachments
            if isinstance(a, dict)
        ]
    return result


@offloaded
def _list_orders_action(
    project_id: Optional[Union[str, int]] = None,
    contact_id: Optional[int] = None,
    status_id: Optional[Union[int, str]] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    include: Optional[str] = None,
    include_custom_fields: bool = False,
    custom_field_ids: Optional[List[int]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(limit):
        return {"error": "limit must be a positive integer."}
    limit = min(limit, _REDMINE_API_PAGE_CAP)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return {"error": "offset must be a non-negative integer."}
    if project_id is not None and not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    if custom_field_ids is not None and (
        not isinstance(custom_field_ids, list)
        or not custom_field_ids
        or not all(_is_positive_int(cf_id) for cf_id in custom_field_ids)
    ):
        return {
            "error": (
                "custom_field_ids must be a non-empty list of positive integer "
                "custom field IDs."
            )
        }
    if contact_id is not None and not _is_positive_int(contact_id):
        return {"error": "contact_id must be a positive integer."}
    if isinstance(status_id, str) and status_id not in _ORDER_STATUS_OPERATORS:
        return {
            "error": (
                "status_id must be a positive integer, or one of "
                "'o' (open), 'c' (completed/canceled), '*' (any status)."
            )
        }
    if (
        status_id is not None
        and not isinstance(status_id, str)
        and not _is_positive_int(status_id)
    ):
        return {"error": "status_id must be a positive integer."}
    include_value = _validate_include(include, _ORDER_LIST_INCLUDES, "list")
    if isinstance(include_value, dict):
        return include_value
    params: Dict[str, Any] = {"limit": limit}
    if offset:
        params["offset"] = offset
    if project_id is not None:
        params["project_id"] = project_id
    if contact_id is not None:
        # OrderQuery names this filter ``contact``, not ``contact_id``
        # (``sql_for_contact_field`` -> ``orders.contact_id``). Redmine drops
        # an unregistered filter name silently, so ``contact_id`` would come
        # back unfiltered.
        params["contact"] = contact_id
    if status_id is not None:
        params["status_id"] = status_id
    if search is not None:
        params["search"] = search
    if include_value:
        params["include"] = include_value
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/orders.json"
        payload = client.engine.request("get", url, params=params)
        envelope = payload if isinstance(payload, dict) else {}
        raw = envelope.get("orders", [])
        raw = raw if isinstance(raw, list) else []
        orders = [
            _order_to_dict(
                o,
                include_custom_fields=include_custom_fields,
                custom_field_ids=custom_field_ids,
            )
            for o in raw[:limit]
        ]
        # Unlike ContactsController, OrdersController counts with the search
        # applied (``@query.object_count(search: params[:search])``), so
        # ``total_count`` measures the collection being paged even under
        # ``search`` and is reported as is.
        applied_limit = _payload_int(envelope.get("limit"), minimum=1)
        applied_offset = _payload_int(envelope.get("offset"), minimum=0)
        return {
            "orders": orders,
            "pagination": _pagination_info(
                limit=limit if applied_limit is None else applied_limit,
                offset=offset if applied_offset is None else applied_offset,
                count=len(orders),
                total=_payload_int(envelope.get("total_count"), minimum=0),
            ),
        }
    except Exception as e:
        # The index answers 404 only from find_optional_project, for a
        # project_id that matches no project. An existing project the caller
        # may not list orders in is refused by authorize_global with 403.
        context: Dict[str, Any] = (
            {"resource_type": "project", "resource_id": project_id}
            if project_id is not None
            else {"resource_type": "orders"}
        )
        return _handle_redmine_error(
            e, f"listing orders (project_id={project_id})", context
        )


@offloaded
def _get_order_action(
    order_id: Optional[int] = None,
    include: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(order_id):
        return {"error": "order_id must be a positive integer."}
    include_value = _validate_include(include, _ORDER_GET_INCLUDES, "get")
    if isinstance(include_value, dict):
        return include_value
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/orders/{order_id}.json"
        params: Dict[str, Any] = {}
        if include_value:
            params["include"] = include_value
        payload = client.engine.request("get", url, params=params)
        order = payload.get("order", {}) if isinstance(payload, dict) else {}
        if not order:
            return {"error": f"Order {order_id} not found."}
        # A single-order read keeps every custom field, as manage_contact's
        # get does. The collection is where the cost is.
        return _order_to_dict(order, include_custom_fields=True)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching order {order_id}",
            {"resource_type": "order", "resource_id": order_id},
        )


@action_dispatch(
    {
        "list": ActionMode.READ,
        "get": ActionMode.READ,
    }
)
async def _manage_order_dispatch(action: str, **kwargs: Any) -> Any:
    return {
        "list": _list_orders_action,
        "get": _get_order_action,
    }


@mcp.tool(tags={plugin_tag("orders")})
async def manage_order(
    action: Literal["list", "get"],
    project_id: Optional[Union[str, int]] = None,
    contact_id: Optional[int] = None,
    status_id: Optional[Union[int, str]] = None,
    search: Optional[str] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 100,
    offset: Annotated[int, Field(ge=0)] = 0,
    include: Optional[str] = None,
    include_custom_fields: bool = False,
    custom_field_ids: Optional[List[int]] = None,
    order_id: Optional[int] = None,
) -> Dict[str, Any]:
    """RedmineUP Products plugin orders tool. Read-only.

    Actions: ``list``, ``get``. There is no write action.

    Requires ``REDMINE_ORDERS_ENABLED=true``, the RedmineUP Products plugin,
    and the ``orders`` project module enabled on the project.

    One flat signature serves both actions, so most parameters apply to one
    action and are ignored by the other. Which is which:

    Args:
        action: Which operation to run.
        project_id: ``list`` only. Restrict to orders in this project
            (identifier or numeric id) and, under Redmine's default
            "display subprojects issues" setting, its subprojects; omit for
            every order the caller can see.
        contact_id: ``list`` only. Only orders placed by this contact, as a
            positive integer contact id.
        status_id: ``list`` only. **``list`` returns only OPEN orders unless
            told otherwise.** Accepts ``"o"`` (open: processing and draft),
            ``"c"`` (completed and canceled), ``"*"`` (every status), or a
            numeric order status id.
        search: ``list`` only. Free-text search over the order number,
            subject and description and the contact's name, company and
            email. Each space-separated word matches on its own (OR), so
            more words return more orders, not fewer.
        limit: ``list`` only. Orders per call, capped at 100 by Redmine.
        offset: ``list`` only. Orders to skip, for paging past the first 100.
        include: On ``list``, ``"lines"`` adds each order's product lines.
            On ``get``, comma-separated, any of ``lines``, ``comments`` and
            ``attachments``. Any other name is refused. ``lines`` stays
            absent from an order that has none, even when requested.
        include_custom_fields: ``list`` only. Return each order's
            ``custom_fields`` values (default: False). Without it a listed
            order carries ``custom_fields`` holding ``None`` beside
            ``custom_fields_count`` saying how many were withheld: ``None``
            means "not requested" and ``[]`` means "this order has none".
            A ``get`` returns the values always.
        custom_field_ids: ``list`` only. Return only these custom fields in
            each order's ``custom_fields``, e.g. ``[42, 43]``; implies
            ``include_custom_fields``. The IDs are the ``id`` of each
            ``custom_fields`` entry.
        order_id: ``get`` only. The order to read (required there).

    Returns:
        ``list`` a dict of ``orders`` (a list of order dicts) and
        ``pagination`` (``total``, ``limit``, ``offset``, ``count``,
        ``has_next``, ``has_previous``, ``next_offset``,
        ``previous_offset``); ``get`` one order dict; ``{"error": ...}`` on
        failure.
    """
    if not _is_orders_enabled():
        return dict(_ORDERS_DISABLED_ERROR)
    return await _manage_order_dispatch(
        action,
        project_id=project_id,
        contact_id=contact_id,
        status_id=status_id,
        search=search,
        limit=limit,
        offset=offset,
        include=include,
        include_custom_fields=include_custom_fields,
        custom_field_ids=custom_field_ids,
        order_id=order_id,
    )
