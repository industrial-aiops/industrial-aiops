"""Tariff overlay: band validation, cost per band, standing charge, shift upper bound."""

from datetime import date, timedelta

import pytest

from iaiops.core.brain import uk_clock
from iaiops.core.brain.hh_import import Interval
from iaiops.core.brain.tariff import cost_intervals, load_tariff

_HH = timedelta(minutes=30)

THREE_RATE = {
    "name": "Example three-rate",
    "unit_rates": [
        {"name": "red", "rate": 40.0, "days": "weekdays", "start": "16:00", "end": "19:00"},
        {"name": "day", "rate": 25.0, "days": "all", "start": "07:00", "end": "23:00"},
        {"name": "night", "rate": 15.0, "days": "all", "start": "23:00", "end": "07:00"},
    ],
    "standing_charge_p_per_day": 100.0,
}


def _flat_day(d: date, kwh: float = 1.0) -> list[Interval]:
    start = uk_clock.local_midnight_utc(d)
    return [Interval(start + i * _HH, kwh, None, "M1") for i in range(uk_clock.periods_in_day(d))]


@pytest.mark.unit
def test_load_and_cost_weekday():
    out = cost_intervals(_flat_day(date(2026, 1, 12)), load_tariff(THREE_RATE))
    bands = {b["name"]: b for b in out["bands"]}
    assert bands["red"]["kwh"] == 6.0
    assert bands["day"]["kwh"] == 26.0  # 07:00–23:00 minus the 3 red hours
    assert bands["night"]["kwh"] == 16.0
    energy = (6 * 40 + 26 * 25 + 16 * 15) / 100
    assert out["energy_cost_gbp"] == pytest.approx(energy)
    assert out["standing"]["days"] == 1
    assert out["total_gbp"] == pytest.approx(energy + 1.0)
    assert out["shift_upper_bound"]["band"] == "red"
    assert out["shift_upper_bound"]["saving_gbp"] == pytest.approx(6 * (40 - 15) / 100)
    assert "upper bound" in out["shift_upper_bound"]["note"]


@pytest.mark.unit
def test_weekend_has_no_red_band():
    out = cost_intervals(_flat_day(date(2026, 1, 17)), load_tariff(THREE_RATE))
    bands = {b["name"]: b for b in out["bands"]}
    assert bands["red"]["kwh"] == 0.0
    assert bands["day"]["kwh"] == 32.0


@pytest.mark.unit
def test_holiday_priced_as_weekend():
    out = cost_intervals(
        _flat_day(date(2026, 1, 12)), load_tariff(THREE_RATE), holidays=["2026-01-12"]
    )
    assert {b["name"]: b["kwh"] for b in out["bands"]}["red"] == 0.0


@pytest.mark.unit
def test_uncovered_slot_is_named():
    spec = {
        "unit_rates": [{"name": "day", "rate": 20, "days": "all", "start": "07:00", "end": "23:00"}]
    }
    with pytest.raises(ValueError, match="23:00"):
        load_tariff(spec)


@pytest.mark.unit
def test_single_rate_has_no_shift_bound():
    spec = {
        "unit_rates": [
            {"name": "flat", "rate": 30, "days": "all", "start": "00:00", "end": "24:00"}
        ]
    }
    out = cost_intervals(_flat_day(date(2026, 1, 12)), load_tariff(spec))
    assert out["shift_upper_bound"] is None
    assert out["avg_p_per_kwh"] == 30.0


@pytest.mark.unit
@pytest.mark.parametrize(
    "band",
    [
        {"name": "x", "rate": -1, "days": "all", "start": "00:00", "end": "24:00"},
        {"name": "x", "rate": 10, "days": "all", "start": "00:10", "end": "24:00"},
        {"name": "x", "rate": 10, "days": "all", "start": "08:00", "end": "08:00"},
        {"name": "x", "rate": 10, "days": "funday", "start": "00:00", "end": "24:00"},
        {"name": "x", "rate": "abc", "days": "all", "start": "00:00", "end": "24:00"},
    ],
)
def test_bad_bands_rejected(band):
    with pytest.raises(ValueError):
        load_tariff({"unit_rates": [band]})


@pytest.mark.unit
def test_days_as_list_and_range():
    spec = {
        "unit_rates": [
            {"name": "wk", "rate": 20, "days": ["mon", "tue", "wed", "thu", "fri"],
             "start": "00:00", "end": "24:00"},
            {"name": "we", "rate": 10, "days": "sat-sun", "start": "00:00", "end": "24:00"},
        ]
    }  # fmt: skip
    tariff = load_tariff(spec)
    out = cost_intervals(_flat_day(date(2026, 1, 17)), tariff)
    assert {b["name"]: b["kwh"] for b in out["bands"]}["we"] == 48.0


@pytest.mark.unit
def test_cost_says_measured_only_and_excludes():
    out = cost_intervals(_flat_day(date(2026, 1, 12)), load_tariff(THREE_RATE))
    assert "measured" in out["coverage_note"]
    assert any("VAT" in e for e in out["excluded"])


@pytest.mark.unit
def test_empty_tariff_rejected():
    with pytest.raises(ValueError):
        load_tariff({})


@pytest.mark.unit
def test_duplicate_band_names_refused():
    spec = {
        "unit_rates": [
            {"name": "day", "rate": 10, "days": "weekdays", "start": "00:00", "end": "24:00"},
            {"name": "day", "rate": 30, "days": "weekends", "start": "00:00", "end": "24:00"},
        ]
    }
    with pytest.raises(ValueError, match="day"):
        load_tariff(spec)
