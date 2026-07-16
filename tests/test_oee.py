"""OEE / downtime / multidim analytics tests over synthetic inputs (no plant)."""

from __future__ import annotations

import pytest

from iaiops.core.brain import energy, oee
from mcp_server.tools import oee_tools


@pytest.mark.unit
def test_oee_compute_classic():
    out = oee.oee_compute(
        planned_time_s=28800,
        run_time_s=25200,
        ideal_cycle_time_s=2.0,
        total_count=12000,
        good_count=11800,
    )
    # Availability 25200/28800 = 0.875
    assert out["availability"]["value"] == pytest.approx(0.875, abs=1e-3)
    # Performance (2*12000)/25200 = 0.95238
    assert out["performance"]["value"] == pytest.approx(0.95238, abs=1e-3)
    # Quality 11800/12000 = 0.98333
    assert out["quality"]["value"] == pytest.approx(0.98333, abs=1e-3)
    assert 0.0 < out["oee"] < 1.0
    assert out["oee_pct"] == pytest.approx(out["oee"] * 100, abs=0.05)


@pytest.mark.unit
def test_oee_performance_capped_when_optimistic_cycle():
    out = oee.oee_compute(100, 100, 2.0, 100, 100)  # ideal*total = 200 > run 100
    assert out["performance"]["capped"] is True
    assert out["performance"]["value"] == 1.0
    assert out["performance"]["raw"] > 1.0


@pytest.mark.unit
def test_downtime_events_detects_and_categorizes():
    series = [
        {"timestamp": "2026-06-28T08:00:00Z", "state": "RUNNING"},
        {"timestamp": "2026-06-28T08:05:00Z", "state": "FAULT"},
        {"timestamp": "2026-06-28T08:10:00Z", "state": "RUNNING"},
        {"timestamp": "2026-06-28T08:20:00Z", "state": "changeover"},
        {"timestamp": "2026-06-28T08:35:00Z", "state": "RUNNING"},
    ]
    out = oee.downtime_events(series)
    assert out["event_count"] == 2
    cats = {e["category"] for e in out["events"]}
    assert "mechanical" in cats  # FAULT
    assert "changeover" in cats
    # FAULT span = 5 min = 300s; changeover span = 15 min = 900s
    assert out["total_downtime_s"] == pytest.approx(1200.0, abs=1e-3)
    assert out["by_category"]["mechanical"]["downtime_s"] == pytest.approx(300.0, abs=1e-3)


@pytest.mark.unit
def test_downtime_min_duration_filters():
    series = [
        {"timestamp": "2026-06-28T08:00:00Z", "state": "RUNNING"},
        {"timestamp": "2026-06-28T08:00:10Z", "state": "IDLE"},
        {"timestamp": "2026-06-28T08:00:20Z", "state": "RUNNING"},
    ]
    out = oee.downtime_events(series, min_duration_s=30)
    assert out["event_count"] == 0


@pytest.mark.unit
def test_oee_multidim_aggregates_and_ranks():
    records = [
        {
            "machine": "M1",
            "part": "A",
            "shift": "day",
            "planned_time_s": 3600,
            "run_time_s": 3600,
            "ideal_cycle_time_s": 1.0,
            "total_count": 3600,
            "good_count": 3600,
        },
        {
            "machine": "M2",
            "part": "A",
            "shift": "day",
            "planned_time_s": 3600,
            "run_time_s": 1800,
            "ideal_cycle_time_s": 1.0,
            "total_count": 1800,
            "good_count": 1000,
        },
    ]
    out = oee.oee_multidim(records, dimensions=["machine", "part"])
    assert out["group_count"] == 2
    # M1 is near-perfect, M2 is worse → M2 first in worst_performers.
    assert out["worst_performers"][0]["dimensions"]["machine"] == "M2"
    assert out["worst_performers"][-1]["oee"] >= out["worst_performers"][0]["oee"]
    # No energy inputs → the energy rollup stays absent (backward compatible).
    assert "energy_baseline" not in out
    assert "energy" not in out["matrix"][0]


# ── Six Big Losses decomposition ───────────────────────────────────────────


