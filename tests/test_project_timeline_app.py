from datetime import date

import pytest

from redmine_mcp_server.apps import project_timeline as tl

TODAY = date(2026, 9, 25)


def test_parse_day_accepts_date_and_datetime_strings():
    assert tl._parse_day("2026-07-04") == date(2026, 7, 4)
    assert tl._parse_day("2026-07-04T14:38:25") == date(2026, 7, 4)
    assert tl._parse_day(None) is None
    assert tl._parse_day("") is None
    assert tl._parse_day("not-a-date") is None


def test_parse_arg_date_strict_format():
    assert tl._parse_arg_date("start_date", None) == (None, None)
    assert tl._parse_arg_date("start_date", "2026-07-01") == (date(2026, 7, 1), None)
    for bad in ["2026-7-1", "20260701", "2026-W27-1", "2026-02-30", 20260701]:
        value, err = tl._parse_arg_date("start_date", bad)
        assert value is None
        assert err == "start_date must be a YYYY-MM-DD date."


def test_check_explicit_window():
    assert tl._check_explicit_window(None, None) is None
    assert tl._check_explicit_window(date(2026, 7, 1), None) is None
    assert tl._check_explicit_window(date(2026, 7, 1), date(2026, 7, 1)) is None
    assert (
        tl._check_explicit_window(date(2026, 8, 1), date(2026, 7, 1))
        == "start_date must not be after end_date."
    )
    # 366 days inclusive is allowed, 367 is not.
    assert tl._check_explicit_window(date(2026, 1, 1), date(2027, 1, 1)) is None
    assert (
        tl._check_explicit_window(date(2026, 1, 1), date(2027, 1, 2))
        == "The window from start_date to end_date must not exceed 366 days."
    )


def test_month_floor_and_ceil():
    assert tl._month_floor(date(2026, 9, 25)) == date(2026, 9, 1)
    assert tl._month_ceil(date(2026, 9, 25)) == date(2026, 9, 30)
    assert tl._month_ceil(date(2026, 2, 3)) == date(2026, 2, 28)
    assert tl._month_ceil(date(2026, 12, 31)) == date(2026, 12, 31)


def test_window_label_quarter_same_year_and_cross_year():
    assert tl._window_label(date(2026, 7, 1), date(2026, 9, 30)) == "Q3 2026"
    assert tl._window_label(date(2026, 7, 1), date(2026, 11, 30)) == "Jul - Nov 2026"
    assert tl._window_label(date(2026, 9, 1), date(2026, 9, 30)) == "Sep 2026"
    assert (
        tl._window_label(date(2026, 11, 1), date(2027, 2, 28)) == "Nov 2026 - Feb 2027"
    )


def test_resolve_window_two_explicit_dates_snap_to_months():
    w = tl._resolve_window(TODAY, date(2026, 7, 10), date(2026, 9, 3), [])
    assert (w["start"], w["end"], w["auto"]) == (
        date(2026, 7, 1),
        date(2026, 9, 30),
        False,
    )
    assert w["label"] == "Q3 2026"


def test_resolve_window_one_sided_start():
    w = tl._resolve_window(TODAY, date(2026, 10, 15), None, [])
    # 2026-10-15 + 90d = 2027-01-13, snapped to month ends.
    assert (w["start"], w["end"], w["auto"]) == (
        date(2026, 10, 1),
        date(2027, 1, 31),
        False,
    )


def test_resolve_window_one_sided_end_in_the_past_skips_today():
    w = tl._resolve_window(TODAY, None, date(2026, 1, 31), [])
    # start = end - 90d = 2025-11-02; today is NOT pulled in.
    assert (w["start"], w["end"], w["auto"]) == (
        date(2025, 11, 1),
        date(2026, 1, 31),
        False,
    )


def test_resolve_window_auto_fits_data_inside_clamp():
    dates = [date(2026, 8, 20), date(2026, 10, 5)]
    w = tl._resolve_window(TODAY, None, None, dates)
    assert (w["start"], w["end"], w["auto"]) == (
        date(2026, 8, 1),
        date(2026, 10, 31),
        True,
    )


def test_resolve_window_auto_clamps_both_sides():
    dates = [date(2025, 1, 1), date(2028, 1, 1)]
    w = tl._resolve_window(TODAY, None, None, dates)
    # today-90 = 2026-06-27, today+90 = 2026-12-24.
    assert (w["start"], w["end"]) == (date(2026, 6, 1), date(2026, 12, 31))


