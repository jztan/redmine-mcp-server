"""project-dashboard MCP App: a read-only snapshot of a Redmine project.

Registers a ``ui://`` HTML resource plus an entry-point tool
(model-callable, renders the dashboard) and a backend tool (app-callable,
used by the Refresh button). KPI math lives in pure helpers so it is unit
tested without a live Redmine; the view renders the payload and drills into
the carried open-issue rows client-side.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_DASH_LIMIT = 100
_RECENT_LIMIT = 6
_OPEN_FIELDS = ["id", "subject", "status", "priority", "assigned_to", "due_date"]
_RECENT_FIELDS = ["id", "subject", "status", "updated_on"]
_UI_RESOURCE_URI = "ui://redmine/project-dashboard.html"


def _name(value: Any) -> Optional[str]:
    """Return the ``name`` of a nested Redmine object dict, or None."""
    if isinstance(value, dict):
        return value.get("name")
    return None


def _dashboard_row(issue: Dict[str, Any], today: str, week_end: str) -> Dict[str, Any]:
    """Flatten a selective issue dict into a card row, tagging due state.

    ``today`` and ``week_end`` are ISO ``YYYY-MM-DD`` strings; ISO dates
    compare correctly as strings, so no date parsing is needed. An issue is
    ``is_overdue`` when it has a due date strictly before today, and
    ``due_soon`` when today <= due_date <= week_end.
    """
    status = issue.get("status") or {}
    priority = issue.get("priority") or {}
    due = issue.get("due_date")
    return {
        "id": issue.get("id"),
        "subject": issue.get("subject", ""),
        "status_id": status.get("id"),
        "status": status.get("name"),
        "priority": priority.get("name"),
        "priority_id": priority.get("id"),
        "assigned_to": _name(issue.get("assigned_to")),
        "due_date": due,
        "is_overdue": bool(due) and due < today,
        "due_soon": bool(due) and today <= due <= week_end,
    }


def _analyze_open_issues(
    rows: List[Dict[str, Any]], priorities: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Aggregate tagged open rows into dashboard metrics (pure)."""
    counts: Dict[Any, int] = {}
    overdue = due_week = due_unassigned = 0
    for r in rows:
        counts[r.get("priority_id")] = counts.get(r.get("priority_id"), 0) + 1
        if r.get("is_overdue"):
            overdue += 1
        if r.get("due_soon"):
            due_week += 1
            if not r.get("assigned_to"):
                due_unassigned += 1
    by_priority = [
        {"id": p.get("id"), "name": p.get("name"), "count": counts.get(p.get("id"), 0)}
        for p in priorities
    ]
    return {
        "by_priority": by_priority,
        "overdue": overdue,
        "due_this_week": due_week,
        "due_unassigned": due_unassigned,
    }


def _project_name(issues: List[Dict[str, Any]], project_id: Any) -> str:
    """Best-effort project name from the first issue, else the identifier."""
    for issue in issues:
        proj = issue.get("project")
        if isinstance(proj, dict) and proj.get("name"):
            return proj["name"]
    return str(project_id)
