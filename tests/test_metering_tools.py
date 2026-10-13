"""MCP metering tools: governed, edition-scoped, same engine as the CLI."""

import pytest

from mcp_server.profiles import BRAIN_MODULES, selected_tool_modules
from mcp_server.tools.metering_tools import meter_hh_check, meter_load_profile

pytestmark = pytest.mark.unit

_CSV = (
    "Date,"
    + ",".join(f"HH{i:02d}" for i in range(1, 49))
    + "\n"
    + "\n".join(
        f"{12 + d:02d}/01/2026," + ",".join("20" if 16 <= i < 36 else "4" for i in range(48))
        for d in range(7)
    )
)
_TARIFF = {
    "unit_rates": [{"name": "flat", "rate": 30, "days": "all", "start": "00:00", "end": "24:00"}]
}


def test_tools_are_governed():
    assert getattr(meter_hh_check, "_is_governed_tool", False)
    assert getattr(meter_load_profile, "_is_governed_tool", False)


def test_edition_wiring():
    assert "metering_tools" not in BRAIN_MODULES
    assert "metering_tools" in selected_tool_modules("building")
    assert "metering_tools" in selected_tool_modules("renewables")
    assert "metering_tools" not in selected_tool_modules("fab")


def test_check():
    out = meter_hh_check(csv_text=_CSV)
    assert out["layout"] == "wide"
    assert out["counts"]["intervals"] == 336


def test_profile_with_tariff_and_without_series():
    out = meter_load_profile(csv_text=_CSV, tariff=_TARIFF)
    (entry,) = out["profiles"].values()
    assert entry["cost"]["avg_p_per_kwh"] == 30.0
    assert "heatmap" not in entry["profile"]
    full = meter_load_profile(csv_text=_CSV, include_series=True)
    assert "heatmap" in next(iter(full["profiles"].values()))["profile"]


def test_holidays_and_hours_passed_through():
    out = meter_load_profile(csv_text=_CSV, operating_hours="mon-sun 00:00-24:00", holidays=[])
    (entry,) = out["profiles"].values()
    assert entry["profile"]["out_of_hours"]["kwh"] == 0.0


def test_bad_input_returns_error_dict():
    assert "error" in meter_hh_check(csv_text="foo,bar\n1,2\n")
    assert "error" in meter_load_profile(csv_text=_CSV, tariff={"unit_rates": []})


def test_size_cap():
    assert "error" in meter_hh_check(csv_text="x" * (6 * 1024 * 1024))
