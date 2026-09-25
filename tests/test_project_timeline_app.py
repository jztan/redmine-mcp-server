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


from unittest.mock import AsyncMock, patch  # noqa: E402


def _resp(issues, has_next=False):
    return {"issues": issues, "pagination": {"has_next": has_next}}


def _patch(open_resp, versions, closed_resp, undated_resp=None):
    undated = _resp([]) if undated_resp is None else undated_resp
    issues = AsyncMock(side_effect=[open_resp, undated, closed_resp])
    return (
        patch.object(tl, "list_redmine_issues", issues),
        patch.object(tl, "list_redmine_versions", AsyncMock(return_value=versions)),
        issues,
    )


async def _build(open_resp, versions, closed_resp, undated_resp=None, **kw):
    pi, pv, issues = _patch(open_resp, versions, closed_resp, undated_resp)
    with pi, pv:
        payload = await tl._build_timeline_payload("web", today=TODAY, **kw)
    return payload, issues


@pytest.mark.asyncio
async def test_build_payload_happy_path():
    open_issue = _iss(
        id=1,
        project={"id": 9, "name": "Web"},
        fixed_version={"id": 1, "name": "v1"},
        start_date="2026-09-10",
        due_date="2026-10-05",
    )
    closed_issue = _iss(
        id=2,
        status={"id": 5, "name": "Closed"},
        start_date="2026-09-01",
        closed_on="2026-09-15T10:00:00",
    )
    payload, issues = await _build(
        _resp([open_issue, _iss(id=3)]),
        [_ver(1, "v1", "2026-10-10")],
        _resp([closed_issue]),
    )
    assert payload["project"] == {"id": "web", "name": "Web"}
    assert payload["window"] == {
        "start": "2026-09-01",
        "end": "2026-10-31",
        "today": "2026-09-25",
        "auto": True,
        "label": "Sep - Oct 2026",
    }
    assert [g["key"] for g in payload["groups"]] == ["version:1", "done"]
    assert payload["unscheduled"] == 1
    assert payload["truncated"] is False
    assert payload["partial"] is False
    assert payload["read_only"] in (True, False)
    assert "generated_at" in payload


@pytest.mark.asyncio
async def test_build_payload_query_kwargs_and_order():
    payload, issues = await _build(
        _resp([_iss(start_date="2026-09-10", due_date="2026-09-12")]),
        [],
        _resp([]),
        filters={"tracker_id": 1},
    )
    open_call, undated_call, closed_call = issues.await_args_list
    # Dated and undated open issues are fetched separately: Redmine sorts
    # start_date with no NULLS clause, so on PostgreSQL a single
    # start_date:desc fetch would fill the cap with undated issues first.
    assert open_call.kwargs == {
        "project_id": "web",
        "status_id": "open",
        "fields": tl._FIELDS,
        "limit": 250,
        "sort": "start_date:desc,id:desc",
        "include_pagination_info": True,
        "filters": {"tracker_id": 1, "start_date": "*"},
    }
    assert undated_call.kwargs == {
        "project_id": "web",
        "status_id": "open",
        "fields": tl._FIELDS,
        "limit": 250,
        "sort": "id:desc",
        "include_pagination_info": True,
        "filters": {"tracker_id": 1, "start_date": "!*"},
    }
    assert closed_call.kwargs == {
        "project_id": "web",
        "status_id": "closed",
        "fields": tl._FIELDS,
        "limit": 250,
        "sort": "closed_on:desc,id:desc",
        "include_pagination_info": True,
        # Bound is the snapped window start, not today-90.
        "filters": {"tracker_id": 1, "closed_on": ">=2026-09-01"},
    }


@pytest.mark.asyncio
async def test_filters_none_is_safe():
    payload, issues = await _build(_resp([]), [], _resp([]), filters=None)
    assert "error" not in payload
    assert issues.await_args_list[0].kwargs["filters"] == {"start_date": "*"}


@pytest.mark.asyncio
async def test_caller_filters_not_mutated():
    # list_redmine_issues pops keys out of the dict it is handed; simulate
    # that so a shared (uncopied) dict would leak between calls.
    seen = []

    async def mutating(**kwargs):
        f = kwargs["filters"]
        seen.append(dict(f))
        f.pop("tracker_id", None)
        f["leaked"] = True
        return _resp([])

    caller = {"tracker_id": 1}
    with (
        patch.object(tl, "list_redmine_issues", side_effect=mutating),
        patch.object(tl, "list_redmine_versions", AsyncMock(return_value=[])),
    ):
        await tl._build_timeline_payload("web", filters=caller, today=TODAY)
    assert caller == {"tracker_id": 1}
    assert len(seen) == 3
    assert all(f.get("tracker_id") == 1 and "leaked" not in f for f in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    ["project_id", "status_id", "closed_on", "start_date", "sort", "limit", "offset"],
)
async def test_reserved_filter_keys_rejected_before_any_call(key):
    payload, issues = await _build(_resp([]), [], _resp([]), filters={key: 1})
    assert payload == {
        "error": f"filters must not contain '{key}'; the timeline sets it itself."
    }
    issues.assert_not_awaited()


