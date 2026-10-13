"""Load-profile analysis over HH intervals: coverage, base load, out-of-hours, day types."""

from datetime import UTC, date, datetime, timedelta

import pytest

from iaiops.core.brain import uk_clock
from iaiops.core.brain.hh_import import Interval
from iaiops.core.brain.load_profile import (
    analyse_load_profile,
    parse_operating_hours,
    profile_by_meter,
)

_HH = timedelta(minutes=30)


def _day(d: date, kw_of_slot, meter="M1", estimated=None) -> list[Interval]:
    start = uk_clock.local_midnight_utc(d)
    n = uk_clock.periods_in_day(d)
    return [
        Interval(start + i * _HH, kw_of_slot(i) / 2.0, estimated, meter)
        for i in range(n)
        if kw_of_slot(i) is not None
    ]


def _office(i: int) -> float:
    """10 kW at night, 50 kW 08:00–18:00 local (slots 16–35)."""
    return 50.0 if 16 <= i < 36 else 10.0


def _week(start: date, fn=_office, weekend_fn=lambda i: 10.0) -> list[Interval]:
    out: list[Interval] = []
    for k in range(7):
        d = start + timedelta(days=k)
        out += _day(d, fn if d.weekday() < 5 else weekend_fn)
    return out


@pytest.mark.unit
def test_parse_operating_hours():
    hours = parse_operating_hours("mon-fri 08:00-18:00; sat 09:00-13:00")
    assert hours[0] == ((480, 1080),)
    assert hours[5] == ((540, 780),)
    assert hours[6] == ()


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["xyz 08:00-18:00", "mon 18:00-08:00", "mon 8-18", "mon"])
def test_parse_operating_hours_rejects(bad):
    with pytest.raises(ValueError):
        parse_operating_hours(bad)


@pytest.mark.unit
def test_full_week_office():
    out = analyse_load_profile(_week(date(2026, 1, 12)))  # Mon 12 Jan 2026
    assert out["coverage"]["coverage_pct"] == 100.0
    assert out["peak"]["kw"] == 50.0
    assert out["base_load"]["kw"] == 10.0
    assert out["load_factor"] == pytest.approx(
        out["consumption"]["measured_kwh"] / (7 * 24) / 50, abs=1e-4
    )
    # weekday: 20 slots × 25 kWh + 28 × 5 = 640; weekend 48 × 5 = 240
    assert out["day_types"]["working"]["avg_daily_kwh"] == 640.0
    assert out["day_types"]["closed"]["avg_daily_kwh"] == 240.0
    assert out["day_types"]["working"]["full_days"] == 5
    ooh = 5 * 28 * 5 + 2 * 240
    assert out["out_of_hours"]["kwh"] == ooh
    assert out["out_of_hours"]["above_base_load_kwh"] == 0.0
    assert out["heatmap"]["mean_kw"][0][20] == 50.0
    assert out["heatmap"]["mean_kw"][6][20] == 10.0
    assert out["findings"]


@pytest.mark.unit
def test_out_of_hours_above_base_load_is_an_indication():
    evening = lambda i: 50.0 if 16 <= i < 36 else (30.0 if 36 <= i < 44 else 10.0)  # noqa: E731
    out = analyse_load_profile(_week(date(2026, 1, 12), fn=evening))
    assert out["out_of_hours"]["above_base_load_kwh"] == 5 * 8 * (30 - 10) / 2
    assert "not a guaranteed saving" in out["out_of_hours"]["note"]


@pytest.mark.unit
def test_gap_is_missing_not_zero_and_not_scaled_up():
    intervals = _week(date(2026, 1, 12))
    full = analyse_load_profile(intervals)
    holed = [iv for k, iv in enumerate(intervals) if not 100 <= k < 148]  # drop 24h
    out = analyse_load_profile(holed)
    assert out["coverage"]["missing_periods"] == 48
    assert out["consumption"]["measured_kwh"] < full["consumption"]["measured_kwh"]
    # Exactly the sum of what is there. "Less than the full week" alone is not
    # enough: a total scaled up by coverage still lands below it whenever the gap
    # falls in busier-than-average hours, and a mutation that extrapolated survived.
    assert out["consumption"]["measured_kwh"] == pytest.approx(sum(iv.kwh for iv in holed))
    assert out["base_load"]["kw"] == 10.0
    assert out["day_types"]["working"]["full_days"] < 5
    assert any("not scaled up" in w for w in out["warnings"])


