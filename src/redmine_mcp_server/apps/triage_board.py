"""triage-board MCP App: a read-only Kanban of Redmine issues by status.

Registers a ``ui://`` HTML resource plus an entry-point tool
(model-callable, renders the board) and a backend tool (app-callable, used
by the Refresh button). Grouping into columns is done in the iframe JS, so
there is a single grouping implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from ..tools.enumeration import list_redmine_issue_statuses
from ..tools.issues import list_redmine_issues

_BOARD_FIELDS = ["id", "subject", "status", "assigned_to", "priority", "tracker"]
_BOARD_LIMIT = 100


def _name(value: Any) -> Optional[str]:
    """Return the ``name`` of a nested Redmine object dict, or None."""
    if isinstance(value, dict):
        return value.get("name")
    return None


def _issue_row(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Redmine issue dict into a render-ready card row."""
    status = issue.get("status") or {}
    return {
        "id": issue.get("id"),
        "subject": issue.get("subject", ""),
        "status_id": status.get("id"),
        "assigned_to": _name(issue.get("assigned_to")),
        "priority": _name(issue.get("priority")),
        "tracker": _name(issue.get("tracker")),
    }


def _project_name(issues: List[Dict[str, Any]], project_id: Any) -> str:
    """Best-effort project name from the first issue, else the identifier."""
    for issue in issues:
        proj = issue.get("project")
        if isinstance(proj, dict) and proj.get("name"):
            return proj["name"]
    return str(project_id)


async def _build_board_payload(
    project_id: Union[int, str],
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the flat, render-ready triage-board payload.

    Returns an ``{"error": ...}`` dict unchanged if either underlying call
    fails.
    """
    statuses = await list_redmine_issue_statuses()
    if isinstance(statuses, dict) and "error" in statuses:
        return statuses

    issues_resp = await list_redmine_issues(
        project_id=project_id,
        status_id="*",
        fields=_BOARD_FIELDS + ["project"],
        limit=_BOARD_LIMIT,
        include_pagination_info=True,
        filters=filters,
    )
    if isinstance(issues_resp, dict) and "error" in issues_resp:
        return issues_resp

    raw_issues = issues_resp.get("issues", [])
    pagination = issues_resp.get("pagination", {}) or {}
    return {
        "project": {
            "id": project_id,
            "name": _project_name(raw_issues, project_id),
        },
        "statuses": statuses,
        "issues": [_issue_row(i) for i in raw_issues],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "truncated": bool(pagination.get("has_next")),
    }
