"""RedmineUP Checklists plugin tools (REDMINE_CHECKLISTS_ENABLED gated)."""

import json
from typing import Any, Dict, List, Optional

from .._client import _get_redmine_client
from .._env import _is_checklists_enabled, _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error
from .._serialization import wrap_insecure_content
from .._validation import _is_positive_int
from ..server import mcp


def _fetch_checklist_items(issue_id: int) -> List[Dict[str, Any]]:
    """Fetch checklist items for an issue from the RedmineUP Checklists endpoint.

    Returns a list of checklist item dicts.
    Raises on any HTTP error (caller is responsible for catching).
    """
    # Lazy lookup so tests patching `redmine_handler.REDMINE_URL` are honored.
    from .. import redmine_handler as _rh

    client = _get_redmine_client()
    url = f"{_rh.REDMINE_URL}/issues/{issue_id}/checklists.json"
    payload = client.engine.request("get", url)
    raw_items = payload if isinstance(payload, list) else payload.get("checklists", [])
    items = []
    for item in raw_items:
        items.append(
            {
                "id": item.get("id"),
                "subject": wrap_insecure_content(item.get("subject", "")),
                "is_done": item.get("is_done", False),
                "position": item.get("position"),
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
        )
    return items


def _update_checklist_item_api(checklist_item_id: int, updates: Dict[str, Any]) -> Any:
    """Update a checklist item via the RedmineUP Checklists endpoint.

    Raises on any HTTP error (caller is responsible for catching).
    """
    # Lazy lookup so tests patching `redmine_handler.REDMINE_URL` are honored.
    from .. import redmine_handler as _rh

    client = _get_redmine_client()
    url = f"{_rh.REDMINE_URL}/checklists/{checklist_item_id}.json"
    payload = json.dumps({"checklist": updates})
    return client.engine.request(
        "put",
        url,
        headers={"Content-Type": "application/json"},
        data=payload,
    )


@mcp.tool()
async def get_checklist(issue_id: int) -> Dict[str, Any]:
    """Retrieve all checklist items for a Redmine issue.

    Requires the RedmineUP Checklists plugin and
    ``REDMINE_CHECKLISTS_ENABLED=true``.

    Args:
        issue_id: The ID of the issue whose checklist to retrieve.

    Returns:
        A dictionary with an ``items`` list of checklist item dicts,
        each containing ``id``, ``subject``, ``is_done``, ``position``,
        ``created_at``, and ``updated_at``. Also includes ``total_count``.
        Returns an error dict if the plugin is disabled or on failure.
    """
    if not _is_checklists_enabled():
        return {
            "error": (
                "Checklist support is disabled. "
                "Set REDMINE_CHECKLISTS_ENABLED=true to enable it."
            )
        }

    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}

    try:
        items = _fetch_checklist_items(issue_id)
        return {
            "issue_id": issue_id,
            "total_count": len(items),
            "items": items,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching checklist for issue {issue_id}",
            {"resource_type": "checklist", "resource_id": issue_id},
        )


@mcp.tool()
async def update_checklist_item(
    checklist_item_id: int,
    subject: Optional[str] = None,
    is_done: Optional[bool] = None,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Update a checklist item's text, done state, or position.

    Requires the RedmineUP Checklists plugin and
    ``REDMINE_CHECKLISTS_ENABLED=true``. This is a write operation and
    is blocked when ``REDMINE_MCP_READ_ONLY=true``.

    Args:
        checklist_item_id: The ID of the checklist item to update.
        subject: New text for the checklist item (optional).
        is_done: New done state (optional).
        position: New position/order (optional).

    Returns:
        A success dict with the updated fields, or an error dict on failure.
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    if not _is_checklists_enabled():
        return {
            "error": (
                "Checklist support is disabled. "
                "Set REDMINE_CHECKLISTS_ENABLED=true to enable it."
            )
        }

    if not _is_positive_int(checklist_item_id):
        return {"error": "checklist_item_id must be a positive integer."}

    updates: Dict[str, Any] = {}
    if subject is not None:
        updates["subject"] = subject
    if is_done is not None:
        if not isinstance(is_done, bool):
            return {"error": "is_done must be a boolean."}
        updates["is_done"] = is_done
    if position is not None:
        if not _is_positive_int(position):
            return {"error": "position must be a positive integer."}
        updates["position"] = position

    if not updates:
        return {
            "error": (
                "No fields to update. Provide at least one of: "
                "subject, is_done, position."
            )
        }

    try:
        _update_checklist_item_api(checklist_item_id, updates)
        return {
            "success": True,
            "checklist_item_id": checklist_item_id,
            "updated_fields": list(updates.keys()),
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating checklist item {checklist_item_id}",
            {"resource_type": "checklist_item", "resource_id": checklist_item_id},
        )
