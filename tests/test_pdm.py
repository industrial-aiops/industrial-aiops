"""Predictive maintenance — trend + time-to-threshold forecast (pure + governed tool)."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain.pdm import pdm_forecast
from iaiops.core.brain.pdm_features import waveform_features
from iaiops.core.brain.pdm_math import (
    mean_crossing_rate,
    percentile,
    r_squared,
    theil_sen,
)
from iaiops.core.brain.pdm_patterns import classify_degradation
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.pdm_tools import pdm_forecast as pdm_forecast_tool


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


def _rising_with_time(n=40, start=50.0, step=0.5, dt_s=60):
    base = datetime(2026, 7, 12, 0, 0, 0, tzinfo=UTC)
    return [
        {"value": start + step * i, "timestamp": (base + timedelta(seconds=dt_s * i)).isoformat()}
        for i in range(n)
    ]


@pytest.mark.unit
def test_insufficient_data():
    out = pdm_forecast([{"value": i} for i in range(10)])
    assert out["status"] == "insufficient_data"
    assert out["samples"] == 10 and out["needed"] == 30


@pytest.mark.unit
def test_stable_flat_series():
    out = pdm_forecast([{"value": 42.0} for _ in range(40)], warn_high=75)
    assert out["status"] == "stable"
    assert out["direction"] == "flat"


@pytest.mark.unit
def test_imminent_with_timestamps():
    # rising 0.5/min toward warn_high=75 from current 69.5 → ETA ~660 s (< 24h default) = imminent
    out = pdm_forecast(_rising_with_time(), warn_high=75, alarm_high=85)
    assert out["status"] == "imminent"
    assert out["direction"] == "rising" and out["unit"] == "s"
    assert out["limit"] == {"name": "warn_high", "value": 75}
    assert 500 < out["eta_to_limit"] < 900


@pytest.mark.unit
def test_degrading_when_eta_beyond_horizon():
    out = pdm_forecast(_rising_with_time(), warn_high=75, imminent_within_s=100)
    assert out["status"] == "degrading"  # ETA ~660 s > 100 s horizon
    assert out["eta_to_limit"] > 100


@pytest.mark.unit
def test_samples_unit_without_timestamps():
    out = pdm_forecast([{"value": 50.0 + 0.5 * i} for i in range(40)], warn_high=75)
    assert out["unit"] == "samples" and out["status"] == "degrading"
    assert out["eta_to_limit"] == pytest.approx(11.0, abs=0.5)  # (75-69.5)/0.5


@pytest.mark.unit
def test_no_limit_in_direction_is_stable():
    # rising, but only a LOW limit configured → nothing ahead → stable (with note)
    out = pdm_forecast(_rising_with_time(), warn_low=10)
    assert out["status"] == "stable" and "note" in out


@pytest.mark.unit
def test_robust_to_a_single_spike():
    series = _rising_with_time()
    series[20]["value"] = 9999.0  # one wild outlier — Theil-Sen should ignore it
    out = pdm_forecast(series, warn_high=75)
    assert out["direction"] == "rising"  # not derailed by the spike


@pytest.mark.unit
def test_tool_governed_registered_and_runs(home):
    assert getattr(pdm_forecast_tool, "_is_governed_tool", False) is True
    assert getattr(pdm_forecast_tool, "_risk_level", "") == "low"
    assert "pdm_tools" in BRAIN_MODULES
    out = pdm_forecast_tool(series=[{"value": 42.0} for _ in range(40)])
    assert "error" not in out and out["status"] == "stable"


# ─── shared math primitives (pdm_math) ──────────────────────────────────────────


def _sine(n: int, amp: float = 5.0, period: int = 64, offset: float = 20.0) -> list[float]:
    return [offset + amp * math.sin(2 * math.pi * i / period) for i in range(n)]


@pytest.mark.unit
def test_theil_sen_recovers_a_clean_slope_and_ignores_a_spike():
    xs = [float(i) for i in range(20)]
    ys = [3.0 + 2.0 * i for i in range(20)]
    assert theil_sen(xs, ys) == pytest.approx(2.0)
    ys[10] = 9999.0  # a wild outlier must not move the robust median slope
    assert theil_sen(xs, ys) == pytest.approx(2.0)


@pytest.mark.unit
def test_r_squared_perfect_line_and_undefined_on_flat():
    xs = [float(i) for i in range(10)]
    ys = [1.0 + 0.5 * i for i in range(10)]
    assert r_squared(xs, ys, 0.5, 1.0) == pytest.approx(1.0)
    assert r_squared(xs, [7.0] * 10, 0.0, 7.0) is None  # no variance ⇒ undefined


@pytest.mark.unit
def test_percentile_and_mean_crossing_rate():
    assert percentile([0.0, 10.0], 50.0) == pytest.approx(5.0)
    assert percentile([1.0], 99.0) == 1.0  # single value
    assert mean_crossing_rate([0, 2, 0, 2, 0, 2]) == pytest.approx(1.0)  # alternates
    assert mean_crossing_rate([1, 2, 3, 4, 5]) == pytest.approx(0.0)  # monotone


# ─── waveform / vibration features (pdm_features) ───────────────────────────────


@pytest.mark.unit
def test_waveform_features_on_a_sine_match_closed_form():
    out = waveform_features(_sine(256, amp=5.0, period=64))
    assert out["status"] == "ok"
    assert out["rms"] == pytest.approx(5.0 / math.sqrt(2), abs=0.02)  # A/√2
    assert out["peak_to_peak"] == pytest.approx(10.0, abs=0.05)
    assert out["crest_factor"] == pytest.approx(math.sqrt(2), abs=0.02)  # peak/rms
    assert out["kurtosis"] == pytest.approx(-1.5, abs=0.05)  # sine excess kurtosis


@pytest.mark.unit
def test_waveform_kurtosis_and_crest_flag_impulsiveness():
    # a mostly-quiet signal with sparse spikes → high (positive) kurtosis + crest
    calm = waveform_features([0.0, 0.5, -0.5, 0.3, -0.3, 0.1, -0.1, 0.2] * 8)
    impulsive = [0.0] * 200
    for i in range(0, 200, 40):
        impulsive[i] = 12.0
    spiky = waveform_features(impulsive)
    assert spiky["kurtosis"] > 3.0 and spiky["kurtosis"] > calm["kurtosis"]
    assert spiky["crest_factor"] > calm["crest_factor"]


@pytest.mark.unit
def test_waveform_flat_and_insufficient_are_honest():
    flat = waveform_features([7.0] * 20)
    assert flat["status"] == "flat"
    assert flat["crest_factor"] is None and flat["kurtosis"] is None  # not fabricated
    thin = waveform_features([1.0, 2.0, 3.0])
    assert thin["status"] == "insufficient_data" and thin["needed"] == 8


# ─── degradation-pattern classification (pdm_patterns) ──────────────────────────


@pytest.mark.unit
def test_pattern_gradual_reports_shape():
    ramp = classify_degradation([50.0 + 0.5 * i for i in range(40)])
    assert ramp["pattern"] == "gradual" and ramp["shape"] == "steady"
    accel = classify_degradation([10.0 * math.exp(0.05 * i) for i in range(40)])
    assert accel["pattern"] == "gradual" and accel["shape"] == "accelerating"
    # a curved (concave) but strictly monotone climb is still "gradual"
    curved = classify_degradation([50.0 + 10.0 * math.log1p(i) for i in range(40)])
    assert curved["pattern"] == "gradual" and curved["shape"] == "decelerating"


@pytest.mark.unit
def test_pattern_sudden_locates_the_step():
    step = [10.0] * 20 + [30.0] * 20
    out = classify_degradation(step)
    assert out["pattern"] == "sudden" and out["step_at_sample"] == 20


@pytest.mark.unit
def test_pattern_cyclic_reports_period():
    out = classify_degradation(_sine(48, amp=5.0, period=8))
    assert out["pattern"] == "cyclic" and out["approx_period_samples"] == 8


@pytest.mark.unit
def test_pattern_flat_and_insufficient():
    assert classify_degradation([42.0] * 40)["pattern"] == "flat"
    assert classify_degradation([1.0, 2.0, 3.0])["pattern"] == "unknown"


# ─── remaining-useful-life depth (pdm_rul) via the forecast ─────────────────────


@pytest.mark.unit
def test_rul_block_present_only_when_degrading():
    degrading = pdm_forecast(_rising_with_time(), warn_high=75)
    assert "rul" in degrading
    rul = degrading["rul"]
    assert rul["recommended_model"] in {"linear", "exponential"}
    assert rul["confidence"] == "high"  # a clean ramp → tight fit
    assert rul["linear"]["r_squared"] > 0.99
    assert rul["eta_band"]["low"] <= degrading["eta_to_limit"] <= rul["eta_band"]["high"]
    # stable series carry the depth blocks but no RUL (nothing is failing)
    stable = pdm_forecast([{"value": 42.0} for _ in range(40)], warn_high=75)
    assert "rul" not in stable and "degradation" in stable


@pytest.mark.unit
def test_rul_prefers_exponential_for_compounding_degradation():
    base = datetime(2026, 7, 12, tzinfo=UTC)
    series = [
        {
            "value": 10.0 * math.exp(0.05 * i),
            "timestamp": (base + timedelta(seconds=60 * i)).isoformat(),
        }
        for i in range(40)
    ]
    rul = pdm_forecast(series, warn_high=90.0)["rul"]
    assert rul["exponential"]["status"] == "ok"
    assert rul["recommended_model"] == "exponential"
    assert rul["exponential"]["r_squared"] >= rul["linear"]["r_squared"]


@pytest.mark.unit
def test_rul_exponential_not_applicable_on_non_positive_values():
    series = [{"value": -5.0 + 0.5 * i} for i in range(40)]  # crosses zero
    rul = pdm_forecast(series, warn_high=30.0)["rul"]
    assert rul["exponential"]["status"] == "not_applicable"


# ─── forecast enrichment wiring + backward compatibility ────────────────────────


@pytest.mark.unit
def test_forecast_attaches_degradation_and_waveform_blocks():
    out = pdm_forecast(_rising_with_time(), warn_high=75)
    assert out["degradation"]["pattern"] == "gradual"
    assert out["waveform"]["status"] in {"ok", "flat"}


@pytest.mark.unit
def test_include_waveform_false_omits_the_block():
    out = pdm_forecast(_rising_with_time(), warn_high=75, include_waveform=False)
    assert "waveform" not in out and "degradation" in out


@pytest.mark.unit
def test_insufficient_data_stays_minimal():
    out = pdm_forecast([{"value": i} for i in range(10)])
    assert out["status"] == "insufficient_data"
    assert "degradation" not in out and "waveform" not in out and "rul" not in out


@pytest.mark.unit
def test_forecast_does_not_mutate_input_series():
    series = _rising_with_time()
    before = [dict(item) for item in series]
    pdm_forecast(series, warn_high=75)
    assert series == before  # pure: the caller's data is untouched
