"""The OEE report — one self-contained HTML file, and what it puts first.

`scan` and `compliance` could both write a file. `oee measure` could not, which
meant the number this product most wants a customer to see was the only one that
could not be put on paper. A terminal is the wrong medium for a five-minute
conversation with a plant manager.

**The section order is the argument, and it is the same argument the scan report
makes.** That module says it plainly: *"Most scanners open with findings; this one
opens with what it did, because the reader of a first survey is usually the person
who has to defend having let it run."* Here the equivalent is coverage. A report
that leads with 66% OEE and hides "we could see 85% of the window" in a footnote
is telling the reader a measured fact and letting them supply a false precision.
So **what the measurement could see comes before the number, and cannot be moved
by configuration.**

Everything the site typed — its name, its tag labels, the free-text note — is
escaped. A report is forwarded by email and opened on a laptop that has no idea
where the strings came from.

[PURE] No I/O, no clock. ``generated_at`` is supplied by the caller so the same
payload renders the same bytes twice; a report that embedded ``now()`` could not
be diffed, and diffing two shifts is most of what this is for.
"""

from __future__ import annotations

import json
from typing import Any

from iaiops.core.report.fmt import humanize_seconds, pct_from_fraction, pct_from_percent
from iaiops.core.report.html import cell, document, escape, kv
from iaiops.core.report.strings import strings
from iaiops.core.report.svg import meter_svg, stacked_bar_svg

#: Loss bucket → CSS colour token. Coloured by BUCKET rather than per loss
#: because that is how OEE is taught: three buckets, six losses. Each colour
#: therefore appears twice, and the second of each pair is dimmed so two adjacent
#: blocks do not read as one.
_BUCKET_VAR = {"availability": "bad", "performance": "warn", "quality": "accent"}

_EXTRA_CSS = """
.meters { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:1.1rem;
          margin:.5rem 0 1.25rem; }
.meter-label { font-size:.75rem; text-transform:uppercase; letter-spacing:.04em;
               color:var(--muted); margin-bottom:.35rem; }
.meter-value { font-size:1.05rem; font-weight:700; margin-top:.3rem; }
.meter-refused { font-size:.82rem; color:var(--muted); font-style:italic; padding:.15rem 0; }
.headline { font-size:2.6rem; font-weight:800; line-height:1.1; margin:.2rem 0 .1rem; }
.headline-sub { color:var(--muted); font-size:.85rem; margin:0 0 1rem; }
.callout { border-left:3px solid var(--warn); background:var(--card); border-radius:0 8px 8px 0;
           padding:.85rem 1.1rem; margin:1.25rem 0; font-size:.88rem; }
.callout h3 { margin:0 0 .35rem; color:var(--warn); }
ul.claims { list-style:none; padding:0; margin:.6rem 0 0; }
ul.claims li { padding:.3rem 0 .3rem 1.5rem; position:relative; font-size:.87rem; }
ul.claims li:before { content:"\\2717"; position:absolute; left:.25rem; color:var(--ok);
                      font-weight:700; }
ul.needs { list-style:none; padding:0; margin:.5rem 0 0; }
ul.needs li { padding:.28rem 0 .28rem 1.5rem; position:relative; font-size:.87rem; }
ul.needs li.have:before { content:"\\2713"; position:absolute; left:.3rem; color:var(--ok);
                          font-weight:700; }
ul.needs li.want:before { content:"\\21b3"; position:absolute; left:.3rem; color:var(--warn);
                          font-weight:700; }
.dim { color:var(--muted); }
"""


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _header(t: dict, *, endpoint: str, site: str, measured: dict, generated_at: str) -> str:
    tag = measured.get("tag", "")
    tiles = "".join(
        [
            kv(t["site"], site),
            kv(t["endpoint"], endpoint),
            kv(t["tag"], tag),
            kv(t["generated"], generated_at),
        ]
    )
    return (
        f"<h1>{escape(t['title'])} — {escape(endpoint or site or t['title'])}</h1>"
        f'<dl class="grid card">{tiles}</dl>'
    )


def _note(t: dict, note: str) -> str:
    """The caller's own caveat, rendered where it cannot be scrolled past.

    The demo supplies its README's sentence here. A forwarded report of a shift
    compressed into seventy seconds, without that sentence, reads as a real
    plant's real OEE — which is the exact overstatement this tool exists to
    refuse, committed by the tool's own demo.
    """
    if not str(note).strip():
        return ""
    return f'<div class="callout"><h3>{escape(t["note_h"])}</h3>{escape(note)}</div>'


