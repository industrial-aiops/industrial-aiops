"""Plain-English findings and warnings for a load profile.

Findings state facts with their numbers; they do not grade the site. Whether 40%
out-of-hours use is "bad" depends on what runs at night, which the file cannot
know — so the sentence gives the figure and leaves the judgement to the person
who has walked the building. Warnings say what limits the figures.
"""

from __future__ import annotations

#: Below this coverage the totals are visibly partial and the report says so first.
LOW_COVERAGE_PCT = 90.0
#: Above this share of estimated kWh the reader is told the data is partly modelled.
HIGH_ESTIMATED_PCT = 10.0


def _kwh(value: float) -> str:
    return f"{value:,.0f} kWh"


def findings(p: dict) -> list[str]:
    """Fact sentences, most consequential first."""
    out: list[str] = []
    ooh = p["out_of_hours"]
    if ooh["share_pct"] is not None:
        out.append(
            f"{ooh['share_pct']:.0f}% of measured consumption ({_kwh(ooh['kwh'])}) fell "
            f"outside the declared operating hours ({p['operating_hours']['spec']})."
        )
    if ooh["above_base_load_kwh"]:
        out.append(
            f"If out-of-hours demand had dropped to the overnight base load, about "
            f"{_kwh(ooh['above_base_load_kwh'])} of the measured period would not have been "
            "used — an indication of opportunity, not a guaranteed saving."
        )
    base, peak = p["base_load"]["kw"], p["peak"]["kw"]
    if base is not None and peak > 0:
        out.append(
            f"The overnight base load is {base:,.1f} kW — {100.0 * base / peak:.0f}% of the "
            f"peak demand of {peak:,.1f} kW (at {p['peak']['at_local'][:16]})."
        )
    days = p["day_types"]
    weekday, weekend = days["weekday"]["avg_daily_kwh"], days["weekend"]["avg_daily_kwh"]
    if weekday and weekend is not None:
        out.append(
            f"A complete closed day (weekend or holiday) averages {_kwh(weekend)} against "
            f"{_kwh(weekday)} on a working day — {100.0 * weekend / weekday:.0f}%."
        )
    if p["load_factor"] is not None:
        out.append(
            f"Load factor {p['load_factor']:.2f} (average ÷ peak demand); a low figure means "
            "short, sharp peaks that a capacity charge prices in full."
        )
    return out


def warnings(p: dict) -> list[str]:
    """What limits the figures, worst first."""
    out: list[str] = []
    cov = p["coverage"]
    if cov["coverage_pct"] < LOW_COVERAGE_PCT:
        out.append(
            f"Only {cov['coverage_pct']:.1f}% of the period was measured "
            f"({cov['missing_periods']} half hours missing); totals cover measured half "
            "hours only and are not scaled up."
        )
    elif cov["missing_periods"]:
        out.append(f"{cov['missing_periods']} half hours missing; totals are not scaled up.")
    cons = p["consumption"]
    if cons["read_type"] == "unknown":
        out.append("The file does not say which values are estimated, so none can be ruled out.")
    elif cons["estimated_share_pct"] and cons["estimated_share_pct"] > HIGH_ESTIMATED_PCT:
        out.append(
            f"{cons['estimated_share_pct']:.0f}% of measured kWh is estimated by the supplier "
            "or data collector, not read from the meter."
        )
    if p["base_load"]["kw"] is None:
        out.append("No overnight data, so no base load could be measured.")
    if not p["day_types"]["weekday"]["full_days"] or not p["day_types"]["weekend"]["full_days"]:
        out.append(
            "No complete working day or no complete closed day; day-type comparison is partial."
        )
    return out


__all__ = ["HIGH_ESTIMATED_PCT", "LOW_COVERAGE_PCT", "findings", "warnings"]
