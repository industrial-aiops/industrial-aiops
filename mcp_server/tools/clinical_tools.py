"""Clinical-facility MCP tools (READ-ONLY) — patient-safety checks.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): these
tools load only when the ``building`` or ``clinical`` edition is selected, NOT on
a bare ``bacnet`` selection and NOT in the always-on brain. Pure analysis over
readings (BACnet AI points / gas alarm panel / historian). Advisory — the
station's own life-safety alarm panels remain the source of truth.
"""

from typing import Any

from iaiops.core.brain import clinical_facility as cf
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def isolation_room_check(
    rooms: list[dict[str, Any]],
    min_magnitude_pa: float = 2.5,
    low_margin_pa: float = 5.0,
) -> dict:
    """[READ][risk=low] Isolation-room pressurization compliance (ASHRAE 170 / CDC).

    The healthcare-facility safety check generic BMS lacks: airborne-infection
    isolation (AII) rooms must stay NEGATIVE to the corridor, protective-
    environment (PE) rooms POSITIVE, at a minimum ~2.5 Pa differential. Grades
    each room from its differential-pressure reading — 'reversed' (wrong
    polarity, a reportable safety event), 'breach' (right polarity but too
    weak), 'low_margin', or 'compliant' — worst-first, citing the number behind
    every flag. Pure analysis over readings you pass in (differential-pressure
    AI points from bacnet_read_points, or a historian); read-only and advisory.

    Args:
        rooms: [{room, mode ('negative'|'positive'|'neutral'), differential_pa}]
            — differential_pa is room-minus-corridor pressure (negative = room
            below corridor).
        min_magnitude_pa: Minimum required differential magnitude (default 2.5 Pa).
        low_margin_pa: Correct-but-within-this-of-the-minimum → low_margin (default 5.0 Pa).

    Returns dict: {rooms_evaluated, standard, min_magnitude_pa, low_margin_pa,
        summary:{compliant, low_margin, breach, reversed, info}, breach_count,
        breaches:[{room, mode, differential_pa, status, detail}], worst}.

    Example: isolation_room_check(rooms=[{"room":"ICU-Iso-3","mode":"negative",
        "differential_pa":-8.0}, {"room":"BMT-12","mode":"positive","differential_pa":1.0}]).
    """
    return cf.isolation_room_check(
        rooms, min_magnitude_pa=min_magnitude_pa, low_margin_pa=low_margin_pa
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def medical_gas_check(sources: list[dict[str, Any]]) -> dict:
    """[READ][risk=low] Medical-gas / vacuum source pressure compliance (NFPA 99 / HTM 02-01).

    The other healthcare-facility safety check: grades each medical-gas source's
    pressure against its NFPA 99 band — positive-pressure gases (oxygen / medical
    air / N2O / nitrogen / CO2) must sit inside ~345–380 kPa; medical vacuum /
    WAGD must be at least as deep as the vacuum threshold. Each source →
    'normal' / 'low_pressure' / 'high_pressure' / 'insufficient_vacuum' /
    'critical', worst-first, citing the number. Pure analysis over readings you
    pass in (from BACnet AI points or the gas alarm panel); read-only, advisory —
    the station's NFPA 99 alarm panel remains the source of truth.

    Args:
        sources: [{system, gas ('oxygen'|'medical_air'|'nitrous_oxide'|'nitrogen'|
            'carbon_dioxide'|'vacuum'|'wagd'), pressure_kpa}] — gauge pressure in kPa.

    Returns dict: {sources_evaluated, standard, summary, alarm_count,
        alarms:[{system, gas, pressure_kpa, status, detail}], worst}.

    Example: medical_gas_check(sources=[{"system":"OR-O2","gas":"oxygen",
        "pressure_kpa":360}, {"system":"ICU-Vac","gas":"vacuum","pressure_kpa":-55}]).
    """
    return cf.medical_gas_check(sources)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def or_environment_check(rooms: list[dict[str, Any]]) -> dict:
    """[READ][risk=low] Operating-room ventilation compliance (ASHRAE 170 Table 7.1).

    Grades each OR's environment — temperature 20–24 °C, relative humidity
    20–60 %, air changes ≥ 20/hr — flagging any parameter out of range; each room
    takes the worst of its parameters, worst-first, citing every number. Pure
    analysis over readings you pass in (BACnet AI points / BMS); read-only,
    advisory. Complements isolation_room_check (pressure) with the OR air package.

    Args:
        rooms: [{room, temp_c?, humidity_pct?, air_changes_per_hour?}] — only the
            parameters present are graded.

    Returns dict: {rooms_evaluated, standard, summary, breach_count,
        breaches:[{room, status, flags:[{parameter, value, unit, detail}]}], worst}.

    Example: or_environment_check(rooms=[{"room":"OR-3","temp_c":25.5,
        "humidity_pct":18,"air_changes_per_hour":15}]).
    """
    return cf.or_environment_check(rooms)
