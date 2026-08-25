"""RedmineUP CRM saved queries (contact and deal query lists).

``GET /crm_queries.json`` requires ``object_type`` (``contact`` or ``deal``;
anything else is a 404) and pages with ``limit``/``offset``. Like notes, the
tool spans both CRM families, so it is available with either flag and gated
per call on the flag matching ``object_type``.
"""

from typing import Any, Dict, List, Literal, Union

from .._client import _get_redmine_client
from .._errors import _handle_redmine_error
from .._offload import offloaded
from .._plugin_visibility import plugin_tag
from .._serialization import _REDMINE_API_PAGE_CAP
from .._validation import _is_positive_int
from ..server import mcp
from .crm_notes import _CRM_NOTES_DISABLED_ERROR, _is_crm_notes_enabled, _source_gate


def _crm_query_to_dict(query: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize one entry of app/views/crm_queries/index.api.rsb."""
    if not isinstance(query, dict):
        return {}
    return {
        "id": query.get("id"),
        "name": query.get("name", ""),
        "is_public": bool(query.get("is_public", False)),
        "project_id": query.get("project_id"),
    }


@offloaded
def _list_crm_queries_impl(
    object_type: str, limit: int, offset: int
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    if object_type not in ("contact", "deal"):
        return {"error": "object_type must be 'contact' or 'deal'."}
    gate = _source_gate(object_type)
    if gate:
        return gate
    if not _is_positive_int(limit) or limit > _REDMINE_API_PAGE_CAP:
        return {"error": f"limit must be between 1 and {_REDMINE_API_PAGE_CAP}."}
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return {"error": "offset must be a non-negative integer."}
    from .. import _client

    try:
        client = _get_redmine_client()
        payload = client.engine.request(
            "get",
            f"{_client.REDMINE_URL}/crm_queries.json",
            params={"object_type": object_type, "limit": limit, "offset": offset},
        )
        raw = payload.get("queries", []) if isinstance(payload, dict) else []
        return [_crm_query_to_dict(q) for q in raw]
    except Exception as e:
        return _handle_redmine_error(
            e, "listing CRM queries", {"resource_type": f"{object_type} queries"}
        )


@mcp.tool(tags={plugin_tag("crm-shared")})
async def list_crm_queries(
    object_type: Literal["contact", "deal"],
    limit: int = 25,
    offset: int = 0,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List saved RedmineUP CRM queries for contacts or deals.

    Saved queries are the named filters users build in the CRM's contact and
    deal lists. Available with ``REDMINE_CRM_ENABLED`` (``contact``) or
    ``REDMINE_DEALS_ENABLED`` (``deal``).

    Args:
        object_type: ``contact`` or ``deal``.
        limit: Queries per call, 1 to 100 (default 25).
        offset: Paging offset (default 0).

    Returns:
        A list of ``{id, name, is_public, project_id}`` (``project_id`` is
        ``None`` for global queries), or ``{"error": ...}``.
    """
    if not _is_crm_notes_enabled():
        return dict(_CRM_NOTES_DISABLED_ERROR)
    return await _list_crm_queries_impl(object_type, limit, offset)