@pytest.mark.unit
def test_six_big_losses_identity_matches_classic_oee():
    out = oee.six_big_losses(28800, 25200, 2.0, 12000, 11800)
    assert out["identity_ok"] is True
    # Fully-productive / planned equals the classic multiplicative OEE (no capping).
    classic = oee.oee_compute(28800, 25200, 2.0, 12000, 11800)["oee"]
    assert out["oee_from_losses"] == pytest.approx(classic, abs=1e-6)
    # The six loss shares plus OEE account for 100% of planned time.
    total = sum(loss["pct_of_planned"] for loss in out["losses"]) + out["oee_from_losses"]
    assert total == pytest.approx(1.0, abs=1e-6)
    # Bucket losses: availability 3600s, performance 1200s, quality 400s.
    assert out["by_bucket"]["availability"]["loss_s"] == pytest.approx(3600, abs=1e-3)
    assert out["by_bucket"]["performance"]["loss_s"] == pytest.approx(1200, abs=1e-3)
    assert out["by_bucket"]["quality"]["loss_s"] == pytest.approx(400, abs=1e-3)
    # With no split given, breakdown is the residual (unplanned) availability bucket.
    bd = next(loss for loss in out["losses"] if loss["loss"] == "breakdown")
    assert bd["time_s"] == pytest.approx(3600, abs=1e-3)
    assert bd["classified"] is False


@pytest.mark.unit
def test_six_big_losses_splits_attribute_all_six():
    out = oee.six_big_losses(
        28800,
        25200,
        2.0,
        12000,
        11800,
        setup_time_s=1800,
        minor_stop_time_s=400,
        startup_reject_count=50,
    )
    by = {loss["loss"]: loss for loss in out["losses"]}
    # Availability: setup 1800 (named) + breakdown 1800 (residual = 3600 - 1800).
    assert by["setup"]["time_s"] == pytest.approx(1800, abs=1e-3)
    assert by["setup"]["classified"] is True
    assert by["breakdown"]["time_s"] == pytest.approx(1800, abs=1e-3)
    # Performance: minor stops 400 (named) + speed 800 (residual = 1200 - 400).
    assert by["minor_stops"]["time_s"] == pytest.approx(400, abs=1e-3)
    assert by["speed_loss"]["time_s"] == pytest.approx(800, abs=1e-3)
    # Quality: 50 startup rejects × ideal 2s = 100s; production = 400 - 100 = 300s.
    assert by["startup_rejects"]["time_s"] == pytest.approx(100, abs=1e-3)
    assert by["startup_rejects"]["count"] == pytest.approx(50, abs=1e-3)
    assert by["production_rejects"]["time_s"] == pytest.approx(300, abs=1e-3)
    assert by["production_rejects"]["count"] == pytest.approx(150, abs=1e-3)
    assert out["fully_classified"] is True
    assert out["identity_ok"] is True


@pytest.mark.unit
def test_six_big_losses_flags_optimistic_cycle():
    # ideal*total = 200 > run 100 → performance would exceed 100%.
    out = oee.six_big_losses(100, 100, 2.0, 100, 100)
    assert out["optimistic_cycle"] is True
    assert out["identity_ok"] is True  # the time-ladder still balances


@pytest.mark.unit
def test_six_big_losses_over_attribution_is_clamped_and_warned():
    # setup 5000s exceeds the measured 3600s availability loss → clamp + warn.
    out = oee.six_big_losses(28800, 25200, 2.0, 12000, 11800, setup_time_s=5000)
    by = {loss["loss"]: loss for loss in out["losses"]}
    assert by["setup"]["time_s"] == pytest.approx(3600, abs=1e-3)
    assert by["breakdown"]["time_s"] == pytest.approx(0.0, abs=1e-3)
    assert out["input_warnings"]
    assert out["identity_ok"] is True


# ── Energy / carbon analytics ──────────────────────────────────────────────


@pytest.mark.unit
def test_energy_intensity_kwh_per_unit_and_placeholder_factor():
    out = energy.energy_intensity(actual_kwh=1000, produced_count=500)
    assert out["kwh_per_unit"] == pytest.approx(2.0, abs=1e-6)
    # Default emission factor is the flagged placeholder (0.5): 1000 × 0.5 = 500 kg.
    assert out["carbon"]["factor_source"] == "default_placeholder"
    assert out["carbon"]["co2e_kg"] == pytest.approx(500.0, abs=1e-3)
    assert "待核实" in out["carbon"]["note"]
    # A caller-supplied factor overrides the placeholder.
    out2 = energy.energy_intensity(1000, 500, emission_factor_kg_per_kwh=0.2)
    assert out2["carbon"]["factor_source"] == "caller"
    assert out2["carbon"]["co2e_kg"] == pytest.approx(200.0, abs=1e-3)


