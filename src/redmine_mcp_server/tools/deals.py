"""RedmineUP CRM (Deals) plugin tool (REDMINE_DEALS_ENABLED gated).

Deals ship inside the same RedmineUP CRM plugin as contacts but get their
own feature flag because the plugin's Light edition ships no deals at all;
see :func:`.._env._is_deals_enabled` for why sharing
``REDMINE_CRM_ENABLED`` would break OAuth consent on a Light install.

Deals are also a separate Redmine *project module* from contacts, so even
on the Pro edition a project can have contacts enabled and deals disabled.
"""

import json
import math
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field
from redminelib.exceptions import ForbiddenError

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._env import _is_deals_enabled
from .._errors import _handle_redmine_error
from .._offload import offloaded
from .._serialization import (
    _REDMINE_API_PAGE_CAP,
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int, _is_valid_project_id
from .._plugin_visibility import plugin_tag
from ..server import mcp

_DEALS_DISABLED_ERROR = {
    "error": (
        "Deals (CRM) support is disabled. "
        "Set REDMINE_DEALS_ENABLED=true to enable it. "
        "Requires the RedmineUP CRM plugin, Pro edition."
    )
}

# Mirrors the plugin's ``Deal`` safe_attributes list, which is what
# POST /deals.json and PUT /deals/<id>.json actually accept. Anything
# outside this set is dropped rather than forwarded, so a typo fails
# loudly in the tool instead of being silently ignored by Redmine.
_DEAL_WRITABLE_FIELDS = {
    "name",
    "background",
    "currency",
    "price",
    "price_type",
    "duration",
    "project_id",
    "author_id",
    "assigned_to_id",
    "status_id",
    "contact_id",
    "category_id",
    "probability",
    "due_date",
    "custom_field_values",
    "custom_fields",
    "watcher_user_ids",
}


# Redmine's :list_status filter operators, which is the type DealQuery gives
# ``status_id``. Passing one of these escapes the open-only default; a bare id
# falls through to the ``=`` operator in Query#add_short_filter.
_DEAL_STATUS_OPERATORS = frozenset({"o", "c", "*"})

# Writable fields that Redmine casts to an integer id. They must be validated
# even when supplied through ``fields``, because ActiveRecord turns ``true``
# into ``1`` -- silently selecting record 1 rather than failing.
_DEAL_ID_FIELDS = frozenset(
    {"author_id", "assigned_to_id", "status_id", "contact_id", "category_id"}
)


def _merge_writable_fields(
    body: Dict[str, Any], fields: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Copy caller-supplied ``fields`` into ``body``, validating id values.

    Returns an error dict, or ``None`` on success. Unknown keys are dropped
    rather than forwarded, so a typo fails here instead of being ignored by
    Redmine.
    """
    for key, value in (fields or {}).items():
        if key not in _DEAL_WRITABLE_FIELDS:
            continue
        if key in _DEAL_ID_FIELDS and not _is_positive_int(value):
            return {"error": f"{key} must be a positive integer."}
        if key == "project_id" and not _is_valid_project_id(value):
            return {
                "error": (
                    "project_id must be a non-empty string identifier or "
                    "positive integer."
                )
            }
        if key == "price":
            coerced = _coerce_price(value)
            if coerced is None:
                return {"error": "price must be a finite number or a string."}
            value = coerced
        body[key] = value
    return None


def _coerce_price(price: Any) -> Optional[str]:
    """Render ``price`` as the string the plugin's parser requires.

    ``DealsController#create`` runs ``params[:deal][:price]`` through
    ``parsed_price``, which calls ``String#gsub!`` -- so a JSON number
    raises ``NoMethodError`` and the request 500s. Sending a string avoids
    that; Redmine casts it into the decimal column either way.

    Returns ``None`` for a value that cannot be sent safely: booleans (an
    ``int`` subclass) and non-finite floats, which ``json.dumps`` would
    emit as bare ``NaN`` / ``Infinity`` and no strict parser accepts.
    """
    if isinstance(price, bool):
        return None
    if isinstance(price, float) and not math.isfinite(price):
        return None
    if isinstance(price, (int, float)):
        return str(price)
    if isinstance(price, str):
        return price
    return None


def _deal_note_to_dict(note: Any) -> Dict[str, Any]:
    """Serialize one deal note, keyed as the plugin's show.api.rsb renders it.

    ``content`` is free text and is wrapped in ``<insecure-content>``
    boundary tags, matching how issue ``description`` and journal notes are
    treated. The plugin only renders the notes array for a caller holding
    ``view_deals`` on the project.
    """
    if not isinstance(note, dict):
        return {}
    return {
        "id": note.get("id"),
        "content": wrap_insecure_content(note.get("content", "")),
        "type_id": note.get("type_id"),
        "author": _named_ref(note.get("author")),
        "created_on": _safe_isoformat(note.get("created_on")),
        "updated_on": _safe_isoformat(note.get("updated_on")),
    }


def _deal_to_dict(deal: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a RedmineUP CRM deal API response into a stable dict.

    Keys mirror the plugin's own ``app/views/deals/index.api.rsb`` and
    ``show.api.rsb`` templates rather than introducing new names.

    ``background`` is the only free-text field and is wrapped in
    ``<insecure-content>`` boundary tags. ``name`` is a short,
    label-shaped field and is returned verbatim, matching how issue
    ``subject`` and the ``id``/``name`` refs are treated (#109).

    The plugin omits a ref entirely when the association is nil
    (``unless deal.project.nil?``), so a missing key becomes ``None``
    rather than an empty dict.

    ``notes`` is present only when the caller asked for it via
    ``include=notes`` and the plugin rendered it, so the key is omitted
    rather than reported as an empty list -- that keeps "not requested"
    distinguishable from "requested, none present".
    """
    if not isinstance(deal, dict):
        return {}
    related = deal.get("related_contacts")
    notes = deal.get("notes")
    return {
        "id": deal.get("id"),
        "name": deal.get("name", ""),
        "price": deal.get("price"),
        "currency": deal.get("currency"),
        "price_type": deal.get("price_type"),
        "duration": deal.get("duration"),
        "probability": deal.get("probability"),
        "due_date": _safe_isoformat(deal.get("due_date")),
        "background": wrap_insecure_content(deal.get("background", "")),
        "project": _named_ref(deal.get("project")),
        "status": _named_ref(deal.get("status")),
        "category": _named_ref(deal.get("category")),
        "author": _named_ref(deal.get("author")),
        "contact": _named_ref(deal.get("contact")),
        "assigned_to": _named_ref(deal.get("assigned_to")),
        "related_contacts": (
            [_named_ref(c) for c in related] if isinstance(related, list) else []
        ),
        "created_on": _safe_isoformat(deal.get("created_on")),
        "updated_on": _safe_isoformat(deal.get("updated_on")),
        **(
            {"notes": [_deal_note_to_dict(n) for n in notes]}
            if isinstance(notes, list)
            else {}
        ),
    }


# DealStatus::OPEN_STATUS / WON_STATUS / LOST_STATUS in the plugin.
_DEAL_STATUS_TYPES = {0: "open", 1: "won", 2: "lost"}


def _deal_status_to_dict(status: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize one entry of GET /deal_statuses.json.

    ``status_type`` is rendered as ``open``/``won``/``lost`` so a caller can
    pick a closing status without knowing the plugin's enum; the raw code is
    kept as ``status_type_id``. ``name`` and ``color`` are label-shaped and
    returned verbatim (same rule as deal ``name``, #109).
    """
    if not isinstance(status, dict):
        return {}
    code = status.get("status_type")
    return {
        "id": status.get("id"),
        "name": status.get("name", ""),
        "position": status.get("position"),
        "is_default": bool(status.get("is_default", False)),
        "status_type": _DEAL_STATUS_TYPES.get(code),
        "status_type_id": code,
        "color": status.get("color"),
    }


def _deal_category_to_dict(category: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize one entry of GET /projects/<id>/deal_categories.json."""
    if not isinstance(category, dict):
        return {}
    return {"id": category.get("id"), "name": category.get("name", "")}


@offloaded
def _list_deals_action(
    project_id: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
    status_id: Optional[Union[int, str]] = None,
    assigned_to_id: Optional[int] = None,
    limit: int = 100,
    **_: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    if not _is_positive_int(limit):
        return {"error": "limit must be a positive integer."}
    limit = min(limit, _REDMINE_API_PAGE_CAP)
    if project_id is not None and not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    params: Dict[str, Any] = {"limit": limit}
    if project_id is not None:
        params["project_id"] = project_id
    if search is not None:
        params["search"] = search
    if status_id is not None:
        if isinstance(status_id, str) and status_id not in _DEAL_STATUS_OPERATORS:
            return {
                "error": (
                    "status_id must be a positive integer, or one of "
                    "'o' (open), 'c' (won/lost), '*' (any status)."
                )
            }
        if not isinstance(status_id, str) and not _is_positive_int(status_id):
            return {"error": "status_id must be a positive integer."}
        params["status_id"] = status_id
    if assigned_to_id is not None:
        if not _is_positive_int(assigned_to_id):
            return {"error": "assigned_to_id must be a positive integer."}
        params["assigned_to_id"] = assigned_to_id
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/deals.json"
        payload = client.engine.request("get", url, params=params)
        raw = payload.get("deals", []) if isinstance(payload, dict) else []
        return [_deal_to_dict(d) for d in raw[:limit]]
    except Exception as e:
        return _handle_redmine_error(e, "listing deals", {"resource_type": "deals"})


@offloaded
def _get_deal_action(
    deal_id: Optional[int] = None,
    include: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(deal_id):
        return {"error": "deal_id must be a positive integer."}
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/deals/{deal_id}.json"
        params: Dict[str, Any] = {}
        if include:
            params["include"] = include
        payload = client.engine.request("get", url, params=params)
        deal = payload.get("deal", {}) if isinstance(payload, dict) else {}
        if not deal:
            return {"error": f"Deal {deal_id} not found."}
        return _deal_to_dict(deal)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching deal {deal_id}",
            {"resource_type": "deal", "resource_id": deal_id},
        )


@offloaded
def _create_deal_action(
    project_id: Optional[Union[str, int]] = None,
    name: Optional[str] = None,
    contact_id: Optional[int] = None,
    status_id: Optional[int] = None,
    assigned_to_id: Optional[int] = None,
    price: Optional[Union[str, int, float]] = None,
    currency: Optional[str] = None,
    due_date: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id is required and must be a non-empty string "
                "identifier or positive integer."
            )
        }
    if not isinstance(name, str) or not name.strip():
        return {"error": "name must be a non-empty string."}
    body: Dict[str, Any] = {"project_id": project_id, "name": name}
    id_params = (
        ("contact_id", contact_id),
        ("status_id", status_id),
        ("assigned_to_id", assigned_to_id),
    )
    for key, value in id_params:
        if value is not None:
            if not _is_positive_int(value):
                return {"error": f"{key} must be a positive integer."}
            body[key] = value
    if price is not None:
        coerced = _coerce_price(price)
        if coerced is None:
            return {"error": "price must be a finite number or a string."}
        body["price"] = coerced
    if currency is not None:
        body["currency"] = currency
    if due_date is not None:
        body["due_date"] = due_date
    error = _merge_writable_fields(body, fields)
    if error:
        return error
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/deals.json"
        payload = client.engine.request(
            "post",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"deal": body}),
        )
        deal = payload.get("deal", {}) if isinstance(payload, dict) else {}
        return _deal_to_dict(deal) if deal else {"success": True}
    except Exception as e:
        return _handle_redmine_error(e, "creating deal", {"resource_type": "deal"})


@offloaded
def _update_deal_action(
    deal_id: Optional[int] = None,
    fields: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(deal_id):
        return {"error": "deal_id must be a positive integer."}
    if not isinstance(fields, dict) or not fields:
        return {"error": "fields must be a non-empty dict."}
    filtered: Dict[str, Any] = {}
    error = _merge_writable_fields(filtered, fields)
    if error:
        return error
    if not filtered:
        return {
            "error": (
                "No writable fields provided. Allowed fields: "
                f"{sorted(_DEAL_WRITABLE_FIELDS)}"
            )
        }
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/deals/{deal_id}.json"
        client.engine.request(
            "put",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"deal": filtered}),
        )
        return {
            "success": True,
            "deal_id": deal_id,
            "updated_fields": list(filtered.keys()),
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating deal {deal_id}",
            {"resource_type": "deal", "resource_id": deal_id},
        )


@offloaded
def _delete_deal_action(
    deal_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(deal_id):
        return {"error": "deal_id must be a positive integer."}
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/deals/{deal_id}.json"
        client.engine.request("delete", url)
        return {
            "success": True,
            "deal_id": deal_id,
            "message": f"Deal {deal_id} deleted.",
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"deleting deal {deal_id}",
            {"resource_type": "deal", "resource_id": deal_id},
        )


@action_dispatch(
    {
        "list": ActionMode.READ,
        "get": ActionMode.READ,
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
        "delete": ActionMode.WRITE,
    }
)
async def _manage_deal_dispatch(action: str, **kwargs: Any) -> Any:
    return {
        "list": _list_deals_action,
        "get": _get_deal_action,
        "create": _create_deal_action,
        "update": _update_deal_action,
        "delete": _delete_deal_action,
    }


@mcp.tool(tags={plugin_tag("deals")})
async def manage_deal(
    action: Literal["list", "get", "create", "update", "delete"],
    project_id: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
    status_id: Optional[Union[int, str]] = None,
    assigned_to_id: Optional[int] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 100,
    deal_id: Optional[int] = None,
    include: Optional[str] = None,
    name: Optional[str] = None,
    contact_id: Optional[int] = None,
    price: Optional[Union[str, int, float]] = None,
    currency: Optional[str] = None,
    due_date: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """RedmineUP CRM (Deals) plugin tool. Combined CRUD-by-action.

    Actions: ``list``, ``get``, ``create``, ``update``, ``delete``.

    Requires ``REDMINE_DEALS_ENABLED=true`` and the RedmineUP CRM plugin.

    One flat signature serves every action, so most parameters apply to some
    actions and are ignored by the rest. Which is which:

    Args:
        action: Which operation to run.
        project_id: On ``list``, restrict to deals in this project. On
            ``create``, the project to file the new deal under (required).
        search: ``list`` only. Free-text search over the deal name.
        status_id: **``list`` returns only OPEN deals unless told
            otherwise.** Accepts ``"o"`` (open), ``"c"`` (won and lost),
            ``"*"`` (every status), or a numeric status id. On ``create``,
            the status to open the deal in, as a numeric id. Status and deal
            category ids come from ``list_deal_statuses``.
        assigned_to_id: On ``list``, filter by the assigned user's ID. On
            ``create``, the user to assign the new deal to.
        limit: ``list`` only. Deals per call, capped at 100 by Redmine.
        deal_id: The deal to act on. Required by every action except
            ``list`` and ``create``.
        include: ``get`` only. Accepts ``"notes"``, returned under a
            ``notes`` key.
        name: ``create`` only -- the new deal's name (required).
        contact_id: ``create`` only. The contact the deal belongs to.
        price: ``create`` only. Send an unformatted string such as
            ``"1500.5"``.
        currency, due_date: ``create`` only. The deal's currency code, and
            its due date as ``YYYY-MM-DD``.
        fields: ``create`` and ``update`` only. Deal attributes to write.
            On ``update`` it is the only way to change a deal, so it is
            required and must be non-empty.

    Returns:
        ``list`` a list of deal dicts, ``get`` / ``create`` one deal dict,
        ``update`` / ``delete`` a status dict, and ``{"error": ...}`` on
        failure.
    """
    if not _is_deals_enabled():
        return dict(_DEALS_DISABLED_ERROR)
    return await _manage_deal_dispatch(
        action,
        project_id=project_id,
        search=search,
        status_id=status_id,
        assigned_to_id=assigned_to_id,
        limit=limit,
        deal_id=deal_id,
        include=include,
        name=name,
        contact_id=contact_id,
        price=price,
        currency=currency,
        due_date=due_date,
        fields=fields,
    )


_DEAL_STATUSES_ADMIN_ONLY = (
    "The CRM plugin restricts GET /deal_statuses.json to Redmine "
    "administrators and the current user is not one. Read status ids off "
    "existing deals instead (manage_deal action=list with status_id='*'), "
    "or ask an administrator for the list."
)


@offloaded
def _list_deal_statuses_impl(
    project_id: Optional[Union[str, int]] = None,
) -> Dict[str, Any]:
    if project_id is not None and not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    from .. import _client

    result: Dict[str, Any] = {}
    try:
        client = _get_redmine_client()
        try:
            payload = client.engine.request(
                "get", f"{_client.REDMINE_URL}/deal_statuses.json"
            )
            raw = payload.get("deal_statuses", []) if isinstance(payload, dict) else []
            result["statuses"] = [_deal_status_to_dict(s) for s in raw]
        except ForbiddenError:
            # Admin-only endpoint: degrade to a partial answer rather than
            # fail the whole lookup for every non-admin caller.
            result["statuses"] = None
            result["statuses_error"] = _DEAL_STATUSES_ADMIN_ONLY
        if project_id is not None:
            payload = client.engine.request(
                "get",
                f"{_client.REDMINE_URL}/projects/{project_id}/deal_categories.json",
            )
            raw = (
                payload.get("deal_categories", []) if isinstance(payload, dict) else []
            )
            result["categories"] = [_deal_category_to_dict(c) for c in raw]
            result["project_id"] = project_id
        return result
    except Exception as e:
        return _handle_redmine_error(
            e,
            "listing deal statuses",
            {"resource_type": "project", "resource_id": project_id or ""},
        )


@mcp.tool(tags={plugin_tag("deals")})
async def list_deal_statuses(
    project_id: Optional[Union[str, int]] = None,
) -> Dict[str, Any]:
    """List RedmineUP CRM deal statuses, and a project's deal categories.

    Call this before ``manage_deal(action="create")``, which requires a
    numeric ``status_id`` and accepts an optional ``category_id``.

    Requires ``REDMINE_DEALS_ENABLED=true`` and the CRM plugin, Pro edition.

    Args:
        project_id: Optional project identifier or id. When given, the
            project's deal categories are returned as well (categories are
            defined per project).

    Returns:
        ``statuses``: list of ``{id, name, position, is_default,
        status_type (open|won|lost), status_type_id, color}`` ordered by
        position. The plugin only serves this list to Redmine
        administrators; for other users ``statuses`` is ``None`` and
        ``statuses_error`` explains the restriction while the rest of the
        answer is still returned. ``categories``: list of ``{id, name}``,
        present only when ``project_id`` was given. ``{"error": ...}`` on
        failure.
    """
    if not _is_deals_enabled():
        return dict(_DEALS_DISABLED_ERROR)
    return await _list_deal_statuses_impl(project_id)
