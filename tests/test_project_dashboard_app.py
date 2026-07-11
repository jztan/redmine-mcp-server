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