def test_resolve_window_auto_includes_today_when_all_data_is_future():
    dates = [date(2027, 6, 1), date(2027, 8, 1)]
    w = tl._resolve_window(TODAY, None, None, dates)
    assert (w["start"], w["end"]) == (date(2026, 9, 1), date(2026, 12, 31))


def test_resolve_window_auto_includes_today_when_all_data_is_old():
    dates = [date(2025, 1, 1), date(2025, 3, 1)]
    w = tl._resolve_window(TODAY, None, None, dates)
    assert (w["start"], w["end"]) == (date(2026, 6, 1), date(2026, 9, 30))


def test_resolve_window_auto_without_data():
    w = tl._resolve_window(TODAY, None, None, [])
    # today-14 = 2026-09-11, today+76 = 2026-12-10.
    assert (w["start"], w["end"], w["auto"]) == (
        date(2026, 9, 1),
        date(2026, 12, 31),
        True,
    )


def _iss(**kw):
    base = {
        "id": 42,
        "subject": "Fix login",
        "status": {"id": 1, "name": "New"},
        "assigned_to": {"id": 7, "name": "Alice"},
        "fixed_version": None,
        "start_date": None,
        "due_date": None,
        "done_ratio": 0,
        "closed_on": None,
    }
    base.update(kw)
    return base


V_DUE = date(2026, 10, 15)


@pytest.mark.parametrize(
    "kw, version_due, expected",
    [
        (
            {"start_date": "2026-09-01", "due_date": "2026-09-20"},
            V_DUE,
            ("bar", date(2026, 9, 1), date(2026, 9, 20), "due"),
        ),
        (
            {"start_date": "2026-09-01"},
            V_DUE,
            ("bar", date(2026, 9, 1), V_DUE, "version"),
        ),
        (
            {"start_date": "2026-09-01"},
            None,
            ("marker", date(2026, 9, 1), date(2026, 9, 1), "start"),
        ),
        (
            {"due_date": "2026-09-20"},
            V_DUE,
            ("marker", date(2026, 9, 20), date(2026, 9, 20), "due"),
        ),
        (
            {},
            V_DUE,
            ("marker", V_DUE, V_DUE, "version"),
        ),
        (
            # Due before start: marker at the due date.
            {"start_date": "2026-09-20", "due_date": "2026-09-01"},
            None,
            ("marker", date(2026, 9, 1), date(2026, 9, 1), "due"),
        ),
    ],
)
def test_row_span_table(kw, version_due, expected):
    span = tl._row_span(_iss(**kw), version_due, closed=False)
    assert (span["kind"], span["start"], span["end"], span["end_source"]) == expected


def test_row_span_unscheduled_returns_none():
    assert tl._row_span(_iss(), None, closed=False) is None


def test_row_span_closed_uses_closed_on_before_version_due():
    issue = _iss(start_date="2026-02-20", closed_on="2026-07-04T14:38:25")
    span = tl._row_span(issue, V_DUE, closed=True)
    assert (span["kind"], span["start"], span["end"], span["end_source"]) == (
        "bar",
        date(2026, 2, 20),
        date(2026, 7, 4),
        "closed_on",
    )


def test_row_span_closed_without_start_is_marker_at_closed_on():
    span = tl._row_span(_iss(closed_on="2026-07-04T00:00:00"), None, closed=True)
    assert (span["kind"], span["end"], span["end_source"]) == (
        "marker",
        date(2026, 7, 4),
        "closed_on",
    )


def test_row_span_closed_on_not_used_when_due_exists():
    issue = _iss(start_date="2026-06-01", due_date="2026-06-10", closed_on="2026-07-04")
    span = tl._row_span(issue, None, closed=True)
    assert (span["end"], span["end_source"]) == (date(2026, 6, 10), "due")


def test_row_span_closed_on_ignored_for_open_issues():
    issue = _iss(start_date="2026-06-01", closed_on="2026-07-04")
    span = tl._row_span(issue, None, closed=False)
    assert span["end_source"] == "start"


def _span(start, end, source="due", kind="bar"):
    return {"kind": kind, "start": start, "end": end, "end_source": source}


