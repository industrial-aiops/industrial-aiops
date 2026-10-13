"""The forwardable report for one meter's half-hourly data.

Written for the person who pays the bill at a small site — a bursar, a club
treasurer — and the consultant who sends it to them. So it is in English, it
leads with what limits the figures before the figures themselves, and it ends
with what it cannot tell you. One self-contained file: no script, no network, no
external resource, everything escaped (an MPAN or site name is whatever was typed).
"""

from __future__ import annotations

from collections.abc import Sequence

from iaiops.core.brain.meter_charts import daily_bars_svg, heatmap_svg
from iaiops.core.report.fmt import UNKNOWN, finite
from iaiops.core.report.html import cell, document, escape, kv
from iaiops.core.report.svg import stacked_bar_svg

_CSS = """
.warnbox { border-left:4px solid var(--warn); }
.warnbox li { color:var(--fg); }
.card + .card { margin-top:.9rem; }
"""
_BAND_VARS = ("bad", "warn", "accent", "ok", "muted")


def _num(value, fmt: str, suffix: str = "") -> str:
    known = finite(value)
    return UNKNOWN if known is None else f"{format(known, fmt)}{suffix}"


def _list(items: Sequence[str], css: str = "notes") -> str:
    return f'<ul class="{css}">' + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def _tiles(profile: dict, cost: dict | None) -> str:
    cons, cov = profile["consumption"], profile["coverage"]
    estimated = (
        "unknown (not flagged)"
        if cons["estimated_share_pct"] is None
        else _num(cons["estimated_share_pct"], ".1f", "% of kWh")
    )
    tiles = [
        kv("Measured consumption", _num(cons["measured_kwh"], ",.0f", " kWh")),
        kv("Coverage", f"{_num(cov['coverage_pct'], '.1f', '%')} of half hours"),
        kv("Peak demand", _num(profile["peak"]["kw"], ",.1f", " kW")),
        kv("Base load (overnight)", _num(profile["base_load"]["kw"], ",.1f", " kW")),
        kv("Out-of-hours share", _num(profile["out_of_hours"]["share_pct"], ".0f", "%")),
        kv("Load factor", _num(profile["load_factor"], ".2f")),
        kv("Estimated reads", estimated),
    ]
    if cost is not None:
        tiles.append(kv("Cost (excl. VAT, levies)", "£" + _num(cost["total_gbp"], ",.2f")))
    return '<dl class="grid">' + "".join(tiles) + "</dl>"


def _cost_section(cost: dict | None) -> str:
    if cost is None:
        return (
            "<h2>Cost by time band</h2><p class='empty'>No tariff supplied, so no costs were "
            "computed. Pass the site's unit rates (e.g. <code>--tariff tariff.yaml</code>) to "
            "see where the money goes by time of day.</p>"
        )
    bands = cost["bands"]
    segments = [
        {"label": f"{b['name']} ({b['rate_p_per_kwh']:g}p/kWh)", "value": b["kwh"],
         "var": _BAND_VARS[i % len(_BAND_VARS)]}
        for i, b in enumerate(sorted(bands, key=lambda b: -b["rate_p_per_kwh"]))
    ]  # fmt: skip
    chart = stacked_bar_svg(segments, total=cost["measured_kwh"], title="kWh by band", unit=" kWh")
    rows = "".join(
        "<tr>" + cell(b["name"]) + cell(f"{b['rate_p_per_kwh']:g}p")
        + cell(_num(b["kwh"], ",.0f")) + cell("£" + _num(b["cost_gbp"], ",.2f"))
        + cell(_num(b["share_cost_pct"], ".0f", "%")) + "</tr>"
        for b in bands
    )  # fmt: skip
    table = (
        "<div class='scroll'><table><thead><tr><th>Band</th><th>Rate</th><th>kWh</th>"
        f"<th>Cost</th><th>Share of cost</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )
    standing = cost["standing"]
    notes = [
        f"Tariff: {cost['tariff']}. Unit cost £{cost['energy_cost_gbp']:,.2f} at an average "
        f"{_num(cost['avg_p_per_kwh'], '.2f')}p/kWh; standing charge {standing['days']} days × "
        f"{standing['p_per_day']:g}p = £{standing['cost_gbp']:,.2f}.",
        cost["coverage_note"].capitalize() + ".",
    ]
    bound = cost.get("shift_upper_bound")
    if bound:
        notes.append(
            f"Moving use out of the '{bound['band']}' band ({bound['kwh']:,.0f} kWh) to the "
            f"cheapest rate would save at most £{bound['saving_gbp']:,.2f} — an {bound['note']}."
        )
    return f"<h2>Cost by time band</h2><div class='card'>{chart}</div>{table}{_list(notes)}"


def _honesty(profile: dict, cost: dict | None, assumptions: Sequence[str]) -> str:
    base, hours = profile["base_load"], profile["operating_hours"]
    listed = f" ({', '.join(hours['holidays'])})." if hours["holidays"] else "."
    items = [
        profile["consumption"]["note"].capitalize() + ".",
        f"Base load = {base['method']} ({base['samples']} half hours).",
        f"Operating hours are as declared ({hours['spec']}), not detected from the data; "
        "bank holidays count as closed only when listed" + listed,
        profile["out_of_hours"]["note"],
        "A supplier file shows when power was used, not by what. Naming the equipment needs "
        "a site visit, sub-metering or the building management system.",
        *(a[:1].upper() + a[1:] + ("" if a.endswith(".") else ".") for a in assumptions),
    ]  # fmt: skip
    if cost is not None:
        items.append("Not included in costs: " + ", ".join(cost["excluded"]) + ".")
    return "<h2>What this report cannot tell you</h2>" + _list(items)


def render_meter_report(
    profile: dict,
    cost: dict | None = None,
    *,
    site: str = "",
    source: str = "",
    generated_at: str = "",
    assumptions: Sequence[str] = (),
) -> str:
    """One standalone HTML page for one meter's profile (and optional cost)."""
    window = profile["window"]
    heading = escape(site) if site else "Half-hourly electricity profile"
    sub = (
        f"Meter {escape(profile['meter'])} · {escape(window['start_local'][:16])} to "
        f"{escape(window['end_local'][:16])} UK time · from {escape(source) or 'supplied data'}"
    )
    warn = profile.get("warnings") or []
    warn_html = (
        f"<div class='card warnbox'><strong>Read this first</strong>{_list(warn)}</div>"
        if warn
        else ""
    )
    body = (
        f"<h1>{heading}</h1><p class='sub'>{sub}</p>{warn_html}"
        f"<h2>At a glance</h2>{_tiles(profile, cost)}"
        f"<h2>What the data says</h2>{_list(profile.get('findings') or ['No findings.'])}"
        f"<h2>Day by day</h2><div class='card'>{daily_bars_svg(profile['daily'])}"
        "<p class='sub'>Amber bars are days with missing half hours — their totals are "
        "measured only and look lower than the day really was.</p></div>"
        f"<h2>When the power is used</h2><div class='card'>{heatmap_svg(profile['heatmap'])}</div>"
        f"{_cost_section(cost)}{_honesty(profile, cost, assumptions)}"
    )
    footer = (
        f"Generated {escape(generated_at)} by iaiops from the supplied half-hourly file. "
        "Pure analysis of that file: no device or service was contacted."
    )
    return document(
        title=f"Electricity profile — {site or profile['meter']}",
        body=body,
        footer=footer,
        extra_css=_CSS,
    )


__all__ = ["render_meter_report"]
