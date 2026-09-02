"""A non-finite reading must never come out the far side as a passing verdict.

`core/report/fmt.finite` was written in 0.23.0 after an audit found NaN walking
past every guard in the *rendering* layer. The same gap was still open one layer
down, in the coercion the analyses share: `_shared.num()` accepted NaN and ±inf
because they are instances of `float`, and every comparison against them is
False. Reproduced on 2026-09-02, before this file existed:

  * `tag_health` and `spc_check` **crashed** — `statistics.pstdev` refuses
    non-finite data, and `downtime_rca` calls `tag_health`, so one NaN sample
    from a device took the RCA copilot down with it;
  * `learn_baseline` returned `status: "ok"` with `band {p1: NaN, p99: NaN}` —
    a band every later reading compares "inside", which silently switches off
    alerting for that tag forever;
  * `water_quality_compliance`, `isolation_room_check`, `medical_gas_check` and
    `or_environment_check` all reported **compliant / normal** — two of them
    patient-safety checks, one a drinking-water one.

Every one of those is "we could not read this" rendered as "this is fine", which
is the direction this codebase exists to refuse. So the rule is asserted for the
whole grading surface at once, and the test is written to fail loudly rather than
to be updated when a new analysis is added.
"""

from __future__ import annotations

import json
import math

import pytest

pytestmark = pytest.mark.unit

NON_FINITE = (float("nan"), float("inf"), float("-inf"))


def _text(value) -> str:
    return json.dumps(value, default=str).lower()


# ─── the shared coercion ─────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", NON_FINITE)
def test_num_rejects_non_finite(bad):
    """The single fix that closes most of the surface below."""
    from iaiops.core.brain._shared import num

    assert num(bad) is None


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "Infinity", "NaN"])
def test_num_rejects_non_finite_spelled_as_text(bad):
    """A device that returns the STRING "NaN" means the same thing."""
    from iaiops.core.brain._shared import num

    assert num(bad) is None


def test_num_still_accepts_ordinary_readings():
    """The complement: a guard that rejected everything would pass the tests above."""
    from iaiops.core.brain._shared import num

    assert num(0) == 0.0
    assert num(-12.5) == -12.5
    assert num("3.25") == 3.25
    assert num(True) == 1.0 and num(False) == 0.0
    assert num(None) is None and num("open") is None


# ─── nothing crashes ─────────────────────────────────────────────────────────


def _cases(bad):
    from iaiops.core.brain.baseline import learn_baseline
    from iaiops.core.brain.clinical_facility import (
        isolation_room_check,
        medical_gas_check,
        or_environment_check,
    )
    from iaiops.core.brain.diagnostics import tag_health
    from iaiops.core.brain.pdm import pdm_forecast
    from iaiops.core.brain.spc import spc_check
    from iaiops.core.brain.water_quality import water_quality_compliance

    stamps = [f"2026-01-0{1 + i // 40}T{(i // 60) % 24:02d}:{i % 60:02d}:00Z" for i in range(200)]
    return {
        "tag_health/all-bad": lambda: tag_health(
            [{"ref": "t", "samples": [{"value": bad}] * 6, "alarm_high": 10.0}]
        ),
        "tag_health/one-bad": lambda: tag_health(
            [{"ref": "t", "samples": [1.0, 2.0, bad, 3.0, 4.0, 5.0], "alarm_high": 10.0}]
        ),
        "spc_check": lambda: spc_check([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, bad], usl=10, lsl=0),
        "learn_baseline": lambda: learn_baseline(
            [{"ts": t, "tag": "t", "value": bad, "quality": "good"} for t in stamps],
            tag="t",
            min_span_s=1,
        ),
        "water_quality": lambda: water_quality_compliance([{"point": "p", "turbidity_ntu": bad}]),
        "isolation_room": lambda: isolation_room_check(
            [{"room": "r", "mode": "negative", "differential_pa": bad}]
        ),
        "medical_gas": lambda: medical_gas_check(
            [{"system": "s", "gas": "oxygen", "pressure_kpa": bad}]
        ),
        "or_environment": lambda: or_environment_check(
            [{"room": "OR", "temp_c": bad, "humidity_pct": bad, "air_changes_per_hour": bad}]
        ),
        "pdm_forecast": lambda: pdm_forecast(
            [{"ts": t, "value": bad} for t in stamps[:30]], alarm_high=10.0
        ),
    }


@pytest.mark.parametrize("bad", NON_FINITE)
def test_no_analysis_crashes_on_a_non_finite_reading(bad):
    """`statistics.pstdev` raises on non-finite data, and RCA calls tag_health."""
    for label, fn in _cases(bad).items():
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — the point is that none escape
            pytest.fail(f"{label} raised {type(exc).__name__}: {exc}")


@pytest.mark.parametrize("bad", NON_FINITE)
def test_no_analysis_leaks_a_non_finite_number_into_its_output(bad):
    """A NaN in a band or a factor is a number nobody can act on."""
    for label, fn in _cases(bad).items():
        out = _text(fn())
        assert "nan" not in out, f"{label} leaked NaN: {out[:160]}"
        assert "infinity" not in out, f"{label} leaked inf: {out[:160]}"


# ─── and nothing PASSES ──────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", NON_FINITE)
def test_a_non_finite_reading_is_never_graded_compliant(bad):
    """The flattering half. Each of these reported compliant / normal before."""
    from iaiops.core.brain.clinical_facility import (
        isolation_room_check,
        medical_gas_check,
        or_environment_check,
    )
    from iaiops.core.brain.water_quality import water_quality_compliance

    iso = isolation_room_check([{"room": "r", "mode": "negative", "differential_pa": bad}])
    assert iso["summary"]["compliant"] == 0, f"NaN differential graded compliant: {iso['summary']}"

    gas = medical_gas_check([{"system": "s", "gas": "oxygen", "pressure_kpa": bad}])
    assert gas["summary"].get("normal", 0) == 0, f"NaN pressure graded normal: {gas['summary']}"

    orr = or_environment_check(
        [{"room": "OR", "temp_c": bad, "humidity_pct": bad, "air_changes_per_hour": bad}]
    )
    assert orr["summary"].get("compliant", 0) == 0, f"NaN OR graded compliant: {orr['summary']}"

    water = water_quality_compliance([{"point": "p", "turbidity_ntu": bad}])
    assert water["summary"].get("compliant", 0) == 0, f"NaN turbidity compliant: {water['summary']}"


@pytest.mark.parametrize("bad", NON_FINITE)
def test_a_baseline_is_never_learned_from_non_finite_history(bad):
    """A band of NaN is worse than no band: every later check compares inside it."""
    from iaiops.core.brain.baseline import learn_baseline

    stamps = [f"2026-01-0{1 + i // 40}T{(i // 60) % 24:02d}:{i % 60:02d}:00Z" for i in range(200)]
    out = learn_baseline(
        [{"ts": t, "tag": "t", "value": bad, "quality": "good"} for t in stamps],
        tag="t",
        min_span_s=1,
    )
    assert out["status"] != "ok", f"learned a band from non-finite history: {out}"


@pytest.mark.parametrize("bad", NON_FINITE)
def test_a_non_finite_sample_does_not_become_a_control_chart(bad):
    from iaiops.core.brain.spc import spc_check

    out = spc_check([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, bad], usl=10, lsl=0)
    assert out.get("samples", 0) == 7, f"non-finite sample counted: {out}"
    for key in ("center", "sigma"):
        value = out.get(key)
        if isinstance(value, (int, float)):
            assert math.isfinite(value), f"{key} is not finite: {value}"
