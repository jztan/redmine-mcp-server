"""RedmineUP Products plugin tool (REDMINE_PRODUCTS_ENABLED gated)."""

import json
from typing import Any, Dict, List, Optional, Union

from .._cleanup import _ensure_cleanup_started
from .._client import _get_redmine_client
from .._env import _is_products_enabled, _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error
from .._serialization import (
    _REDMINE_API_PAGE_CAP,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int, _is_valid_project_id
from ..server import mcp

_PRODUCTS_DISABLED_ERROR = {
    "error": (
        "Products support is disabled. "
        "Set REDMINE_PRODUCTS_ENABLED=true to enable it. "
        "Requires the RedmineUP Products plugin."
    )
}

_PRODUCT_WRITABLE_FIELDS = {
    "name",
    "description",
    "price",
    "currency",
    "status_id",
    "code",
    "project_id",
    "category_id",
    "tag_list",
    "custom_fields",
}


def _product_to_dict(product: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a RedmineUP Products API response into a stable dict.

    Display-name fields (``name``, ``description``, ``code``) are wrapped in
    ``<insecure-content>`` boundary tags because they are user-controlled.
    """
    if not isinstance(product, dict):
        return {}
    raw_project = product.get("project")
    project = raw_project if isinstance(raw_project, dict) else {}
    raw_category = product.get("category")
    category = raw_category if isinstance(raw_category, dict) else {}
    return {
        "id": product.get("id"),
        "name": wrap_insecure_content(product.get("name", "")),
        "description": wrap_insecure_content(product.get("description", "")),
        "code": wrap_insecure_content(product.get("code", "")),
        "price": product.get("price"),
        "currency": product.get("currency"),
        "status_id": product.get("status_id"),
        "project": (
            {
                "id": project.get("id"),
                "name": wrap_insecure_content(project.get("name", "")),
            }
            if project
            else None
        ),
        "category": (
            {
                "id": category.get("id"),
                "name": wrap_insecure_content(category.get("name", "")),
            }
            if category
            else None
        ),
        "tags": product.get("tags") or [],
        "created_on": _safe_isoformat(product.get("created_on")),
        "updated_on": _safe_isoformat(product.get("updated_on")),
    }


@mcp.tool()
async def manage_product(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    limit: int = 100,
    product_id: Optional[int] = None,
    name: Optional[str] = None,
    status_id: int = 1,
    description: Optional[str] = None,
    price: Optional[float] = None,
    currency: Optional[str] = None,
    code: Optional[str] = None,
    category_id: Optional[int] = None,
    tag_list: Optional[str] = None,
    custom_fields: Optional[List[Dict[str, Any]]] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """RedmineUP Products plugin tool. Combined CRUD-by-action.

    Actions: ``list``, ``get``, ``create``, ``update``.
    Requires ``REDMINE_PRODUCTS_ENABLED=true`` and the RedmineUP Products
    plugin.
    """
    if not _is_products_enabled():
        return dict(_PRODUCTS_DISABLED_ERROR)

    _valid_actions = {"list", "get", "create", "update"}
    if action not in _valid_actions:
        return {
            "error": (
                f"Invalid action '{action}'. " f"Allowed: {sorted(_valid_actions)}"
            )
        }

    # Lazy lookup so tests patching `redmine_handler.REDMINE_URL` are honored.
    from .. import redmine_handler as _rh

    if action == "list":
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            return {"error": "limit must be a positive integer."}
        limit = min(limit, _REDMINE_API_PAGE_CAP)
        if project_id is not None and not _is_valid_project_id(project_id):
            return {
                "error": (
                    "project_id must be a non-empty string identifier or "
                    "positive integer."
                )
            }
        try:
            client = _get_redmine_client()
            url = (
                f"{_rh.REDMINE_URL}/projects/{project_id}/products.json"
                if project_id is not None
                else f"{_rh.REDMINE_URL}/products.json"
            )
            payload = client.engine.request("get", url, params={"limit": limit})
            raw = payload.get("products", []) if isinstance(payload, dict) else []
            return [_product_to_dict(p) for p in raw[:limit]]
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing products (project_id={project_id})",
                {"resource_type": "products", "resource_id": project_id},
            )

    if action == "get":
        if not _is_positive_int(product_id):
            return {"error": "product_id must be a positive integer."}
        try:
            client = _get_redmine_client()
            url = f"{_rh.REDMINE_URL}/products/{product_id}.json"
            payload = client.engine.request("get", url)
            product = payload.get("product", {}) if isinstance(payload, dict) else {}
            if not product:
                return {"error": f"Product {product_id} not found."}
            return _product_to_dict(product)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"fetching product {product_id}",
                {"resource_type": "product", "resource_id": product_id},
            )

    # write actions below
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)
    await _ensure_cleanup_started()

    if action == "create":
        if not isinstance(name, str) or not name.strip():
            return {"error": "name must be a non-empty string."}
        if isinstance(status_id, bool) or status_id not in (1, 2):
            return {"error": "status_id must be 1 (Active) or 2 (Inactive)."}
        body: Dict[str, Any] = {"name": name, "status_id": status_id}
        if project_id is not None:
            body["project_id"] = project_id
        if description is not None:
            body["description"] = description
        if price is not None:
            body["price"] = price
        if currency is not None:
            body["currency"] = currency
        if code is not None:
            body["code"] = code
        if category_id is not None:
            if not _is_positive_int(category_id):
                return {"error": "category_id must be a positive integer."}
            body["category_id"] = category_id
        if tag_list is not None:
            body["tag_list"] = tag_list
        if custom_fields is not None:
            body["custom_fields"] = custom_fields
        try:
            client = _get_redmine_client()
            url = f"{_rh.REDMINE_URL}/products.json"
            payload = client.engine.request(
                "post",
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps({"product": body}),
            )
            product = payload.get("product", {}) if isinstance(payload, dict) else {}
            return _product_to_dict(product) if product else {"success": True}
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating product '{name}'",
                {"resource_type": "product", "resource_id": name},
            )

    # action == "update"
    if not _is_positive_int(product_id):
        return {"error": "product_id must be a positive integer."}
    if not isinstance(fields, dict) or not fields:
        return {"error": "fields must be a non-empty dict."}
    filtered = {k: v for k, v in fields.items() if k in _PRODUCT_WRITABLE_FIELDS}
    if not filtered:
        return {
            "error": (
                "No writable fields provided. Allowed fields: "
                f"{sorted(_PRODUCT_WRITABLE_FIELDS)}"
            )
        }
    try:
        client = _get_redmine_client()
        url = f"{_rh.REDMINE_URL}/products/{product_id}.json"
        client.engine.request(
            "put",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"product": filtered}),
        )
        return {
            "success": True,
            "product_id": product_id,
            "updated_fields": list(filtered.keys()),
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating product {product_id}",
            {"resource_type": "product", "resource_id": product_id},
        )
