"""Pharmaceutical water (PW / WFI) checks — the procedure, not the table.

The water edition already speaks the right protocols for a pharmaceutical water
system: Modbus for the still, the EDI and the distribution skid, HART for the
conductivity and TOC transmitters, OPC-UA for the plant SCADA. What it does not
share is the *semantics*. Its checks are municipal — dissolved oxygen, ORP,
turbidity, chlorine, ammonia. A purified-water loop is judged on conductivity,
total organic carbon and loop temperature, and by a procedure that is easy to
run backwards.

Two parts of that procedure are what this module is for, because both are
routinely got wrong and neither needs a limit from us:

**The Stage 1 conductivity test uses a NON-temperature-compensated reading.**
The stage-1 table is indexed by the temperature of the sample as measured, and
the measured temperature is rounded *down* to the tabulated step. Comparing a
transmitter's 25 °C-compensated output against that table is the common mistake,
and at a hot WFI loop temperature it flatters — the limit at 80 °C is several
times the limit at 25 °C. So a reading that is compensated, or that does not say
whether it is, is **not graded**, and the refusal says why.

**Exceeding Stage 1 is not a failure.** It means proceed to Stage 2. A tool that
prints FAIL there is telling an operator something the compendium does not say,
and the consequence — an unnecessary loop rejection — is expensive enough that
people learn to ignore the tool. The verdict is worded as the compendium words
it.

**No compendial limits are shipped.** The stage-1 table, the TOC limit and the
loop temperature band belong to the site's specification at its compendial
revision. This grades what you declare and cites it. It reads no device.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num, s

MAX_ROWS = 200

WITHIN = "within_limit"
EXCEEDS_STAGE1 = "exceeds_stage1_proceed_to_stage2"
EXCEEDED = "exceeded"
NOT_GRADED = "not_graded"

_SEVERITY = {EXCEEDED: 0, EXCEEDS_STAGE1: 1, NOT_GRADED: 2, WITHIN: 3}

_STAGE1_NOTE = (
    "USP <645> Stage 1: exceeding the stage-1 limit is not a failing result — it "
    "means proceed to Stage 2. Reported as such rather than as a failure."
)


class Stage1TableError(ValueError):
    """Raised when the supplied stage-1 conductivity table cannot be used."""


def _stage1_table(raw: Any) -> list[tuple[float, float]] | None:
    """Normalize ``{temperature_step: limit}`` into sorted (step, limit) pairs."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw:
        raise Stage1TableError(
            "stage1_conductivity_us_cm must be a non-empty {temperature_step_c: "
            "max_us_cm} mapping, e.g. {0: 0.6, 5: 0.8, ...}. No table is shipped: "
            "the limits belong to your specification at its compendial revision."
        )
    pairs: list[tuple[float, float]] = []
    for step, limit in raw.items():
        t, lim = num(step), num(limit)
        if t is None or lim is None:
            raise Stage1TableError(
                f"stage-1 table entry {step!r}: {limit!r} is not numeric. Every "
                "temperature step and limit has to be a number."
            )
        pairs.append((t, lim))
    return sorted(pairs)


def _stage1_limit(table: list[tuple[float, float]], temperature_c: float) -> tuple[Any, Any]:
    """The limit for a measured temperature: round DOWN to the tabulated step."""
    applicable = [(t, lim) for t, lim in table if t <= temperature_c]
    if not applicable:
        return None, None
    return applicable[-1]


def _conductivity_row(sample: dict, table: list[tuple[float, float]] | None) -> dict:
    point = s(sample.get("point", ""), 96)
    value = num(sample.get("conductivity_us_cm"))
    temp = num(sample.get("sample_temperature_c"))
    compensated = sample.get("temperature_compensated")
    row = {
        "point": point,
        "parameter": "conductivity",
        "value": value,
        "unit": "µS/cm",
        "sample_temperature_c": temp,
        "temperature_compensated": compensated,
        "limit": None,
        "limit_at_step_c": None,
    }
    if value is None:
        return {**row, "status": NOT_GRADED, "detail": "no numeric conductivity_us_cm supplied"}
    if table is None:
        return {
            **row,
            "status": NOT_GRADED,
            "detail": (
                "no stage-1 table supplied — pass stage1_conductivity_us_cm="
                "{temperature_step_c: max_us_cm} from your specification"
            ),
        }
    if compensated is not True and compensated is not False:
        return {
            **row,
            "status": NOT_GRADED,
            "detail": (
                "temperature_compensated was not declared. The stage-1 table is "
                "indexed by the sample's own temperature, so a compensated reading "
                "compared against it is a different measurement — state which this "
                "is rather than have it assumed"
            ),
        }
    if compensated is True:
        return {
            **row,
            "status": NOT_GRADED,
            "detail": (
                "this reading is temperature-compensated; the stage-1 test is run on "
                "the NON-compensated value. At loop temperature the compensated "
                "comparison reads better than the real one, so it is refused rather "
                "than reported"
            ),
        }
    if temp is None:
        return {
            **row,
            "status": NOT_GRADED,
            "detail": "no sample_temperature_c supplied — the stage-1 limit is chosen by it",
        }
    step, limit = _stage1_limit(table, temp)
    if limit is None:
        return {
            **row,
            "status": NOT_GRADED,
            "detail": (
                f"{temp} °C is below the lowest tabulated step "
                f"({table[0][0]} °C) — no limit applies without extrapolating"
            ),
        }
    row = {**row, "limit": limit, "limit_at_step_c": step}
    if value > limit:
        return {
            **row,
            "status": EXCEEDS_STAGE1,
            "detail": (
                f"{value} µS/cm > {limit} µS/cm (stage-1 limit at {step} °C, from "
                f"{temp} °C rounded down) — proceed to Stage 2"
            ),
        }
    return {
        **row,
        "status": WITHIN,
        "detail": f"{value} µS/cm ≤ {limit} µS/cm (stage-1 limit at {step} °C)",
    }