@pytest.mark.asyncio
async def test_filters_must_be_a_dict():
    payload, issues = await _build(_resp([]), [], _resp([]), filters=["x"])
    assert payload == {"error": "filters must be an object (a JSON dict)."}
    issues.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_project_id_rejected():
    pi, pv, issues = _patch(_resp([]), [], _resp([]))
    with pi, pv:
        payload = await tl._build_timeline_payload("", today=TODAY)
    assert "error" in payload
    issues.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kw, message",
    [
        ({"start_date": "2026/09/01"}, "start_date must be a YYYY-MM-DD date."),
        ({"end_date": "tomorrow"}, "end_date must be a YYYY-MM-DD date."),
        (
            {"start_date": "2026-10-01", "end_date": "2026-09-01"},
            "start_date must not be after end_date.",
        ),
        (
            {"start_date": "2026-01-01", "end_date": "2027-06-01"},
            "The window from start_date to end_date must not exceed 366 days.",
        ),
    ],
)
async def test_invalid_dates_rejected_before_any_call(kw, message):
    payload, issues = await _build(_resp([]), [], _resp([]), **kw)
    assert payload == {"error": message}
    issues.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_query_error_passes_through():
    err = {"error": "Project not found"}
    payload, issues = await _build(err, [], _resp([]))
    assert payload == err
    assert issues.await_count == 1


@pytest.mark.asyncio
async def test_closed_query_error_is_partial():
    open_issue = _iss(start_date="2026-09-10", due_date="2026-09-12")
    payload, _ = await _build(_resp([open_issue]), [], {"error": "boom"})
    assert payload["partial"] is True
    assert [g["key"] for g in payload["groups"]] == ["none"]


@pytest.mark.asyncio
async def test_versions_error_is_partial_and_groups_by_issue_ref():
    open_issue = _iss(
        fixed_version={"id": 4, "name": "v4"},
        start_date="2026-09-10",
        due_date="2026-09-12",
    )
    payload, _ = await _build(_resp([open_issue]), {"error": "403"}, _resp([]))
    assert payload["partial"] is True
    group = payload["groups"][0]
    assert (group["key"], group["title"]) == ("version:4", "v4")
    assert [r["type"] for r in group["rows"]] == ["issue"]


@pytest.mark.asyncio
async def test_truncated_from_either_query():
    p1, _ = await _build(_resp([], has_next=True), [], _resp([]))
    p2, _ = await _build(_resp([]), [], _resp([], has_next=True))
    assert p1["truncated"] is True and p2["truncated"] is True


@pytest.mark.asyncio
async def test_all_undated_truncated_project_shows_empty_state_payload():
    undated = [_iss(id=i) for i in range(250)]
    payload, _ = await _build(
        _resp([]), [], _resp([]), undated_resp=_resp(undated, has_next=True)
    )
    assert payload["groups"] == []
    assert payload["unscheduled"] == 250
    assert payload["truncated"] is True


@pytest.mark.asyncio
async def test_version_due_dates_feed_auto_window_and_row_ends():
    open_issue = _iss(fixed_version={"id": 1, "name": "v1"}, start_date="2026-09-10")
    payload, _ = await _build(
        _resp([open_issue]), [_ver(1, "v1", "2026-11-20")], _resp([])
    )
    assert payload["window"]["end"] == "2026-11-30"
    row = payload["groups"][0]["rows"][0]
    assert (row["end"], row["end_source"]) == ("2026-11-20", "version")


@pytest.mark.asyncio
async def test_project_name_falls_back_to_closed_row_then_identifier():
    closed_issue = _iss(
        project={"id": 9, "name": "Web"}, closed_on="2026-09-15T10:00:00"
    )
    p1, _ = await _build(_resp([]), [], _resp([closed_issue]))
    assert p1["project"]["name"] == "Web"
    p2, _ = await _build(_resp([]), [], _resp([]))
    assert p2["project"]["name"] == "web"


@pytest.mark.asyncio
async def test_read_only_reflected():
    with patch.object(tl, "_is_read_only_mode", return_value=True):
        payload, _ = await _build(_resp([]), [], _resp([]))
    assert payload["read_only"] is True


from importlib.resources import files  # noqa: E402


def _timeline_html():
    return (
        files("redmine_mcp_server.apps._ui")
        .joinpath("project_timeline.html")
        .read_text(encoding="utf-8")
    )


def test_timeline_html_speaks_extapps_protocol():
    html = _timeline_html()
    for token in [
        "ui/initialize",
        "ui/notifications/initialized",
        "ui/notifications/tool-result",
        "ui/notifications/tool-input",
        "ui/notifications/size-changed",
        "get_project_timeline_data",
        "2026-01-26",
        "postMessage",
        "read_only",
        "start_date",
        "end_date",
    ]:
        assert token in html, token


def test_timeline_html_never_uses_innerhtml():
    assert "innerHTML" not in _timeline_html()


def test_timeline_html_reuses_dashboard_design_tokens():
    html = _timeline_html()
    for token in [
        "--accent",
        "--panel-2",
        "--pos",
        "--neg",
        'data-theme="dark"',
        "prefers-color-scheme: dark",
        'class="shell"',
        'class="stamp"',
    ]:
        assert token in html, token


