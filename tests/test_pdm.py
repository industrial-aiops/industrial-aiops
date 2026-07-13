"""Predictive maintenance — trend + time-to-threshold forecast (pure + governed tool)."""

from datetime import UTC, datetime, timedelta

import pytest

from iaiops.core.brain.pdm import pdm_forecast
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