def _scalar_row(
    sample: dict,
    parameter: str,
    field: str,
    unit: str,
    limit: float | None,
    band: dict | None = None,
) -> dict:
    point = s(sample.get("point", ""), 96)
    value = num(sample.get(field))
    row = {"point": point, "parameter": parameter, "value": value, "unit": unit, "limit": limit}
    if value is None:
        return {**row, "status": NOT_GRADED, "detail": f"no numeric {field} supplied"}
    if band is not None:
        low, high = num(band.get("min")), num(band.get("max"))
        row = {**row, "limit": {"min": low, "max": high}}
        if low is None and high is None:
            return {**row, "status": NOT_GRADED, "detail": "band supplied without min or max"}
        if (low is not None and value < low) or (high is not None and value > high):
            return {
                **row,
                "status": EXCEEDED,
                "detail": f"{value} {unit} outside the declared band {low}–{high} {unit}",
            }
        return {**row, "status": WITHIN, "detail": f"{value} {unit} within {low}–{high} {unit}"}
    if limit is None:
        return {
            **row,
            "status": NOT_GRADED,
            "detail": f"no limit supplied for {parameter} — not graded rather than assumed",
        }
    if value > limit:
        return {**row, "status": EXCEEDED, "detail": f"{value} {unit} > {limit} {unit}"}
    return {**row, "status": WITHIN, "detail": f"{value} {unit} ≤ {limit} {unit}"}


def pharma_water_check(
    samples: list[dict],
    stage1_conductivity_us_cm: dict | None = None,
    toc_limit_ppb: float | None = None,
    temperature_band_c: dict | None = None,
) -> dict:
    """[READ] Grade PW / WFI loop readings against the limits YOU declare.

    ``samples`` are ``{point, conductivity_us_cm?, sample_temperature_c?,
    temperature_compensated?, toc_ppb?, temperature_c?}``.

    ``stage1_conductivity_us_cm`` is ``{temperature_step_c: max_us_cm}`` from your
    specification. The stage-1 procedure is implemented: the measured temperature
    is rounded DOWN to the tabulated step, the comparison uses the
    NON-temperature-compensated reading, and exceeding the limit is reported as
    *proceed to Stage 2* rather than as a failure. A compensated reading — or one
    that does not say — is refused, because at loop temperature that comparison
    reads better than the real one.

    ``toc_limit_ppb`` and ``temperature_band_c`` (``{min, max}``) are likewise
    yours; anything not declared is reported ``not_graded`` and named, never
    assumed and never counted as passing.

    Worst-first, every verdict citing the reading and the limit it was compared
    against. Read-only, no device I/O.
    """
    table = _stage1_table(stage1_conductivity_us_cm)
    rows: list[dict] = []
    for sample in list(samples or ())[:MAX_ROWS]:
        if not isinstance(sample, dict):
            continue
        if "conductivity_us_cm" in sample:
            rows.append(_conductivity_row(sample, table))
        if "toc_ppb" in sample:
            rows.append(_scalar_row(sample, "toc", "toc_ppb", "ppb", num(toc_limit_ppb)))
        if "temperature_c" in sample:
            rows.append(
                _scalar_row(
                    sample,
                    "loop_temperature",
                    "temperature_c",
                    "°C",
                    None,
                    band=temperature_band_c if isinstance(temperature_band_c, dict) else None,
                )
            )
    rows.sort(key=lambda r: (_SEVERITY.get(r["status"], 9), r["point"], r["parameter"]))
    summary = dict.fromkeys(_SEVERITY, 0)
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    return {
        "standard": "PW / WFI — limits supplied by the caller; USP <645> stage-1 procedure applied",
        "readings_evaluated": len(rows),
        "summary": summary,
        "not_graded_count": summary.get(NOT_GRADED, 0),
        "readings": rows,
        "worst": rows[0] if rows else None,
        "stage1_note": _STAGE1_NOTE,
        "advisory": (
            "Advisory analysis of readings you supplied, against limits you "
            "declared. Nothing was read from a device, and an ungraded reading is "
            "listed rather than counted as passing."
        ),
    }


__all__ = [
    "EXCEEDED",
    "EXCEEDS_STAGE1",
    "NOT_GRADED",
    "WITHIN",
    "Stage1TableError",
    "pharma_water_check",
]
