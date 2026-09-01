"""Pharmaceutical-manufacturing MCP tools (READ-ONLY) — cleanroom + PW/WFI.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): these
load only when the ``pharma`` edition is selected, never on a bare protocol
selection and never in the always-on brain. Pure analysis over readings you pass
in (BACnet AI points from the BMS/EMS, Modbus or HART from the water skid and its
transmitters, or a historian).

What is deliberately NOT here: compendial limit tables. The particle limits, the
stage-1 conductivity table and the TOC limit belong to the site's qualified
specification at its compendial revision. A transcription nobody in this
repository can verify would end up deciding whether a batch environment passed,
and the error that hurts is the flattering one — a limit set too loose reads as
"in specification". Every tool takes the limits and cites them back.

Advisory. The site's qualified EMS and its alarm limits remain the source of
truth; nothing here reads or writes a device.
"""

from typing import Any, Optional

from iaiops.core.brain import pharma_cleanroom as cr
from iaiops.core.brain import pharma_water as pw
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def cleanroom_pressure_cascade(
    rooms: list[dict[str, Any]],
    doors: Optional[list[dict[str, Any]]] = None,
    min_cascade_pa: float = cr.DEFAULT_MIN_CASCADE_PA,
) -> dict:
    """[READ][risk=low] Grade a GMP cleanroom pressure cascade door by door (EU GMP Annex 1).

    The question a suite of classified rooms actually poses is not "is this room
    negative enough" — that is the isolation-room check — but **does the cascade
    hold from A down to D**: every door between differently classified areas has
    to push from the cleaner side to the dirtier one, and the chain is only as
    good as its weakest door. It is what an Annex 1 inspection walks, and the
    failure is silent (a door propped, a supply fan drifting) until an
    environmental-monitoring excursion turns up days later.

    Adjacency is **declared, never inferred**: a room list carries no topology and
    a guessed door would invent the relationship being checked. Omit ``doors`` and
    the cascade is reported as not evaluated, saying what would make it evaluable;
    the room readings are still graded.

    Args:
        rooms: [{room, grade ('A'|'B'|'C'|'D'|'CNC'), pressure_pa}] — pressure
            against ONE common reference (the unclassified corridor or outside),
            so differentials are computed here rather than read from doors that
            may disagree with each other.
        doors: [{from, to}] with `from` the side that must be cleaner.
        min_cascade_pa: Required differential across a door (default 10.0 —
            Annex 1 guidance is 10–15 Pa; use your qualified value).

    Returns dict: {standard, min_cascade_pa, grade_order, rooms_evaluated,
        rooms:[{room, grade, pressure_pa, status, detail}], cascade:{evaluated,
        doors_evaluated, summary, doors:[{from, to, from_grade, to_grade,
        differential_pa, required_pa, status ('correct'|'insufficient'|'reversed'|
        'unknown'), detail}], why_not?}, failure_count, worst, advisory}.

    Example: cleanroom_pressure_cascade(
        rooms=[{"room":"Fill-B","grade":"B","pressure_pa":45},
               {"room":"Gown-C","grade":"C","pressure_pa":30}],
        doors=[{"from":"Fill-B","to":"Gown-C"}]).
    """
    return cr.cleanroom_pressure_cascade(rooms, doors=doors, min_cascade_pa=min_cascade_pa)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def cleanroom_particle_check(
    samples: list[dict[str, Any]],
    limits: dict[str, Any],
) -> dict:
    """[READ][risk=low] Grade airborne particle counts against the limits you supply.

    No compendial table is shipped, on purpose. The grade / state / size limits
    belong to the site's qualified specification at its compendial revision, and a
    transcription this repository cannot verify would decide whether a batch
    environment passed — with the flattering error, a limit set too loose, reading
    as "in specification". A missing entry is reported as `no_limit` and named,
    never skipped and never assumed to pass.

    Args:
        samples: [{room, grade, state ('at_rest'|'in_operation'),
            particles_per_m3: {"0.5": n, "5.0": n}}].
        limits: {grade: {state: {size: max_per_m3}}} — required.

    Returns dict: {standard, readings_evaluated, summary, exceeded_count,
        ungraded_count, readings:[{room, grade, state, size_um, count_per_m3,
        limit_per_m3, status ('within_limit'|'exceeded'|'no_limit'|'no_reading'),
        detail}], worst, advisory}.

    Example: cleanroom_particle_check(
        samples=[{"room":"Fill-B","grade":"B","state":"in_operation",
                  "particles_per_m3":{"0.5": 290000, "5.0": 2600}}],
        limits={"B":{"in_operation":{"0.5": 352000, "5.0": 2930}}}).
    """
    return cr.cleanroom_particle_check(samples, limits)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pharma_water_check(
    samples: list[dict[str, Any]],
    stage1_conductivity_us_cm: Optional[dict[str, Any]] = None,
    toc_limit_ppb: Optional[float] = None,
    temperature_band_c: Optional[dict[str, Any]] = None,
) -> dict:
    """[READ][risk=low] Grade PW / WFI loop readings — the stage-1 procedure, your limits.

    The water edition speaks the right protocols for a pharmaceutical water system
    (Modbus on the still and the skid, HART on the conductivity and TOC
    transmitters, OPC-UA on plant SCADA) but its semantics are municipal — DO, ORP,
    turbidity, chlorine. A purified-water loop is judged on conductivity, TOC and
    loop temperature, by a procedure that is easy to run backwards. Two parts of
    it are what this tool is for:

    **Stage 1 uses the NON-temperature-compensated reading**, and the measured
    temperature is rounded DOWN to the tabulated step. Comparing a transmitter's
    25 °C-compensated output against that table is the common mistake and it
    flatters at loop temperature, so a compensated reading — or one that does not
    say which it is — is refused rather than graded.

    **Exceeding Stage 1 is not a failure**; it means proceed to Stage 2, and the
    verdict is worded the way the compendium words it. A tool that printed FAIL
    there would cost an unnecessary loop rejection and then be ignored.

    Args:
        samples: [{point, conductivity_us_cm?, sample_temperature_c?,
            temperature_compensated?, toc_ppb?, temperature_c?}].
        stage1_conductivity_us_cm: {temperature_step_c: max_us_cm} from your
            specification. None → conductivity is reported `not_graded`.
        toc_limit_ppb: Your TOC limit. None → TOC reported `not_graded`.
        temperature_band_c: {min, max} for the loop. None → not graded.

    Returns dict: {standard, readings_evaluated, summary, not_graded_count,
        readings:[{point, parameter, value, unit, limit, status ('within_limit'|
        'exceeds_stage1_proceed_to_stage2'|'exceeded'|'not_graded'), detail}],
        worst, stage1_note, advisory}.

    Example: pharma_water_check(
        samples=[{"point":"WFI-UP-07","conductivity_us_cm":1.9,
                  "sample_temperature_c":52.0,"temperature_compensated":False,
                  "toc_ppb":180}],
        stage1_conductivity_us_cm={"50": 1.9, "55": 2.1}, toc_limit_ppb=500).
    """
    return pw.pharma_water_check(
        samples,
        stage1_conductivity_us_cm=stage1_conductivity_us_cm,
        toc_limit_ppb=toc_limit_ppb,
        temperature_band_c=temperature_band_c,
    )