def test_bar_state_done_for_closed():
    s = _span(date(2026, 1, 1), date(2026, 1, 5))
    assert tl._bar_state(s, True, 0, TODAY) == ("done", False)


def test_bar_state_in_progress_by_start_or_ratio():
    started = _span(TODAY, date(2026, 10, 30))
    assert tl._bar_state(started, False, 0, TODAY) == ("in_progress", False)
    future_with_ratio = _span(date(2026, 10, 1), date(2026, 10, 30))
    assert tl._bar_state(future_with_ratio, False, 10, TODAY) == (
        "in_progress",
        False,
    )


def test_bar_state_planned_when_future_and_zero_ratio():
    s = _span(date(2026, 10, 1), date(2026, 10, 30))
    assert tl._bar_state(s, False, 0, TODAY) == ("planned", False)
    assert tl._bar_state(s, False, None, TODAY) == ("planned", False)


def test_bar_state_overdue_flag():
    s = _span(date(2026, 9, 1), date(2026, 9, 24))
    assert tl._bar_state(s, False, 50, TODAY) == ("in_progress", True)
    inferred = _span(date(2026, 9, 1), date(2026, 9, 24), source="version")
    assert tl._bar_state(inferred, False, 0, TODAY)[1] is True


def test_due_today_is_not_overdue():
    s = _span(date(2026, 9, 1), TODAY)
    assert tl._bar_state(s, False, 0, TODAY)[1] is False


def test_marker_at_start_is_never_overdue():
    s = _span(date(2026, 9, 1), date(2026, 9, 1), source="start", kind="marker")
    assert tl._bar_state(s, False, 0, TODAY)[1] is False


WS, WE = date(2026, 9, 1), date(2026, 11, 30)


def test_issue_row_inside_window():
    issue = _iss(id=5, start_date="2026-09-10", due_date="2026-09-20", done_ratio=30)
    kind, row = tl._issue_row(issue, False, None, TODAY, WS, WE)
    assert kind == "row"
    assert row == {
        "type": "issue",
        "id": 5,
        "subject": "Fix login",
        "status": "New",
        "assigned_to": "Alice",
        "start": "2026-09-10",
        "end": "2026-09-20",
        "kind": "bar",
        "state": "in_progress",
        "done_ratio": 30,
        "overdue": True,
        "end_source": "due",
        "clipped_start": False,
        "clipped_end": False,
    }


def test_issue_row_clipped_keeps_true_dates():
    issue = _iss(start_date="2026-08-01", due_date="2026-12-20")
    kind, row = tl._issue_row(issue, False, None, TODAY, WS, WE)
    assert kind == "row"
    assert (row["start"], row["end"]) == ("2026-08-01", "2026-12-20")
    assert (row["clipped_start"], row["clipped_end"]) == (True, True)


def test_issue_row_outside_and_unscheduled():
    past = _iss(start_date="2026-01-01", due_date="2026-01-10")
    assert tl._issue_row(past, False, None, TODAY, WS, WE) == ("outside", None)
    assert tl._issue_row(_iss(), False, None, TODAY, WS, WE) == (
        "unscheduled",
        None,
    )


def test_issue_row_unassigned_and_missing_status():
    issue = _iss(assigned_to=None, status=None, due_date="2026-09-30")
    _, row = tl._issue_row(issue, False, None, TODAY, WS, WE)
    assert row["assigned_to"] is None and row["status"] is None


def _row(id, start, end="2026-10-01", state="planned"):
    return {"type": "issue", "id": id, "start": start, "end": end, "state": state}


def _ver(id, name, due, status="open", description=""):
    return {
        "id": id,
        "name": name,
        "due_date": due,
        "status": status,
        "description": description,
    }


def _ref(id, name):
    return {"id": id, "name": name}


