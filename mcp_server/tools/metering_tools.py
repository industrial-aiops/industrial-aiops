"""Half-hourly electricity metering MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads with
the ``building`` and ``renewables`` editions, not in the always-on brain. Pure
analysis over a supplier half-hourly CSV the caller passes in as text — no file,
device or network access. Same engine as ``iaiops meter`` (the CLI also writes the
HTML report; these tools return data only).
"""

from typing import Any

from iaiops.core.brain import meter_analysis
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors

#: An agent passes the file as a string; a year of one meter is ~1 MB wide-format.
MAX_CSV_TEXT = 5 * 1024 * 1024


def _check_size(csv_text: str) -> None:
    if len(csv_text) > MAX_CSV_TEXT:
        raise ValueError(
            f"csv_text is {len(csv_text) // 1024} KiB; cap {MAX_CSV_TEXT // 1024} KiB — "
            "split by meter or period, or use `iaiops meter profile` on the file"
        )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def meter_hh_check(csv_text: str, unit: str = "auto", timestamp_marks: str = "start") -> dict:
    """[READ][risk=low] What a supplier half-hourly electricity CSV contains, before analysis.

    Detects the layout (wide: date + 46–50 half-hour columns; long: timestamp + kWh),
    lists meters (MPAN) with their first/last half hour in UK local time, and counts
    what was rejected: blank / non-numeric cells (kept as MISSING, never zero),
    negative values, non-UK dates, clock-change mismatches, conflicting duplicates.
    Also returns every assumption the parser made (unit, timestamp convention,
    unknown read type). Pure analysis of the text you pass; no device contacted.

    Args:
        csv_text: The CSV file content (≤ 5 MiB).
        unit: auto | kwh | wh | kw (kW = half-hour average demand; kWh = kW ÷ 2).
        timestamp_marks: Long layout only — 'start' or 'end' of the half hour.

    Returns dict: {layout, unit, meters:[{meter, intervals, first_local, last_local}],
        counts:{intervals, rows_rejected, blank_or_non_numeric, ...}, assumptions, warnings}.
    """
    _check_size(csv_text)
    return meter_analysis.parse_summary(csv_text, unit=unit, timestamp_marks=timestamp_marks)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def meter_load_profile(
    csv_text: str,
    meter: str = "",
    operating_hours: str = "mon-fri 08:00-18:00",
    holidays: list[str] | None = None,
    since: str = "",
    until: str = "",
    tariff: dict[str, Any] | None = None,
    unit: str = "auto",
    timestamp_marks: str = "start",
    include_series: bool = False,
) -> dict:
    """[READ][risk=low] Where and when a site uses electricity, from supplier half-hourly data.

    Per meter: coverage (missing half hours are counted, never filled or scaled up),
    measured kWh, estimated-read share (or 'unknown' when the file has no flag),
    peak kW and when, overnight base load (median 00:00–05:00), out-of-hours kWh and
    share against the DECLARED operating hours, out-of-hours use above base load
    (an indication of opportunity, not a guaranteed saving), complete-day weekday vs
    weekend averages, load factor, plain-English findings and warnings. With a
    ``tariff``, cost by time band, standing charge, and an upper bound for moving
    use out of the dearest band (excludes VAT, CCL, kVA and DUoS line items).

    Args:
        csv_text: Supplier HH CSV content (≤ 5 MiB).
        meter: Only this MPAN / meter (default: every meter in the file).
        operating_hours: e.g. 'mon-fri 08:00-18:00; sat 09:00-13:00'.
        holidays: Closed days, ['YYYY-MM-DD', ...] — counted as closed and priced as Sunday.
        since / until: Optional window (ISO-8601; naive = UK local); both or neither.
        tariff: {name?, unit_rates:[{name, rate (p/kWh), days ('all'|'weekdays'|'weekends'|
            ['mon',..]|'mon-fri'), start 'HH:MM', end 'HH:MM'}], standing_charge_p_per_day?}.
            First matching band wins; every half hour must be priced.
        unit / timestamp_marks: as for meter_hh_check.
        include_series: Also return the daily series and the 7×48 heatmap (bulky).

    Returns dict: {parse:{...meter_hh_check...}, profiles:{<meter>:{profile, cost|null}}}.
    """
    _check_size(csv_text)
    return meter_analysis.analyse_hh(
        csv_text, meter=meter, operating_hours=operating_hours, holidays=holidays or (),
        since=since or None, until=until or None, tariff=tariff, unit=unit,
        timestamp_marks=timestamp_marks, include_series=include_series,
    )  # fmt: skip
