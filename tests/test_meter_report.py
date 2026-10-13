"""The forwardable half-hourly meter report: self-contained, escaped, honest about gaps."""

from datetime import date, timedelta

import pytest

from iaiops.core.brain import uk_clock
from iaiops.core.brain.hh_import import Interval
from iaiops.core.brain.load_profile import analyse_load_profile
from iaiops.core.brain.meter_charts import daily_bars_svg, heatmap_svg
from iaiops.core.brain.meter_report import render_meter_report
from iaiops.core.brain.tariff import cost_intervals, load_tariff

_HH = timedelta(minutes=30)
TARIFF = {
    "name": "Two-rate",
    "unit_rates": [
        {"name": "day", "rate": 28, "days": "all", "start": "07:00", "end": "23:00"},
        {"name": "night", "rate": 16, "days": "all", "start": "23:00", "end": "07:00"},
    ],
    "standing_charge_p_per_day": 90,
}


def _intervals(meter: str = "1200000000001", drop: range = range(0)) -> list[Interval]:
    out = []
    for k in range(7):
        d = date(2026, 1, 12) + timedelta(days=k)
        start = uk_clock.local_midnight_utc(d)
        for i in range(48):
            kw = 50.0 if (d.weekday() < 5 and 16 <= i < 36) else 10.0
            out.append(Interval(start + i * _HH, kw / 2, None, meter))
    return [iv for n, iv in enumerate(out) if n not in drop]


def _render(intervals, tariff=True, site="Anfield College"):
    profile = analyse_load_profile(intervals)
    cost = cost_intervals(intervals, load_tariff(TARIFF)) if tariff else None
    return render_meter_report(
        profile, cost, site=site, source="supplier.csv", generated_at="2026-10-13 10:00"
    )


@pytest.mark.unit
def test_report_is_self_contained():
    page = _render(_intervals())
    assert page.startswith("<!doctype html>")
    for pattern in ("http://", "https://", "//cdn", "@import", "url(http"):
        assert pattern not in page
    for tag in ("<link", "<img", "<iframe", "<object", "<embed", "<source", "<script"):
        assert tag not in page


@pytest.mark.unit
def test_report_escapes_site_and_meter():
    page = _render(_intervals(meter="<b>m</b>"), site="<script>alert(1)</script>")
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "<b>m</b>" not in page


@pytest.mark.unit
def test_report_carries_figures_findings_and_honesty():
    page = _render(_intervals())
    assert "Out-of-hours" in page
    assert "Base load" in page
    assert "What this report cannot tell you" in page
    assert "VAT" in page
    assert "not a guaranteed saving" in page


@pytest.mark.unit
def test_report_without_tariff_says_so():
    page = _render(_intervals(), tariff=False)
    assert "No tariff" in page


@pytest.mark.unit
def test_incomplete_day_marked_and_gaps_reported():
    page = _render(_intervals(drop=range(60, 80)))
    assert "incomplete" in page
    assert "20 half hours missing" in page


@pytest.mark.unit
def test_charts_handle_none_and_nan():
    assert heatmap_svg({"weekdays": ["Mon"] * 7, "slots": 48, "mean_kw": [[None] * 48] * 7}) != ""
    bars = daily_bars_svg([{"date": "2026-01-12", "kwh": float("nan"), "complete": False,
                            "periods_measured": 0, "periods_in_day": 48}])  # fmt: skip
    assert "nan" not in bars.lower()


@pytest.mark.unit
def test_daily_bars_empty():
    assert daily_bars_svg([]) == ""


@pytest.mark.unit
def test_partly_flagged_tile_says_minimum():
    flagged = [
        Interval(iv.start_utc, iv.kwh, n < 48, iv.meter) for n, iv in enumerate(_intervals())
    ]
    mixed = flagged[:96] + [Interval(iv.start_utc, iv.kwh, None, iv.meter) for iv in flagged[96:]]
    page = render_meter_report(analyse_load_profile(mixed), None, generated_at="x")
    assert "at least" in page and "unflagged" in page
