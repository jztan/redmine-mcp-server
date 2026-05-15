"""Gantt chart tool — composite read tool for project timeline data."""

from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import Field

from .._client import _get_redmine_client
from .._errors import _handle_redmine_error
from .._serialization import (
    _DEFAULT_LIST_RESULT_CAP,
    _iter_capped,
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_valid_project_id
from ..server import mcp


def _gantt_issue_to_dict(issue: Any) -> Dict[str, Any]:
    """Serialize an issue for Gantt output.

    Includes scheduling fields (``start_date``, ``due_date``, ``done_ratio``,
    ``estimated_hours``, ``parent``) that ``_issue_to_dict`` omits, plus
    relations when present.
    """
    parent = getattr(issue, "parent", None)
    parent_id: Optional[int] = None
    if parent is not None:
        parent_id = getattr(parent, "id", None)

    out: Dict[str, Any] = {
        "id": getattr(issue, "id", None),
        "subject": wrap_insecure_content(getattr(issue, "subject", "")),
        "tracker": _named_ref(getattr(issue, "tracker", None)),
        "status": _named_ref(getattr(issue, "status", None)),
        "assigned_to": _named_ref(getattr(issue, "assigned_to", None)),
        "start_date": _safe_isoformat(getattr(issue, "start_date", None)),
        "due_date": _safe_isoformat(getattr(issue, "due_date", None)),
        "done_ratio": getattr(issue, "done_ratio", 0),
        "estimated_hours": getattr(issue, "estimated_hours", None),
        "parent_id": parent_id,
    }

    rel_list: List[Dict[str, Any]] = []
    relations = getattr(issue, "relations", None)
    if relations is not None:
        for rel in _iter_capped(relations):
            rel_type = getattr(rel, "relation_type", None)
            if rel_type not in {"precedes", "blocks"}:
                continue
            rel_list.append(
                {
                    "id": getattr(rel, "id", None),
                    "relation_type": rel_type,
                    "issue_id": getattr(rel, "issue_id", None),
                    "issue_to_id": getattr(rel, "issue_to_id", None),
                    "delay": getattr(rel, "delay", None),
                }
            )
    out["relations"] = rel_list
    return out


def _gantt_version_to_dict(version: Any) -> Dict[str, Any]:
    return {
        "id": getattr(version, "id", None),
        "name": wrap_insecure_content(getattr(version, "name", "")),
        "due_date": _safe_isoformat(getattr(version, "due_date", None)),
        "status": getattr(version, "status", None),
    }


@mcp.tool()
async def get_gantt_chart(
    project_id: Union[str, int],
    start_date_after: Optional[str] = None,
    due_date_before: Optional[str] = None,
    include_closed: bool = False,
    limit: Annotated[int, Field(ge=1, le=500)] = 250,
) -> Dict[str, Any]:
    """Retrieve project timeline (Gantt) data: issues with dates, dependencies,
    and milestones.

    Composite tool that aggregates ``GET /issues.json`` (with relations) and
    ``GET /projects/{id}/versions.json`` into a single structured response
    suitable for timeline analysis. Returns structured data, not an image.

    Use cases: "What's the current timeline for project X?", "Which issues
    are overdue?", "Show me the dependency chain on this project".

    Uses the core Redmine REST API only — no plugin required.

    Performance note: Redmine paginates issues at 25 per HTTP call by
    default, so a request for ``limit=500`` can trigger ~20 underlying
    API calls. Expect a few seconds of latency on large projects.

    Args:
        project_id: Project identifier (ID or string).
        start_date_after: Optional ``YYYY-MM-DD`` filter (issues whose
            ``start_date`` is on or after this date).
        due_date_before: Optional ``YYYY-MM-DD`` filter (issues whose
            ``due_date`` is on or before this date).
        include_closed: When ``True``, include closed issues. Default
            ``False``: only open issues are returned, which keeps response
            size and pagination cost low on long-lived projects.
        limit: Maximum number of issues to return (1-500, default 250).

    Returns:
        Dict with: ``project_id``, ``issues`` (list with date fields,
        progress, parent_id, relations), ``versions`` (list of milestones),
        ``total_count``.
    """
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"error": "limit must be a positive integer."}
    limit = min(limit, _DEFAULT_LIST_RESULT_CAP)

    try:
        client = _get_redmine_client()

        issue_filters: Dict[str, Any] = {
            "project_id": project_id,
            "include": "relations",
        }
        if include_closed:
            issue_filters["status_id"] = "*"
        if start_date_after:
            issue_filters["start_date"] = f">={start_date_after}"
        if due_date_before:
            issue_filters["due_date"] = f"<={due_date_before}"

        issues_resource = client.issue.filter(**issue_filters)
        issues_list = [
            _gantt_issue_to_dict(i) for i in _iter_capped(issues_resource, limit)
        ]

        try:
            versions_resource = client.version.filter(project_id=project_id)
            versions_list = [
                _gantt_version_to_dict(v) for v in _iter_capped(versions_resource)
            ]
        except Exception:
            versions_list = []

        return {
            "project_id": project_id,
            "total_count": len(issues_list),
            "issues": issues_list,
            "versions": versions_list,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching Gantt data for project {project_id}",
            {"resource_type": "gantt", "resource_id": project_id},
        )