def _seen(t: dict, measured: dict) -> str:
    """What the measurement could see. Section one, before any figure."""
    tiles = "".join(
        [
            kv(t["coverage"], pct_from_percent(measured.get("coverage_pct"))),
            kv(
                t["duration"],
                humanize_seconds(_num(measured.get("running_s")) + _num(measured.get("stopped_s"))),
            ),
            kv(t["blind"], humanize_seconds(_num(measured.get("unknown_s")))),
            kv(t["samples"], f"{int(_num(measured.get('n_samples'))):,}"),
            kv(t["cadence"], humanize_seconds(_num(measured.get("sample_cadence_s")))),
            kv(t["stops"], f"{int(_num(measured.get('stops')))}"),
            kv(t["minor_stops"], f"{int(_num(measured.get('minor_stops')))}"),
        ]
    )
    claims = "".join(f"<li>{escape(line)}</li>" for line in t["not_claimed"])
    return (
        f"<h2>{escape(t['seen_h'])}</h2>"
        f'<p class="sub">{escape(t["seen_lead"])}</p>'
        f'<dl class="grid card">{tiles}</dl>'
        f"<h3>{escape(t['not_claimed_h'])}</h3>"
        f'<ul class="claims">{claims}</ul>'
    )


def _figure(t: dict, payload: dict) -> str:
    factors = payload.get("factors") or {}
    perf = payload.get("performance") or {}
    qual = payload.get("quality") or {}
    measured = payload.get("measured") or {}

    meters = "".join(
        [
            meter_svg(
                t["availability"], factors.get("availability"), refused=measured.get("note", "")
            ),
            meter_svg(t["performance"], factors.get("performance"), refused=perf.get("note", "")),
            meter_svg(t["quality"], factors.get("quality"), refused=qual.get("note", "")),
        ]
    )
    oee = payload.get("oee")
    if oee is None:
        missing = ", ".join(
            escape(t[name]) for name, value in factors.items() if value is None and name in t
        )
        headline = (
            f'<p class="headline dim">{escape(t["not_measurable"])}</p>'
            f'<p class="headline-sub">{t["oee_partial"].format(missing=missing or "—")}</p>'
        )
    else:
        headline = (
            f'<p class="headline">{pct_from_fraction(oee)}</p>'
            f'<p class="headline-sub">{escape(t["oee_formula"])}</p>'
        )

    production = payload.get("production") or {}
    tiles = ""
    if production:
        parts = [kv(t["produced"], f"{_num(production.get('produced')):,.0f}")]
        if production.get("discontinuities"):
            parts.append(kv(t["discontinuities"], production["discontinuities"]))
        if production.get("unobserved_steps"):
            parts.append(kv(t["unobserved_steps"], production["unobserved_steps"]))
        tiles = f'<dl class="grid card">{"".join(parts)}</dl>'

    warning = ""
    if perf.get("warning"):
        warning = f'<p class="sub">{escape(perf["warning"])}</p>'

    return (
        f'<h2>{escape(t["oee_h"])}</h2>{headline}<div class="meters">{meters}</div>{warning}{tiles}'
    )


def _losses(t: dict, losses: dict) -> str:
    if losses.get("status") != "ok":
        return (
            f'<h2>{escape(t["losses_h"])}</h2><p class="empty">{escape(losses.get("note", ""))}</p>'
        )

    total = _num(losses.get("planned_time_s"))
    segments: list[dict] = [
        {
            "label": t["fully_productive"],
            "value": _num(losses.get("fully_productive_time_s")),
            "var": "ok",
        }
    ]
    seen: set[str] = set()
    rows: list[str] = []
    for entry in losses.get("losses") or ():
        name = str(entry.get("loss", ""))
        bucket = str(entry.get("bucket", ""))
        var = _BUCKET_VAR.get(bucket, "muted")
        label = t.get(f"loss_{name}", name)
        segments.append(
            {"label": label, "value": _num(entry.get("time_s")), "var": var, "dim": var in seen}
        )
        seen.add(var)
        basis = t["classified"] if entry.get("classified") else t["unclassified"]
        rows.append(
            "<tr>"
            + cell(label)
            + cell(t.get(f"bucket_{bucket}", bucket))
            + cell(humanize_seconds(_num(entry.get("time_s"))))
            + cell(pct_from_fraction(entry.get("pct_of_planned")))
            + cell(entry.get("count"))
            + cell(basis)
            + "</tr>"
        )

    chart = stacked_bar_svg(segments, total=total, title=t["losses_h"])
    head = "".join(
        f"<th>{escape(label)}</th>"
        for label in (t["loss"], t["bucket"], t["time"], t["share"], t["produced"], t["provenance"])
    )
    biggest = losses.get("largest_loss") or {}
    largest = ""
    if biggest and _num(biggest.get("time_s")) > 0:
        name = t.get(f"loss_{biggest.get('loss', '')}", biggest.get("loss", ""))
        largest = (
            f'<p class="sub"><strong>{escape(t["largest"])}: {escape(name)}</strong>'
            f" — {escape(t['largest_note'])}</p>"
        )
    return (
        f"<h2>{escape(t['losses_h'])}</h2>{chart}{largest}"
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f'<p class="sub">{escape(losses.get("note", ""))}</p>'
    )


