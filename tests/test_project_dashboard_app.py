import pytest
from unittest.mock import AsyncMock, patch

from redmine_mcp_server.apps import project_dashboard as pd

_PRIORITIES = [
    {"id": 1, "name": "Low", "active": True, "is_default": False},
    {"id": 2, "name": "Normal", "active": True, "is_default": True},
    {"id": 3, "name": "High", "active": True, "is_default": False},
    {"id": 4, "name": "Urgent", "active": True, "is_default": False},
]


def _issue(**kw):
    base = {
        "id": 42,
        "subject": "Fix login",
        "status": {"id": 1, "name": "New"},
        "priority": {"id": 2, "name": "Normal"},
        "assigned_to": {"id": 7, "name": "Alice"},
        "due_date": None,
    }
    base.update(kw)
    return base


def test_dashboard_row_flattens_and_tags_overdue():
    row = pd._dashboard_row(_issue(due_date="2026-07-01"), "2026-07-11", "2026-07-18")
    assert row == {
        "id": 42,
        "subject": "Fix login",
        "status_id": 1,
        "status": "New",
        "priority": "Normal",
        "priority_id": 2,
        "assigned_to": "Alice",
        "due_date": "2026-07-01",
        "is_overdue": True,
        "due_soon": False,
    }


def test_dashboard_row_due_soon_boundaries():
    # today itself and the +7 edge are "due_soon"; the day after is not.
    assert (
        pd._dashboard_row(_issue(due_date="2026-07-11"), "2026-07-11", "2026-07-18")[
            "due_soon"
        ]
        is True
    )
    assert (
        pd._dashboard_row(_issue(due_date="2026-07-18"), "2026-07-11", "2026-07-18")[
            "due_soon"
        ]
        is True
    )
    assert (
        pd._dashboard_row(_issue(due_date="2026-07-19"), "2026-07-11", "2026-07-18")[
            "due_soon"
        ]
        is False
    )


def test_dashboard_row_no_due_date_is_neither():
    row = pd._dashboard_row(_issue(due_date=None), "2026-07-11", "2026-07-18")
    assert row["is_overdue"] is False and row["due_soon"] is False


def test_dashboard_row_unassigned():
    row = pd._dashboard_row(_issue(assigned_to=None), "2026-07-11", "2026-07-18")
    assert row["assigned_to"] is None


def test_analyze_open_issues_priority_breakdown_ordered_with_zeros():
    rows = [
        pd._dashboard_row(
            _issue(id=1, priority={"id": 4, "name": "Urgent"}),
            "2026-07-11",
            "2026-07-18",
        ),
        pd._dashboard_row(
            _issue(id=2, priority={"id": 4, "name": "Urgent"}),
            "2026-07-11",
            "2026-07-18",
        ),
        pd._dashboard_row(
            _issue(id=3, priority={"id": 2, "name": "Normal"}),
            "2026-07-11",
            "2026-07-18",
        ),
    ]
    out = pd._analyze_open_issues(rows, _PRIORITIES)
    assert out["by_priority"] == [
        {"id": 1, "name": "Low", "count": 0},
        {"id": 2, "name": "Normal", "count": 1},
        {"id": 3, "name": "High", "count": 0},
        {"id": 4, "name": "Urgent", "count": 2},
    ]


def test_analyze_open_issues_overdue_and_due_counts():
    rows = [
        pd._dashboard_row(
            _issue(id=1, due_date="2026-07-01"), "2026-07-11", "2026-07-18"
        ),  # overdue
        pd._dashboard_row(
            _issue(id=2, due_date="2026-07-15", assigned_to=None),
            "2026-07-11",
            "2026-07-18",
        ),  # due, unassigned
        pd._dashboard_row(
            _issue(id=3, due_date="2026-07-16"), "2026-07-11", "2026-07-18"
        ),  # due, assigned
    ]
    out = pd._analyze_open_issues(rows, _PRIORITIES)
    assert out["overdue"] == 1
    assert out["due_this_week"] == 2
    assert out["due_unassigned"] == 1


def test_project_name_prefers_first_issue_then_falls_back():
    assert pd._project_name([{"project": {"id": 9, "name": "Web"}}], 9) == "Web"
    assert pd._project_name([], "my-proj") == "my-proj"


_STATUSES = [
    {"id": 1, "name": "New", "is_closed": False},
    {"id": 2, "name": "In Progress", "is_closed": False},
    {"id": 5, "name": "Closed", "is_closed": True},
]


def _open_resp(issues, has_next=False, total=None):
    pag = {"has_next": has_next}
    if total is not None:
        pag["total"] = total
    return {"issues": issues, "pagination": pag}


