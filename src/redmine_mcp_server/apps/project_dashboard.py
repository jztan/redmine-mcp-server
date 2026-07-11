"""project-dashboard MCP App: a read-only snapshot of a Redmine project.

Registers a ``ui://`` HTML resource plus an entry-point tool
(model-callable, renders the dashboard) and a backend tool (app-callable,
used by the Refresh button). KPI math lives in pure helpers so it is unit
tested without a live Redmine; the view renders the payload and drills into
the carried open-issue rows client-side.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from .._env import _is_read_only_mode
from ..tools.enumeration import (
    list_redmine_issue_priorities,
    list_redmine_issue_statuses,
)
from ..tools.issues import list_redmine_issues

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


def _recent_rows(resp: Any, statuses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map a recent-issues list response to slim activity rows.

    ``resp`` is a plain list on success or an ``{"error": ...}`` dict; on
    error (or any non-list) an empty feed is returned so the rest of the
    dashboard still renders.
    """
    if not isinstance(resp, list):
        return []
    closed_ids = {s.get("id") for s in statuses if s.get("is_closed")}
    rows = []
    for issue in resp[:_RECENT_LIMIT]:
        status = issue.get("status") or {}
        rows.append(
            {
                "id": issue.get("id"),
                "subject": issue.get("subject", ""),
                "updated_on": issue.get("updated_on"),
                "status": status.get("name"),
                "is_closed": status.get("id") in closed_ids,
            }
        )
    return rows


async def _open_created_this_week(
    project_id: Union[int, str], today: Any, filters: Optional[Dict[str, Any]]
) -> Optional[int]:
    """Best-effort count of issues created in the last 7 days.

    Returns None on any failure so a fuzzy or missing number is simply not
    shown rather than surfaced as an error.
    """
    try:
        since = (today - timedelta(days=7)).isoformat()
        merged = dict(filters or {})
        merged["created_on"] = ">=" + since
        resp = await list_redmine_issues(
            project_id=project_id,
            status_id="*",
            limit=1,
            include_pagination_info=True,
            filters=merged,
        )
        if isinstance(resp, dict) and "error" in resp:
            return None
        return (resp.get("pagination", {}) or {}).get("total")
    except Exception:
        return None


async def _build_dashboard_payload(
    project_id: Union[int, str],
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the render-ready project-dashboard payload.

    Passes any underlying ``{"error": ...}`` dict through unchanged.
    """
    statuses = await list_redmine_issue_statuses()
    if isinstance(statuses, dict) and "error" in statuses:
        return statuses
    priorities = await list_redmine_issue_priorities()
    if isinstance(priorities, dict) and "error" in priorities:
        return priorities

    today = datetime.now(timezone.utc).date()
    today_s = today.isoformat()
    week_s = (today + timedelta(days=7)).isoformat()

    open_resp = await list_redmine_issues(
        project_id=project_id,
        status_id="open",
        fields=_OPEN_FIELDS,
        limit=_DASH_LIMIT,
        include_pagination_info=True,
        filters=filters,
    )
    if isinstance(open_resp, dict) and "error" in open_resp:
        return open_resp
    raw_open = open_resp.get("issues", [])
    open_pag = open_resp.get("pagination", {}) or {}
    open_count = open_pag.get("total", len(raw_open))
    rows = [_dashboard_row(i, today_s, week_s) for i in raw_open]
    analysis = _analyze_open_issues(rows, priorities)

    total_resp = await list_redmine_issues(
        project_id=project_id,
        status_id="*",
        limit=1,
        include_pagination_info=True,
        filters=filters,
    )
    if isinstance(total_resp, dict) and "error" in total_resp:
        return total_resp
    total = (total_resp.get("pagination", {}) or {}).get("total", open_count)
    closed = max(total - open_count, 0)

    recent_resp = await list_redmine_issues(
        project_id=project_id,
        status_id="*",
        sort="updated_on:desc",
        fields=_RECENT_FIELDS,
        limit=_RECENT_LIMIT,
        filters=filters,
    )
    recent = _recent_rows(recent_resp, statuses)

    open_delta = await _open_created_this_week(project_id, today, filters)

    return {
        "project": {
            "id": project_id,
            "name": _project_name(raw_open, project_id),
        },
        "totals": {"total": total, "open": open_count, "closed": closed},
        "kpis": {
            "open": open_count,
            "closed": closed,
            "overdue": analysis["overdue"],
            "due_this_week": analysis["due_this_week"],
            "due_unassigned": analysis["due_unassigned"],
            "open_delta_week": open_delta,
        },
        "by_priority": analysis["by_priority"],
        "open_issues": rows,
        "recent": recent,
        "priorities": [{"id": p.get("id"), "name": p.get("name")} for p in priorities],
        "statuses": statuses,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "truncated": bool(open_pag.get("has_next")),
        "read_only": _is_read_only_mode(),
    }