def test_group_rows_orders_versions_then_no_version_then_done():
    versions = [
        _ver(2, "v3.0", "2026-11-20"),
        _ver(
            1,
            "v2.5",
            "2026-10-10",
            description="<insecure-content-ab>\nApps\n</insecure-content-ab>",
        ),
        _ver(3, "v9", None),
        _ver(0, "v2.4", "2026-09-05", status="closed"),
    ]
    entries = [
        (_row(10, "2026-10-01"), _ref(2, "v3.0"), False),
        (_row(11, "2026-09-10"), _ref(1, "v2.5"), False),
        (_row(12, "2026-09-12"), _ref(3, "v9"), False),
        (_row(13, "2026-09-15"), None, False),
        (_row(14, "2026-09-01", state="done"), _ref(0, "v2.4"), True),
        (_row(15, "2026-09-02", state="done"), None, True),
    ]
    groups = tl._group_rows(entries, versions, WS, WE)
    assert [g["key"] for g in groups] == [
        "version:1",
        "version:2",
        "version:3",
        "none",
        "done",
    ]
    assert groups[0]["title"] == "v2.5"
    assert groups[0]["description"].startswith("<insecure-content-ab>")
    assert groups[2]["description"] is None
    assert groups[3]["title"] == "No version"
    assert groups[4]["title"] == "Done"
    # Version group: issues, then its milestone last.
    assert [r["type"] for r in groups[0]["rows"]] == ["issue", "milestone"]
    assert groups[0]["rows"][1] == {
        "type": "milestone",
        "version_id": 1,
        "label": "v2.5 release",
        "date": "2026-10-10",
        "closed": False,
        "in_window": True,
    }
    # Undated version: no milestone row.
    assert [r["type"] for r in groups[2]["rows"]] == ["issue"]
    # Done: closed version's rows + milestone, then unversioned closed rows.
    assert [
        (r["type"], r.get("id") or r.get("version_id")) for r in groups[4]["rows"]
    ] == [
        ("issue", 14),
        ("milestone", 0),
        ("issue", 15),
    ]
    assert groups[4]["rows"][1]["closed"] is True


def test_group_rows_sorts_issues_by_start_end_id():
    versions = [_ver(1, "v1", "2026-10-10")]
    entries = [
        (_row(3, "2026-09-10", "2026-09-20"), _ref(1, "v1"), False),
        (_row(2, "2026-09-10", "2026-09-15"), _ref(1, "v1"), False),
        (_row(1, "2026-09-12", "2026-09-13"), _ref(1, "v1"), False),
    ]
    rows = tl._group_rows(entries, versions, WS, WE)[0]["rows"]
    assert [r.get("id") for r in rows[:3]] == [2, 3, 1]


def test_group_rows_hides_versions_without_rows():
    versions = [_ver(1, "shared", "2026-10-01"), _ver(2, "v2", "2026-10-02")]
    entries = [(_row(1, "2026-09-10"), _ref(2, "v2"), False)]
    groups = tl._group_rows(entries, versions, WS, WE)
    assert [g["key"] for g in groups] == ["version:2"]


def test_group_rows_milestone_outside_window_has_no_diamond():
    versions = [_ver(1, "v1", "2027-03-01")]
    entries = [(_row(1, "2026-09-10"), _ref(1, "v1"), False)]
    ms = tl._group_rows(entries, versions, WS, WE)[0]["rows"][-1]
    assert ms["type"] == "milestone" and ms["in_window"] is False


def test_group_rows_closed_issue_in_open_version_stays_there():
    versions = [_ver(1, "v1", "2026-10-10")]
    entries = [(_row(1, "2026-09-10", state="done"), _ref(1, "v1"), True)]
    groups = tl._group_rows(entries, versions, WS, WE)
    assert [g["key"] for g in groups] == ["version:1"]


def test_group_rows_open_issue_in_closed_version_goes_to_done():
    versions = [_ver(1, "v1", "2026-09-05", status="closed")]
    entries = [(_row(1, "2026-09-10", state="in_progress"), _ref(1, "v1"), False)]
    groups = tl._group_rows(entries, versions, WS, WE)
    assert [g["key"] for g in groups] == ["done"]
    assert groups[0]["rows"][0]["state"] == "in_progress"


def test_group_rows_foreign_version_titled_from_issue_ref():
    # e.g. a subproject version, or the versions query failed.
    entries = [(_row(1, "2026-09-10"), _ref(77, "sub-v1"), False)]
    groups = tl._group_rows(entries, [], WS, WE)
    assert groups == [
        {
            "key": "version:77",
            "title": "sub-v1",
            "description": None,
            "rows": [entries[0][0]],
        }
    ]


def test_group_rows_empty():
    assert tl._group_rows([], [_ver(1, "v1", "2026-10-01")], WS, WE) == []