@pytest.mark.unit
def test_requested_window_counts_unsampled_head_and_tail():
    intervals = _day(date(2026, 1, 13), _office)
    out = analyse_load_profile(
        intervals, since="2026-01-12T00:00:00+00:00", until="2026-01-15T00:00:00+00:00"
    )
    assert out["window"]["basis"] == "requested"
    assert out["coverage"]["expected_periods"] == 144
    assert out["coverage"]["coverage_pct"] == pytest.approx(100 / 3, abs=0.01)


@pytest.mark.unit
def test_window_excludes_intervals_outside_it():
    intervals = _week(date(2026, 1, 12))
    out = analyse_load_profile(intervals, since="2026-01-12", until="2026-01-13")
    assert out["coverage"]["measured_periods"] == 48


@pytest.mark.unit
def test_holiday_counts_as_closed():
    intervals = _week(date(2026, 1, 12))
    out = analyse_load_profile(intervals, holidays=["2026-01-12"])
    assert out["day_types"]["working"]["full_days"] == 4
    assert out["day_types"]["closed"]["full_days"] == 3


@pytest.mark.unit
def test_estimated_share_and_unknown():
    unknown = analyse_load_profile(_day(date(2026, 1, 12), _office))
    assert unknown["consumption"]["estimated_share_pct"] is None
    assert unknown["consumption"]["read_type"] == "unknown"
    flagged = analyse_load_profile(
        _day(date(2026, 1, 12), _office, estimated=False)
        + _day(date(2026, 1, 13), _office, estimated=True)
    )
    assert flagged["consumption"]["estimated_share_pct"] == 50.0


@pytest.mark.unit
def test_clock_change_day_is_complete_with_46_periods():
    out = analyse_load_profile(_day(date(2026, 3, 29), lambda i: 10.0))
    (day,) = out["daily"]
    assert day["periods_in_day"] == 46 and day["complete"]


@pytest.mark.unit
def test_single_meter_required_and_profile_by_meter():
    both = _day(date(2026, 1, 12), _office) + _day(date(2026, 1, 12), _office, meter="M2")
    with pytest.raises(ValueError, match="meter"):
        analyse_load_profile(both)
    out = profile_by_meter(both)
    assert set(out["profiles"]) == {"M1", "M2"}
    only = profile_by_meter(both, meter="M2")
    assert set(only["profiles"]) == {"M2"}
    with pytest.raises(ValueError):
        profile_by_meter(both, meter="nope")


@pytest.mark.unit
def test_empty_refuses():
    with pytest.raises(ValueError):
        analyse_load_profile([])


@pytest.mark.unit
def test_peak_local_time_reported():
    out = analyse_load_profile(_day(date(2026, 7, 1), _office))
    assert out["peak"]["at_local"].startswith("2026-07-01 08:00")
    assert out["window"]["start_utc"] == datetime(2026, 6, 30, 23, tzinfo=UTC).isoformat()


@pytest.mark.unit
def test_day_types_follow_declared_hours_not_the_calendar():
    """A seven-day site has no closed days; a Mon–Sat site's Saturday is working."""
    week = _week(date(2026, 1, 12))
    always = analyse_load_profile(week, operating_hours="mon-sun 08:00-18:00")
    assert always["day_types"]["closed"]["full_days"] == 0
    assert always["day_types"]["working"]["full_days"] == 7
    six = analyse_load_profile(week, operating_hours="mon-sat 08:00-18:00")
    assert six["day_types"]["working"]["full_days"] == 6
    assert not any("closed day (weekend" in f for f in always["findings"])


@pytest.mark.unit
def test_partly_flagged_reports_the_unflagged_share():
    mixed = _day(date(2026, 1, 12), _office, estimated=True) + _day(date(2026, 1, 13), _office)
    out = analyse_load_profile(mixed)
    assert out["consumption"]["read_type"] == "partly_flagged"
    assert out["consumption"]["unflagged_share_pct"] == 50.0
    assert any("no actual/estimated flag" in w for w in out["warnings"])


@pytest.mark.unit
def test_night_window_may_cross_midnight():
    out = analyse_load_profile(_week(date(2026, 1, 12)), night=("22:00", "05:00"))
    assert out["base_load"]["samples"] == 7 * 14
    assert out["base_load"]["kw"] == 10.0


@pytest.mark.unit
def test_holiday_accepts_uk_dates_and_explains_bad_ones():
    out = analyse_load_profile(_week(date(2026, 1, 12)), holidays=["12/01/2026"])
    assert out["operating_hours"]["holidays"] == ["2026-01-12"]
    with pytest.raises(ValueError, match="holiday"):
        analyse_load_profile(_week(date(2026, 1, 12)), holidays=["01/13/2026"])
