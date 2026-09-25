"""project-timeline MCP App: a read-only Gantt-style schedule of a project.

Registers a ``ui://`` HTML resource plus an entry-point tool
(model-callable, renders the timeline) and a backend tool (app-callable,
used by the Refresh button). Window, span, state and grouping rules live in
pure helpers so they are unit tested without a live Redmine; the view only
draws the payload.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from .._env import _is_read_only_mode
from .._validation import _is_valid_project_id
from ..tools.issues import list_redmine_issues
from ..tools.projects import list_redmine_versions

_CLAMP_DAYS = 90
_ONE_SIDED_DAYS = 90
_MAX_SPAN_DAYS = 366
_EMPTY_BEFORE_DAYS = 14
_EMPTY_AFTER_DAYS = 76
_TL_LIMIT = 250
_FIELDS = [
    "id",
    "subject",
    "project",
    "status",
    "assigned_to",
    "fixed_version",
    "start_date",
    "due_date",
    "done_ratio",
    "closed_on",
]
_RESERVED_FILTER_KEYS = (
    "project_id",
    "status_id",
    "closed_on",
    "sort",
    "limit",
    "offset",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]  # fmt: skip


def _parse_day(value: Any) -> Optional[date]:
    """Return the date part of an ISO date or datetime string, or None."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_arg_date(name: str, value: Any) -> Tuple[Optional[date], Optional[str]]:
    """Parse a tool argument that must be exactly ``YYYY-MM-DD``.

    Stricter than ``date.fromisoformat``, which on 3.11+ also accepts week
    dates and compact forms.
    """
    if value is None:
        return None, None
    message = f"{name} must be a YYYY-MM-DD date."
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None, message
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, message


def _check_explicit_window(start: Optional[date], end: Optional[date]) -> Optional[str]:
    """Validate two explicit dates before snapping (one-sided cannot fail)."""
    if start is None or end is None:
        return None
    if start > end:
        return "start_date must not be after end_date."
    if (end - start).days + 1 > _MAX_SPAN_DAYS:
        return (
            "The window from start_date to end_date must not exceed "
            f"{_MAX_SPAN_DAYS} days."
        )
    return None


def _month_floor(d: date) -> date:
    return d.replace(day=1)


def _month_ceil(d: date) -> date:
    next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def _window_label(start: date, end: date) -> str:
    """Human label for a month-snapped window: a quarter, or a month range."""
    if start.month in (1, 4, 7, 10) and start.day == 1:
        quarter_end = _month_ceil(date(start.year, start.month + 2, 1))
        if end == quarter_end:
            return f"Q{(start.month - 1) // 3 + 1} {start.year}"
    first = _MONTHS[start.month - 1]
    last = _MONTHS[end.month - 1]
    if start.year != end.year:
        return f"{first} {start.year} - {last} {end.year}"
    if start.month == end.month:
        return f"{first} {start.year}"
    return f"{first} - {last} {start.year}"


def _resolve_window(
    today: date,
    start: Optional[date],
    end: Optional[date],
    dates: List[date],
) -> Dict[str, Any]:
    """Resolve the drawn window (pure). Explicit dates are already validated.

    Two explicit dates are used as given; one explicit date gets the other
    side at 90 days; with none, the window auto-fits ``dates``, clamped to
    today +/- 90 days and extended to include today. Every mode snaps
    outward to whole months, which also guarantees at least one month.
    """
    auto = start is None and end is None
    if start is not None and end is not None:
        s, e = start, end
    elif start is not None:
        s, e = start, start + timedelta(days=_ONE_SIDED_DAYS)
    elif end is not None:
        s, e = end - timedelta(days=_ONE_SIDED_DAYS), end
    elif dates:
        s = max(min(dates), today - timedelta(days=_CLAMP_DAYS))
        e = min(max(dates), today + timedelta(days=_CLAMP_DAYS))
        s, e = min(s, today), max(e, today)
    else:
        s = today - timedelta(days=_EMPTY_BEFORE_DAYS)
        e = today + timedelta(days=_EMPTY_AFTER_DAYS)
    s, e = _month_floor(s), _month_ceil(e)
    return {"start": s, "end": e, "auto": auto, "label": _window_label(s, e)}


def _row_span(
    issue: Dict[str, Any], version_due: Optional[date], closed: bool
) -> Optional[Dict[str, Any]]:
    """Where an issue is drawn, or None when it has no usable date.

    The end is the due date, else (closed issues only) the ``closed_on``
    date, else the version due date; Redmine's own Gantt uses due date then
    version due date and draws a bar only when a start exists too. Markers
    are this app's extension for single-date issues.
    """
    start = _parse_day(issue.get("start_date"))
    end, source = _parse_day(issue.get("due_date")), "due"
    if end is None and closed:
        end, source = _parse_day(issue.get("closed_on")), "closed_on"
    if end is None and version_due is not None:
        end, source = version_due, "version"
    if start is not None and end is not None:
        if end < start:
            return {"kind": "marker", "start": end, "end": end, "end_source": source}
        return {"kind": "bar", "start": start, "end": end, "end_source": source}
    if start is not None:
        return {"kind": "marker", "start": start, "end": start, "end_source": "start"}
    if end is not None:
        return {"kind": "marker", "start": end, "end": end, "end_source": source}
    return None