def _comparison(t: dict, comparison: dict | None) -> str:
    if not comparison:
        return ""
    tiles = "".join(
        [
            kv(t["reported"], pct_from_percent(comparison.get("reported_pct"))),
            kv(t["measured"], pct_from_percent(comparison.get("measured_pct"))),
            kv(
                t["gap"],
                f"{_num(comparison.get('gap_points')):+.2f} {t['points']}"
                if comparison.get("gap_points") is not None
                else "—",
            ),
        ]
    )
    return (
        f"<h2>{escape(t['compare_h'])}</h2>"
        f'<dl class="grid card">{tiles}</dl>'
        f'<p class="sub">{escape(comparison.get("explanation", ""))}</p>'
    )


def _needs(t: dict, payload: dict) -> str:
    """The prerequisite row a sales deck leaves out.

    Every figure above rests on something a person had to declare. Listing what
    was supplied AND what is still missing is what stops the report reading as
    "point it at a plant and it does this" — which is the promise that fails on
    first contact with a real site.
    """
    measured = payload.get("measured") or {}
    losses = payload.get("losses") or {}
    factors = payload.get("factors") or {}
    production = payload.get("production") or {}

    have: list[str] = [t["need_collection"], t["need_run_state"]]
    want: list[str] = []
    (have if production else want).append(t["need_total_count"])
    (have if factors.get("quality") is not None else want).append(t["need_good_count"])
    (have if factors.get("performance") is not None else want).append(t["need_cycle"])

    if measured.get("status") != "ok":
        want.append(escape(measured.get("note", "")))
    if losses.get("status") == "inputs_not_declared":
        want.append(escape(losses.get("note", "")))

    items = "".join(f'<li class="have">{escape(line)}</li>' for line in have)
    items += "".join(f'<li class="want">{escape(line)}</li>' for line in want)
    if not want:
        items += f'<li class="have">{escape(t["nothing_missing"])}</li>'
    return (
        f"<h2>{escape(t['needs_h'])}</h2>"
        f'<p class="sub">{escape(t["needs_lead"])}</p>'
        f'<ul class="needs">{items}</ul>'
    )


def _appendix(t: dict, payload: dict) -> str:
    blob = json.dumps(payload, indent=2, sort_keys=True, default=str, ensure_ascii=False)
    return (
        f"<h2>{escape(t['appendix_h'])}</h2>"
        f'<p class="sub">{escape(t["appendix_lead"])}</p>'
        f"<pre><code>{escape(blob)}</code></pre>"
    )


def render_oee_report(
    payload: dict,
    *,
    endpoint: str = "",
    site: str = "",
    lang: str = "en",
    note: str = "",
    generated_at: str = "",
) -> str:
    """[PURE] One self-contained HTML file from an ``oee measure`` result.

    ``payload`` is exactly what ``iaiops oee measure --json`` emits. Unknown
    ``lang`` raises rather than falling back to English — a half-translated page
    gives the reader no way to tell a gap from a deliberate term.
    """
    t = strings(lang)
    measured = payload.get("measured") or {}
    losses = payload.get("losses") or {}
    body = "".join(
        [
            _header(t, endpoint=endpoint, site=site, measured=measured, generated_at=generated_at),
            _note(t, note),
            _seen(t, measured),
            _figure(t, payload),
            _losses(t, losses),
            _comparison(t, payload.get("comparison")),
            _needs(t, payload),
            _appendix(t, payload),
        ]
    )
    return document(
        title=f"{t['title']} — {endpoint or site}",
        body=body,
        footer=escape(t["footer"]),
        lang=lang,
        extra_css=_EXTRA_CSS,
    )


__all__ = ["render_oee_report"]
