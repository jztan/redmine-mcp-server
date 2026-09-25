from datetime import date


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
