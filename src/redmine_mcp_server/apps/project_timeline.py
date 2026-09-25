"""project-timeline MCP App: a read-only Gantt-style schedule of a project.

Registers a ``ui://`` HTML resource plus an entry-point tool
(model-callable, renders the timeline) and a backend tool (app-callable,
used by the Refresh button). Window, span, state and grouping rules live in
pure helpers so they are unit tested without a live Redmine; the view only
draws the payload.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

_CLAMP_DAYS = 90
_ONE_SIDED_DAYS = 90
_MAX_SPAN_DAYS = 366
_EMPTY_BEFORE_DAYS = 14
_EMPTY_AFTER_DAYS = 76
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
