"""The metering demo still contains what its README says it contains."""

import importlib.util
from pathlib import Path

import pytest
import yaml

from iaiops.core.brain.meter_analysis import analyse_hh

pytestmark = pytest.mark.unit
_DEMO = Path(__file__).resolve().parent.parent / "demo" / "metering"


def _generator():
    spec = importlib.util.spec_from_file_location("gen", _DEMO / "generate_sample.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_csv_matches_the_generator():
    committed = (_DEMO / "college_hh_sample.csv").read_text("utf-8")
    assert committed == "\n".join(_generator().rows()) + "\n"


def test_demo_has_the_planted_features():
    text = (_DEMO / "college_hh_sample.csv").read_text("utf-8")
    tariff = yaml.safe_load((_DEMO / "tariff_example.yaml").read_text("utf-8"))
    out = analyse_hh(text, tariff=tariff)
    (entry,) = out["profiles"].values()
    profile = entry["profile"]
    assert profile["coverage"]["missing_periods"] == 12
    days = {d["date"]: d for d in profile["daily"]}
    assert days["2026-10-25"]["periods_in_day"] == 50 and days["2026-10-25"]["complete"]
    assert not days["2026-11-03"]["complete"]
    assert profile["consumption"]["estimated_share_pct"] > 0
    assert profile["out_of_hours"]["above_base_load_kwh"] > 0
    assert entry["cost"]["shift_upper_bound"]["band"] == "red"