def test_timeline_html_is_self_contained():
    html = _timeline_html()
    for bad in ["<link", 'src="http', 'src="//', 'href="http', "@import", "cdn."]:
        assert bad not in html, bad


def test_timeline_html_unwraps_version_descriptions():
    html = _timeline_html()
    assert "insecure-content-" in html  # the anchored unwrap regex
    assert "\\u2014" in html  # separator written as an escape, not a literal
    assert "\u2014" not in html


from fastmcp import Client  # noqa: E402

from redmine_mcp_server import apps  # noqa: E402,F401
from redmine_mcp_server.server import mcp  # noqa: E402

_EMPTY_CSP = {"connectDomains": [], "resourceDomains": []}
_URI = "ui://redmine/project-timeline.html"


@pytest.mark.asyncio
async def test_timeline_ui_resource_registered():
    res = await mcp.get_resource(_URI)
    assert res.mime_type == "text/html;profile=mcp-app"
    assert (await res.read()).strip()


@pytest.mark.asyncio
async def test_show_project_timeline_meta_points_at_ui():
    tool = await mcp.get_tool("show_project_timeline")
    ui = tool.meta["ui"]
    assert ui["resourceUri"] == _URI
    assert ui["visibility"] == ["model"]
    assert ui["csp"] == _EMPTY_CSP


@pytest.mark.asyncio
async def test_timeline_ui_resource_declares_csp():
    async with Client(mcp) as client:
        entry = next(r for r in await client.list_resources() if str(r.uri) == _URI)
        (content,) = await client.read_resource(_URI)
    assert entry.meta["ui"]["csp"] == _EMPTY_CSP
    assert content.meta["ui"]["csp"] == _EMPTY_CSP
    assert "domain" not in entry.meta["ui"]


@pytest.mark.asyncio
async def test_timeline_backend_tool_is_app_only():
    tool = await mcp.get_tool("get_project_timeline_data")
    ui = tool.meta["ui"]
    assert ui["visibility"] == ["app"]
    assert "resourceUri" not in ui


def test_timeline_tools_have_scopes_and_annotations():
    from redmine_mcp_server._annotations import TOOL_KINDS, ToolKind
    from redmine_mcp_server.oauth_scopes import TOOL_SCOPES

    for name in ("show_project_timeline", "get_project_timeline_data"):
        assert TOOL_SCOPES[name] == frozenset({"view_issues"})
        assert TOOL_KINDS[name] == ToolKind.READ


@pytest.mark.asyncio
async def test_both_tools_delegate_to_builder():
    builder = AsyncMock(return_value={"ok": True})
    with patch.object(tl, "_build_timeline_payload", builder):
        a = await tl.show_project_timeline("web", start_date="2026-07-01")
        b = await tl.get_project_timeline_data("web", filters={"tracker_id": 1})
    assert a == b == {"ok": True}
    assert builder.await_args_list[0].args == ("web", "2026-07-01", None, None)
    assert builder.await_args_list[1].args == ("web", None, None, {"tracker_id": 1})


@pytest.mark.asyncio
async def test_dated_issues_kept_when_undated_overflow():
    dated = _iss(id=1, start_date="2026-09-10", due_date="2026-09-20")
    undated = [_iss(id=i) for i in range(100, 350)]
    payload, _ = await _build(
        _resp([dated]), [], _resp([]), undated_resp=_resp(undated, has_next=True)
    )
    assert [r["id"] for r in payload["groups"][0]["rows"]] == [1]
    assert payload["unscheduled"] == 250
    assert payload["truncated"] is True


@pytest.mark.asyncio
async def test_undated_query_rows_can_still_draw_markers():
    due_only = _iss(id=5, due_date="2026-09-20")
    payload, _ = await _build(_resp([]), [], _resp([]), undated_resp=_resp([due_only]))
    row = payload["groups"][0]["rows"][0]
    assert (row["id"], row["kind"]) == (5, "marker")


@pytest.mark.asyncio
async def test_undated_query_error_is_partial():
    dated = _iss(id=1, start_date="2026-09-10", due_date="2026-09-20")
    payload, _ = await _build(
        _resp([dated]), [], _resp([]), undated_resp={"error": "boom"}
    )
    assert payload["partial"] is True
    assert [g["key"] for g in payload["groups"]] == ["none"]


def test_timeline_details_float_over_chart_without_resizing():
    # Clicking a bar must not grow the iframe: details open in an absolutely
    # positioned popover inside the chart, not an inline strip above it.
    html = _timeline_html()
    assert 'id="detail"' not in html
    assert "tl-detail" not in html
    pop_css = html.split(".tl-pop {", 1)[1].split("}", 1)[0]
    assert "position: absolute" in pop_css
    show = html.split("function showPopover(", 1)[1].split("\n        }\n", 1)[0]
    assert "queueResize" not in show


def test_timeline_bars_are_not_text_selectable():
    html = _timeline_html()
    rule = html.split(".bar,\n      .marker,\n      .diamond {", 1)[1].split("}", 1)[0]
    assert "user-select: none" in rule