def _patch_calls(statuses, priorities, list_side_effect, delta=4):
    return (
        patch.object(
            pd, "list_redmine_issue_statuses", AsyncMock(return_value=statuses)
        ),
        patch.object(
            pd, "list_redmine_issue_priorities", AsyncMock(return_value=priorities)
        ),
        patch.object(
            pd, "list_redmine_issues", AsyncMock(side_effect=list_side_effect)
        ),
        patch.object(pd, "_open_created_this_week", AsyncMock(return_value=delta)),
    )


@pytest.mark.asyncio
async def test_build_payload_assembles_totals_and_kpis():
    open_issue = _issue(
        id=1, project={"id": 9, "name": "Web"}, due_date="2000-01-01"
    )  # overdue vs any real "today"
    side = [
        _open_resp([open_issue], has_next=False, total=1),  # open fetch
        _open_resp([], total=3),  # total count
        [],  # recent (list)
    ]
    ps, pp, pl, pd_delta = _patch_calls(_STATUSES, _PRIORITIES, side)
    with ps, pp, pl, pd_delta:
        payload = await pd._build_dashboard_payload(9)
    assert payload["project"] == {"id": 9, "name": "Web"}
    assert payload["totals"] == {"total": 3, "open": 1, "closed": 2}
    assert payload["kpis"]["open"] == 1
    assert payload["kpis"]["closed"] == 2
    assert payload["kpis"]["overdue"] == 1
    assert payload["kpis"]["open_delta_week"] == 4
    assert payload["statuses"] == _STATUSES
    assert payload["priorities"] == [
        {"id": 1, "name": "Low"},
        {"id": 2, "name": "Normal"},
        {"id": 3, "name": "High"},
        {"id": 4, "name": "Urgent"},
    ]
    assert len(payload["open_issues"]) == 1
    assert payload["truncated"] is False


@pytest.mark.asyncio
async def test_build_payload_recent_maps_is_closed():
    recent = [
        {
            "id": 5,
            "subject": "Done",
            "status": {"id": 5, "name": "Closed"},
            "updated_on": "2026-07-11T08:00:00Z",
        },
        {
            "id": 6,
            "subject": "Working",
            "status": {"id": 2, "name": "In Progress"},
            "updated_on": "2026-07-11T07:00:00Z",
        },
    ]
    side = [_open_resp([], total=2), _open_resp([], total=2), recent]
    ps, pp, pl, pd_delta = _patch_calls(_STATUSES, _PRIORITIES, side)
    with ps, pp, pl, pd_delta:
        payload = await pd._build_dashboard_payload(9)
    assert payload["recent"][0] == {
        "id": 5,
        "subject": "Done",
        "updated_on": "2026-07-11T08:00:00Z",
        "status": "Closed",
        "is_closed": True,
    }
    assert payload["recent"][1]["is_closed"] is False


@pytest.mark.asyncio
async def test_build_payload_truncated_flag():
    side = [
        _open_resp([_issue()], has_next=True, total=200),
        _open_resp([], total=200),
        [],
    ]
    ps, pp, pl, pd_delta = _patch_calls(_STATUSES, _PRIORITIES, side)
    with ps, pp, pl, pd_delta:
        payload = await pd._build_dashboard_payload(9)
    assert payload["truncated"] is True


@pytest.mark.asyncio
async def test_build_payload_passes_through_statuses_error():
    ps, pp, pl, pd_delta = _patch_calls({"error": "boom"}, _PRIORITIES, [])
    with ps, pp, pl, pd_delta:
        payload = await pd._build_dashboard_payload(9)
    assert payload == {"error": "boom"}


@pytest.mark.asyncio
async def test_build_payload_passes_through_open_fetch_error():
    side = [{"error": "no access"}]
    ps, pp, pl, pd_delta = _patch_calls(_STATUSES, _PRIORITIES, side)
    with ps, pp, pl, pd_delta:
        payload = await pd._build_dashboard_payload(9)
    assert payload == {"error": "no access"}


@pytest.mark.asyncio
async def test_build_payload_read_only_reflected():
    side = [_open_resp([], total=0), _open_resp([], total=0), []]
    ps, pp, pl, pd_delta = _patch_calls(_STATUSES, _PRIORITIES, side)
    with (
        ps,
        pp,
        pl,
        pd_delta,
        patch.object(pd, "_is_read_only_mode", return_value=True),
    ):
        payload = await pd._build_dashboard_payload(9)
    assert payload["read_only"] is True


@pytest.mark.asyncio
async def test_open_created_this_week_returns_none_on_error():
    with patch.object(
        pd, "list_redmine_issues", AsyncMock(return_value={"error": "x"})
    ):
        from datetime import date

        got = await pd._open_created_this_week(9, date(2026, 7, 11), None)
    assert got is None