@pytest.mark.unit
def test_energy_baseline_deviation_verdicts():
    assert energy.energy_baseline_deviation(1200, 1000)["status"] == "over"
    assert energy.energy_baseline_deviation(800, 1000)["status"] == "under"
    on_target = energy.energy_baseline_deviation(1050, 1000)  # +5% within ±10%
    assert on_target["status"] == "on_target"
    assert on_target["exceeds_tolerance"] is False
    no_base = energy.energy_baseline_deviation(500, 0)
    assert no_base["status"] == "no_baseline"
    assert no_base["deviation_pct"] is None


@pytest.mark.unit
def test_energy_baseline_by_period_flags_anomalies():
    records = [
        {"period": "day", "actual_kwh": 900, "baseline_kwh": 880, "produced_count": 11800},
        {"period": "night", "actual_kwh": 1400, "baseline_kwh": 880, "produced_count": 10500},
        {"period": "swing", "actual_kwh": 905, "baseline_kwh": 880, "produced_count": 11300},
    ]
    out = energy.energy_baseline_by_period(records)
    assert out["period_count"] == 3
    assert out["anomaly_count"] == 1
    night = out["anomalies"][0]
    assert night["period"] == "night"
    assert night["exceeds_tolerance"] is True  # +59% over baseline
    assert night["robust_outlier"] is True  # far from the cross-period median
    assert night["kwh_per_unit"] == pytest.approx(1400 / 10500, abs=1e-4)
    assert out["totals"]["actual_kwh"] == pytest.approx(3205, abs=1e-3)
    # The two well-behaved shifts are not flagged.
    calm = {p["period"] for p in out["periods"] if not p["anomaly"]}
    assert calm == {"day", "swing"}


@pytest.mark.unit
def test_energy_baseline_by_period_sums_duplicate_periods():
    records = [
        {"period": "day", "actual_kwh": 400, "baseline_kwh": 500},
        {"period": "day", "actual_kwh": 450, "baseline_kwh": 500},
    ]
    out = energy.energy_baseline_by_period(records)
    assert out["period_count"] == 1
    day = out["periods"][0]
    assert day["actual_kwh"] == pytest.approx(850, abs=1e-3)  # summed
    assert day["baseline_kwh"] == pytest.approx(1000, abs=1e-3)  # summed
    assert day["status"] == "under"  # 850 vs 1000 = -15%


# ── Tool-layer composition (no new @mcp.tool; existing tools deepened) ──────


@pytest.mark.unit
def test_oee_compute_tool_adds_losses_and_optional_energy():
    base = oee_tools.oee_compute(28800, 25200, 2.0, 12000, 11800)
    assert base["six_big_losses"]["identity_ok"] is True
    assert "energy" not in base  # no energy inputs → no energy block
    full = oee_tools.oee_compute(
        28800,
        25200,
        2.0,
        12000,
        11800,
        setup_time_s=1800,
        actual_kwh=1000,
        baseline_kwh=880,
    )
    assert full["energy"]["kwh_per_unit"] == pytest.approx(1000 / 11800, abs=1e-6)
    assert full["energy"]["baseline"]["status"] == "over"  # +13.6% > 10%
    assert full["energy"]["carbon"]["factor_source"] == "default_placeholder"


@pytest.mark.unit
def test_oee_multidim_tool_energy_baseline_by_shift():
    records = [
        {
            "shift": "day",
            "planned_time_s": 28800,
            "run_time_s": 25000,
            "ideal_cycle_time_s": 2,
            "total_count": 12000,
            "good_count": 11800,
            "actual_kwh": 900,
            "baseline_kwh": 880,
        },
        {
            "shift": "night",
            "planned_time_s": 28800,
            "run_time_s": 24000,
            "ideal_cycle_time_s": 2,
            "total_count": 11000,
            "good_count": 10500,
            "actual_kwh": 1400,
            "baseline_kwh": 880,
        },
        {
            "shift": "swing",
            "planned_time_s": 28800,
            "run_time_s": 24500,
            "ideal_cycle_time_s": 2,
            "total_count": 11500,
            "good_count": 11300,
            "actual_kwh": 905,
            "baseline_kwh": 880,
        },
    ]
    out = oee_tools.oee_multidim(records, dimensions=["shift"])
    assert out["energy_baseline"]["anomaly_count"] == 1
    assert out["energy_baseline"]["anomalies"][0]["period"] == "night"
    assert "energy" in out["matrix"][0]