def _bar_state(
    span: Dict[str, Any], closed: bool, done_ratio: Any, today: date
) -> Tuple[str, bool]:
    """Return ``(state, overdue)`` for a span; overdue is strictly past."""
    if closed:
        return "done", False
    overdue = span["end_source"] in ("due", "version") and span["end"] < today
    if (done_ratio or 0) > 0 or span["start"] <= today:
        return "in_progress", overdue
    return "planned", overdue


def _issue_row(
    issue: Dict[str, Any],
    closed: bool,
    version_due: Optional[date],
    today: date,
    win_start: date,
    win_end: date,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Build one issue row, or report it as ``outside`` / ``unscheduled``."""
    span = _row_span(issue, version_due, closed)
    if span is None:
        return "unscheduled", None
    if span["end"] < win_start or span["start"] > win_end:
        return "outside", None
    state, overdue = _bar_state(span, closed, issue.get("done_ratio"), today)
    status = issue.get("status") or {}
    assignee = issue.get("assigned_to")
    return "row", {
        "type": "issue",
        "id": issue.get("id"),
        "subject": issue.get("subject", ""),
        "status": status.get("name"),
        "assigned_to": assignee.get("name") if isinstance(assignee, dict) else None,
        "start": span["start"].isoformat(),
        "end": span["end"].isoformat(),
        "kind": span["kind"],
        "state": state,
        "done_ratio": issue.get("done_ratio") or 0,
        "overdue": overdue,
        "end_source": span["end_source"],
        "clipped_start": span["start"] < win_start,
        "clipped_end": span["end"] > win_end,
    }


def _group_rows(
    entries: List[Tuple[Dict[str, Any], Any, bool]],
    versions: List[Dict[str, Any]],
    win_start: date,
    win_end: date,
) -> List[Dict[str, Any]]:
    """Group issue rows by version, then No version, then one Done group.

    ``entries`` holds ``(row, fixed_version_ref, closed)``. Only versions
    with at least one row get a group, so shared versions with no work here
    never show as empty groups. A version's milestone row follows its
    issues; a version without a due date has no milestone.
    """
    by_id = {v.get("id"): v for v in versions}
    buckets: Dict[Any, List[Dict[str, Any]]] = {}
    refs: Dict[Any, Dict[str, Any]] = {}
    none_open: List[Dict[str, Any]] = []
    none_closed: List[Dict[str, Any]] = []
    for row, ref, closed in entries:
        vid = ref.get("id") if isinstance(ref, dict) else None
        if vid is None:
            (none_closed if closed else none_open).append(row)
            continue
        buckets.setdefault(vid, []).append(row)
        refs.setdefault(vid, ref)

    def sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(rows, key=lambda r: (r["start"], r["end"], r.get("id") or 0))

    def version_name(vid: Any) -> str:
        return (by_id.get(vid) or refs[vid]).get("name") or ""

    def order_key(vid: Any) -> Tuple[bool, str, str]:
        due = (by_id.get(vid) or {}).get("due_date")
        return (due is None, due or "", version_name(vid))

    def version_rows(vid: Any) -> List[Dict[str, Any]]:
        rows = sort_rows(buckets[vid])
        v = by_id.get(vid)
        due = _parse_day(v.get("due_date")) if v else None
        if due is not None:
            rows.append(
                {
                    "type": "milestone",
                    "version_id": vid,
                    "label": f"{version_name(vid)} release",
                    "date": due.isoformat(),
                    "closed": v.get("status") == "closed",
                    "in_window": win_start <= due <= win_end,
                }
            )
        return rows

    def is_closed(vid: Any) -> bool:
        return (by_id.get(vid) or {}).get("status") == "closed"

    groups: List[Dict[str, Any]] = []
    for vid in sorted((v for v in buckets if not is_closed(v)), key=order_key):
        groups.append(
            {
                "key": f"version:{vid}",
                "title": version_name(vid),
                "description": (by_id.get(vid) or {}).get("description") or None,
                "rows": version_rows(vid),
            }
        )
    if none_open:
        groups.append(
            {
                "key": "none",
                "title": "No version",
                "description": None,
                "rows": sort_rows(none_open),
            }
        )
    done_rows: List[Dict[str, Any]] = []
    for vid in sorted((v for v in buckets if is_closed(v)), key=order_key):
        done_rows.extend(version_rows(vid))
    done_rows.extend(sort_rows(none_closed))
    if done_rows:
        groups.append(
            {"key": "done", "title": "Done", "description": None, "rows": done_rows}
        )
    return groups


def _reject_timeline_filters(filters: Any) -> Optional[str]:
    """Refuse filters that would override what the builder controls.

    ``list_redmine_issues`` spreads ``filters`` over its named parameters
    and pops ``limit``/``offset`` out of the caller's dict, so these keys
    would silently break the open/closed split or the cap.
    """
    if filters is None:
        return None
    if not isinstance(filters, dict):
        return "filters must be an object (a JSON dict)."
    for key in _RESERVED_FILTER_KEYS:
        if key in filters:
            return f"filters must not contain '{key}'; the timeline sets it itself."
    return None


def _is_error(resp: Any) -> bool:
    return isinstance(resp, dict) and "error" in resp


def _project_name(issue_lists: List[List[Dict[str, Any]]], project_id: Any) -> str:
    """First project name found on an open, then a closed row, else the id."""
    for issues in issue_lists:
        for issue in issues:
            proj = issue.get("project")
            if isinstance(proj, dict) and proj.get("name"):
                return proj["name"]
    return str(project_id)


async def _build_timeline_payload(
    project_id: Union[int, str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Assemble the render-ready project-timeline payload.

    Order matters: the window is resolved from the open rows and versions
    before the closed query, whose ``closed_on`` bound is the window start.
    An error from the open query passes through unchanged; a failed closed
    or versions query renders what is left and sets ``partial``.
    """
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    start, err = _parse_arg_date("start_date", start_date)
    if err:
        return {"error": err}
    end, err = _parse_arg_date("end_date", end_date)
    if err:
        return {"error": err}
    err = _check_explicit_window(start, end) or _reject_timeline_filters(filters)
    if err:
        return {"error": err}
    if today is None:
        today = datetime.now(timezone.utc).date()

    open_resp = await list_redmine_issues(
        project_id=project_id,
        status_id="open",
        fields=_FIELDS,
        limit=_TL_LIMIT,
        sort="start_date:desc,id:desc",
        include_pagination_info=True,
        filters=dict(filters or {}),
    )
    if _is_error(open_resp):
        return open_resp
    open_issues = open_resp.get("issues", [])
    truncated = bool((open_resp.get("pagination") or {}).get("has_next"))

    partial = False
    versions_resp = await list_redmine_versions(project_id=project_id)
    if isinstance(versions_resp, list):
        versions = versions_resp
    else:
        versions, partial = [], True
    version_due = {v.get("id"): _parse_day(v.get("due_date")) for v in versions}

    def due_for(issue: Dict[str, Any]) -> Optional[date]:
        ref = issue.get("fixed_version")
        return version_due.get(ref.get("id")) if isinstance(ref, dict) else None

    dates: List[date] = []
    for issue in open_issues:
        span = _row_span(issue, due_for(issue), closed=False)
        if span is not None:
            dates.extend([span["start"], span["end"]])
    dates.extend(
        d
        for v in versions
        if v.get("status") != "closed"
        for d in [_parse_day(v.get("due_date"))]
        if d is not None
    )
    window = _resolve_window(today, start, end, dates)

    closed_resp = await list_redmine_issues(
        project_id=project_id,
        status_id="closed",
        fields=_FIELDS,
        limit=_TL_LIMIT,
        sort="closed_on:desc,id:desc",
        include_pagination_info=True,
        filters={**(filters or {}), "closed_on": ">=" + window["start"].isoformat()},
    )
    if _is_error(closed_resp):
        closed_issues, partial = [], True
    else:
        closed_issues = closed_resp.get("issues", [])
        truncated = truncated or bool(
            (closed_resp.get("pagination") or {}).get("has_next")
        )

    entries: List[Tuple[Dict[str, Any], Any, bool]] = []
    unscheduled = 0
    for issues, closed in ((open_issues, False), (closed_issues, True)):
        for issue in issues:
            kind, row = _issue_row(
                issue, closed, due_for(issue), today, window["start"], window["end"]
            )
            if kind == "unscheduled":
                unscheduled += 1
            elif row is not None:
                entries.append((row, issue.get("fixed_version"), closed))

    return {
        "project": {
            "id": project_id,
            "name": _project_name([open_issues, closed_issues], project_id),
        },
        "window": {
            "start": window["start"].isoformat(),
            "end": window["end"].isoformat(),
            "today": today.isoformat(),
            "auto": window["auto"],
            "label": window["label"],
        },
        "groups": _group_rows(entries, versions, window["start"], window["end"]),
        "unscheduled": unscheduled,
        "truncated": truncated,
        "partial": partial,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": _is_read_only_mode(),
    }
