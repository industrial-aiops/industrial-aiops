"""Pharma edition: the cascade, the particle limits, and the stage-1 procedure.

Every test here that matters is about a refusal. Grading a reading against a
limit is arithmetic; the value of these three checks is what they decline to say:

* no door is invented from a room list (adjacency is declared — D25);
* no particle limit is assumed, and an ungraded reading is never counted as
  passing;
* a temperature-compensated conductivity reading is not compared against the
  stage-1 table, and exceeding stage 1 is not called a failure.

Each of those has a comfortable alternative that would make the tool look more
capable, and each of the comfortable alternatives errs toward "in
specification" — the direction this repository keeps having to catch.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain import pharma_cleanroom as cr
from iaiops.core.brain import pharma_water as pw

pytestmark = pytest.mark.unit

ROOMS = [
    {"room": "Fill-A", "grade": "A", "pressure_pa": 60.0},
    {"room": "Fill-B", "grade": "B", "pressure_pa": 45.0},
    {"room": "Gown-C", "grade": "C", "pressure_pa": 30.0},
    {"room": "Corr-D", "grade": "D", "pressure_pa": 15.0},
]
DOORS = [
    {"from": "Fill-A", "to": "Fill-B"},
    {"from": "Fill-B", "to": "Gown-C"},
    {"from": "Gown-C", "to": "Corr-D"},
]


# ─── pressure cascade ────────────────────────────────────────────────────────


def test_a_healthy_cascade_passes_every_door():
    out = cr.cleanroom_pressure_cascade(ROOMS, DOORS)

    assert out["cascade"]["evaluated"] is True
    assert out["failure_count"] == 0
    assert {d["status"] for d in out["cascade"]["doors"]} == {"correct"}
    assert out["cascade"]["doors"][0]["differential_pa"] == 15.0


def test_a_reversed_door_is_the_worst_finding():
    rooms = [*ROOMS[:2], {"room": "Gown-C", "grade": "C", "pressure_pa": 50.0}, ROOMS[3]]
    out = cr.cleanroom_pressure_cascade(rooms, DOORS)

    assert out["worst"]["status"] == "reversed"
    assert out["worst"]["from"] == "Fill-B"
    assert "REVERSED" in out["worst"]["detail"]
    assert out["failure_count"] == 1


def test_a_weak_door_is_insufficient_not_correct():
    rooms = [*ROOMS[:2], {"room": "Gown-C", "grade": "C", "pressure_pa": 40.0}, ROOMS[3]]
    out = cr.cleanroom_pressure_cascade(rooms, DOORS)
    weak = next(d for d in out["cascade"]["doors"] if d["to"] == "Gown-C")

    assert weak["status"] == "insufficient"
    assert weak["differential_pa"] == 5.0
    assert "10.0 Pa" in weak["detail"]


def test_adjacency_is_never_inferred_from_the_room_list():
    """Four rooms in grade order look like an obvious chain. It is not offered."""
    out = cr.cleanroom_pressure_cascade(ROOMS)

    assert out["cascade"]["evaluated"] is False
    assert out["cascade"]["doors"] == []
    assert "declared rather than inferred" in out["cascade"]["why_not"]
    # ...and the readings are still graded, so the refusal costs nothing.
    assert out["rooms_evaluated"] == 4
    assert {r["status"] for r in out["rooms"]} == {"ok"}


def test_a_door_with_a_missing_reading_is_unknown_not_correct():
    rooms = [*ROOMS[:2], {"room": "Gown-C", "grade": "C"}, ROOMS[3]]
    out = cr.cleanroom_pressure_cascade(rooms, DOORS)
    unknown = [d for d in out["cascade"]["doors"] if d["status"] == "unknown"]

    assert len(unknown) == 2
    assert all("not evaluated" in d["detail"] for d in unknown)
    assert out["failure_count"] == 0  # unknown is not a failure, and not a pass either
    assert out["cascade"]["summary"]["correct"] == 1


def test_an_unrecognised_grade_is_not_guessed():
    out = cr.cleanroom_pressure_cascade([{"room": "X", "grade": "Grade B", "pressure_pa": 40.0}])
    assert out["rooms"][0]["status"] == "unknown_grade"
    assert "not graded rather than guessed" in out["rooms"][0]["detail"]


def test_the_min_cascade_is_overridable():
    out = cr.cleanroom_pressure_cascade(ROOMS, DOORS, min_cascade_pa=20.0)
    assert out["min_cascade_pa"] == 20.0
    assert all(d["status"] == "insufficient" for d in out["cascade"]["doors"])


# ─── particle counts ─────────────────────────────────────────────────────────

SAMPLE = {
    "room": "Fill-B",
    "grade": "B",
    "state": "in_operation",
    "particles_per_m3": {"0.5": 290000, "5.0": 2600},
}
LIMITS = {"B": {"in_operation": {"0.5": 352000, "5.0": 2930}}}


def test_counts_inside_the_declared_limits_pass_and_cite_both_numbers():
    out = cr.cleanroom_particle_check([SAMPLE], LIMITS)

    assert out["exceeded_count"] == 0
    assert out["ungraded_count"] == 0
    assert all(r["status"] == "within_limit" for r in out["readings"])
    assert "352000" in out["readings"][0]["detail"] or "352000" in out["readings"][1]["detail"]


def test_an_exceedance_is_worst_first_and_cites_the_limit():
    hot = {**SAMPLE, "particles_per_m3": {"0.5": 400000, "5.0": 100}}
    out = cr.cleanroom_particle_check([hot], LIMITS)

    assert out["worst"]["status"] == "exceeded"
    assert out["worst"]["count_per_m3"] == 400000
    assert out["worst"]["limit_per_m3"] == 352000


def test_a_missing_limit_is_named_and_never_counted_as_passing():
    """The comfortable version would skip it and report a clean run."""
    out = cr.cleanroom_particle_check([SAMPLE], {"B": {"at_rest": {"0.5": 3520}}})

    assert out["exceeded_count"] == 0
    assert out["ungraded_count"] == 2
    assert out["summary"]["within_limit"] == 0
    assert all(r["status"] == "no_limit" for r in out["readings"])
    assert "not graded rather than assumed" in out["readings"][0]["detail"]


def test_no_compendial_table_is_shipped():
    """A limit this repository cannot verify must not decide a batch environment."""
    out = cr.cleanroom_particle_check([SAMPLE], {})
    assert out["ungraded_count"] == 2
    assert out["summary"]["within_limit"] == 0

    source = (cr.__file__,)
    text = open(source[0], encoding="utf-8").read()
    for suspicious in ("3520", "352000", "29300"):
        assert suspicious not in text, (
            f"{suspicious} looks like a transcribed compendial limit. The module "
            "must not carry one — the flattering error (a limit set too loose) "
            "reads as 'in specification'."
        )


def test_a_missing_count_is_reported_not_dropped():
    out = cr.cleanroom_particle_check(
        [{"room": "Fill-B", "grade": "B", "state": "at_rest"}], LIMITS
    )
    assert out["readings"][0]["status"] == "no_reading"
    assert out["ungraded_count"] == 1


# ─── pharmaceutical water ────────────────────────────────────────────────────

STAGE1 = {"45": 1.8, "50": 1.9, "55": 2.1, "60": 2.2}


def _sample(**kw):
    return {
        "point": "WFI-UP-07",
        "conductivity_us_cm": 1.9,
        "sample_temperature_c": 52.0,
        "temperature_compensated": False,
        **kw,
    }


def test_the_stage1_limit_is_the_step_below_the_measured_temperature():
    """52 °C uses the 50 °C row. Rounding up would pick a looser limit."""
    out = pw.pharma_water_check([_sample()], stage1_conductivity_us_cm=STAGE1)
    row = out["readings"][0]

    assert row["limit_at_step_c"] == 50.0
    assert row["limit"] == 1.9
    assert row["status"] == pw.WITHIN


def test_exceeding_stage_1_says_proceed_to_stage_2_not_fail():
    out = pw.pharma_water_check([_sample(conductivity_us_cm=2.0)], stage1_conductivity_us_cm=STAGE1)
    row = out["readings"][0]

    assert row["status"] == pw.EXCEEDS_STAGE1
    assert "Stage 2" in row["detail"]
    assert "fail" not in row["detail"].lower()
    assert "not a failing result" in out["stage1_note"]


def test_a_temperature_compensated_reading_is_refused():
    """At loop temperature the compensated comparison reads better than the real one."""
    out = pw.pharma_water_check(
        [_sample(temperature_compensated=True)], stage1_conductivity_us_cm=STAGE1
    )
    row = out["readings"][0]

    assert row["status"] == pw.NOT_GRADED
    assert "NON-compensated" in row["detail"]


def test_an_undeclared_compensation_state_is_refused():
    sample = _sample()
    del sample["temperature_compensated"]
    out = pw.pharma_water_check([sample], stage1_conductivity_us_cm=STAGE1)

    assert out["readings"][0]["status"] == pw.NOT_GRADED
    assert "not declared" in out["readings"][0]["detail"]


def test_conductivity_is_not_graded_without_a_table():
    out = pw.pharma_water_check([_sample()])
    assert out["readings"][0]["status"] == pw.NOT_GRADED
    assert "stage1_conductivity_us_cm" in out["readings"][0]["detail"]


def test_a_temperature_below_every_step_is_not_extrapolated():
    out = pw.pharma_water_check(
        [_sample(sample_temperature_c=20.0)], stage1_conductivity_us_cm=STAGE1
    )
    assert out["readings"][0]["status"] == pw.NOT_GRADED
    assert "without extrapolating" in out["readings"][0]["detail"]


def test_toc_is_graded_against_the_declared_limit_only():
    graded = pw.pharma_water_check([{"point": "P1", "toc_ppb": 620}], toc_limit_ppb=500)
    assert graded["readings"][0]["status"] == pw.EXCEEDED

    ungraded = pw.pharma_water_check([{"point": "P1", "toc_ppb": 620}])
    assert ungraded["readings"][0]["status"] == pw.NOT_GRADED
    assert ungraded["not_graded_count"] == 1


def test_the_loop_temperature_band_is_declared_not_assumed():
    band = {"min": 65.0, "max": 80.0}
    cold = pw.pharma_water_check([{"point": "P1", "temperature_c": 40.0}], temperature_band_c=band)
    assert cold["readings"][0]["status"] == pw.EXCEEDED

    none = pw.pharma_water_check([{"point": "P1", "temperature_c": 40.0}])
    assert none["readings"][0]["status"] == pw.NOT_GRADED


def test_a_malformed_stage1_table_is_refused_rather_than_ignored():
    with pytest.raises(pw.Stage1TableError, match="non-empty"):
        pw.pharma_water_check([_sample()], stage1_conductivity_us_cm={})
    with pytest.raises(pw.Stage1TableError, match="not numeric"):
        pw.pharma_water_check([_sample()], stage1_conductivity_us_cm={"50": "low"})


def test_findings_are_worst_first():
    out = pw.pharma_water_check(
        [
            _sample(point="ok", conductivity_us_cm=1.0),
            _sample(point="over", conductivity_us_cm=5.0),
            {"point": "toc-only", "toc_ppb": 900},
        ],
        stage1_conductivity_us_cm=STAGE1,
        toc_limit_ppb=500,
    )
    assert [r["status"] for r in out["readings"]] == [
        pw.EXCEEDED,
        pw.EXCEEDS_STAGE1,
        pw.WITHIN,
    ]


# ─── the edition wiring ──────────────────────────────────────────────────────


def test_the_pharma_tools_are_governed_and_read_only():
    import mcp_server.tools.pharma_tools as mod

    for name in ("cleanroom_pressure_cascade", "cleanroom_particle_check", "pharma_water_check"):
        fn = getattr(mod, name)
        assert getattr(fn, "_is_governed_tool", False), f"{name} is ungoverned"
        assert (fn.__doc__ or "").startswith("[READ]"), name


def test_the_pharma_edition_carries_its_tools_and_no_new_protocol():
    """The bet: pharma needed semantics, not a connector."""
    from mcp_server.profiles import EDITION_MODULES, NAMED_PROFILES, PROTOCOL_MODULES

    assert NAMED_PROFILES["pharma"] == ("bacnet", "modbus", "hart", "opcua")
    assert all(p in PROTOCOL_MODULES for p in NAMED_PROFILES["pharma"])
    assert EDITION_MODULES["pharma"] == ("pharma_tools",)


def test_the_pharma_tools_do_not_ride_the_water_or_clinical_editions():
    """Shared protocols, different limits and a different procedure."""
    from mcp_server.profiles import EDITION_MODULES

    for edition in ("water", "clinical", "building", "process"):
        assert "pharma_tools" not in EDITION_MODULES.get(edition, ())
