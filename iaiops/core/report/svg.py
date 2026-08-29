"""Inline SVG charts — no library, no script, no external resource.

The repo had no chart of any kind before this. The constraint that decided the
approach is already enforced by the scan report's tests: the page may contain no
``<img>``, ``<link>``, ``<object>`` or ``<source>``, and its script may not touch
the network. That rules out a charting library, a data-URI image, and a canvas
drawn at load time. What is left — and what fits — is a handful of ``<rect>`` and
``<text>`` elements written straight into the document.

Two consequences worth having:

* **Dark mode is free.** Fills are ``var(--ok)`` etc., resolved against the same
  ``:root`` tokens the rest of the page uses, so the chart follows the reader's
  laptop without a second palette to keep in sync.
* **The page still runs nothing.** A chart that needed JavaScript would make
  "this file executes nothing" false on the very page that argues for trust.

Every caller-supplied label is escaped. A chart is not a safe place to skip that:
an SVG ``<text>`` node is parsed as markup like anything else.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.report.fmt import UNKNOWN, finite
from iaiops.core.report.html import escape

#: Bar geometry, in the SVG's own user units. The viewBox scales to the column,
#: so these are proportions rather than pixels — but the NUMBER still matters,
#: because it sets the scale factor at the width this is normally read at. The
#: page's content column is 1100px wide, so a viewBox near that renders the text
#: at roughly its nominal size instead of magnified.
#:
#: The first version paired a 720-unit viewBox with a fixed pixel `height`. With
#: `width="100%"` that combination makes `preserveAspectRatio="meet"` letterbox
#: the drawing: the ELEMENT measured 1100px while the chart occupied 720 of them
#: and the rest was blank, so the bar looked truncated. Caught by looking at the
#: page rather than by any assertion — the geometry was internally consistent,
#: it just was not what a reader saw.
_BAR_W = 1060.0
_BAR_H = 34.0
_ROW_H = 22.0

#: Segments thinner than this are still drawn, but their inline label is dropped:
#: at a few user units the text is wider than the block it names and overlaps its
#: neighbours. The legend still carries every segment, so nothing is lost —
#: dropping the VALUE instead would be the dishonest way to tidy a chart.
_MIN_LABEL_W = 46.0


def _share(value: Any, total: float) -> str:
    """One segment's share, or the dash. NEVER a number it could not compute.

    Was ``_pct`` returning a float clamped with ``min``/``max`` — which NaN walks
    straight through, because every NaN comparison is False. A segment of unknown
    size then printed as "100.0%".
    """
    known = finite(value)
    if known is None or total <= 0:
        return UNKNOWN
    return f"{max(0.0, min(100.0, 100.0 * known / total)):.1f}%"


def stacked_bar_svg(
    segments: list[dict],
    *,
    total: float,
    title: str,
    unit: str = "s",
) -> str:
    """One bar split into ``segments``, plus a legend naming every one.

    Each segment is ``{"label", "value", "var"}`` with an optional ``"dim"``.
    ``total`` is the whole the parts add up to. Segments are drawn in the order
    given — for the OEE ladder that is productive time first, then each loss,
    which reads left-to-right as "here is what the shift became".

    ``dim`` exists because the six losses are coloured by BUCKET (availability /
    performance / quality — the way OEE is taught), so each colour appears twice
    and two adjacent same-coloured blocks would read as one. Dimming the second
    of a pair keeps the bucket legible while still separating the parts.

    A segment whose value exceeds what is left is CLIPPED rather than allowed to
    overflow the bar, and the legend keeps the true number. A chart that silently
    renders 110% of a bar is worse than one that visibly stops at the edge,
    because only the second makes the reader check the input.
    """
    whole = finite(total)
    if whole is None or whole <= 0 or not segments:
        # `total <= 0` alone let NaN through: `nan <= 0` is False. The chart then
        # drew nothing while its legend claimed every segment was 100% of planned.
        return ""
    total = whole
    x = 0.0
    blocks: list[str] = []
    rows: list[str] = []
    for index, seg in enumerate(segments):
        label = seg.get("label", "")
        value = finite(seg.get("value"))
        var, opacity = seg.get("var", "muted"), (0.5 if seg.get("dim") else 0.85)
        # An unknown-sized segment is drawn as nothing and labelled as unknown —
        # not as zero, which is a measurement, and not as 100%, which is what the
        # clamp produced before.
        width = 0.0 if value is None else min(_BAR_W * (max(0.0, value) / total), _BAR_W - x)
        if width > 0:
            blocks.append(
                f'<rect x="{x:.2f}" y="0" width="{width:.2f}" height="{_BAR_H:.0f}" '
                f'fill="var(--{escape(var)})" opacity="{opacity}"></rect>'
            )
            if width >= _MIN_LABEL_W:
                blocks.append(
                    f'<text x="{x + width / 2:.2f}" y="{_BAR_H / 2 + 4:.1f}" '
                    f'text-anchor="middle" font-size="11" fill="var(--bg)" '
                    f'font-weight="700">{_share(value, total)}</text>'
                )
            x += width
        y = _BAR_H + 14 + index * _ROW_H
        rows.append(
            f'<rect x="0" y="{y - 9:.0f}" width="10" height="10" '
            f'fill="var(--{escape(var)})" opacity="{opacity}"></rect>'
            f'<text x="18" y="{y:.0f}" font-size="12" fill="var(--fg)">{escape(label)}</text>'
            f'<text x="{_BAR_W:.0f}" y="{y:.0f}" font-size="12" text-anchor="end" '
            f'fill="var(--muted)">'
            f"{UNKNOWN if value is None else format(value, ',.1f') + escape(unit)} · "
            f"{_share(value, total)}</text>"
        )
    height = _BAR_H + 14 + len(segments) * _ROW_H
    return (
        # No fixed height: `width:100%; height:auto` lets one uniform scale carry
        # the whole drawing, so the bar always fills its column and the legend
        # keeps its proportions instead of being letterboxed beside it.
        f'<svg viewBox="0 0 {_BAR_W:.0f} {height:.0f}" '
        f'style="width:100%;height:auto" role="img" aria-label="{escape(title)}" '
        f'preserveAspectRatio="xMinYMin meet">'
        f"<title>{escape(title)}</title>" + "".join(blocks) + "".join(rows) + "</svg>"
    )


def meter_svg(
    label: str,
    fraction: float | None,
    *,
    refused: str = "",
    clamped_from: float | None = None,
) -> str:
    """One 0–100% meter, or an explicit refusal where the bar would have been.

    ``fraction is None`` means the factor was not measurable. It renders the
    reason, not an empty track: a blank meter reads as zero, and zero is a
    measurement. This is the same rule the CLI follows for a refused factor.

    ``clamped_from`` is the raw value when it exceeded the bar's ceiling. A
    Performance of 3726% clamps to 100%, and a FULL GREEN BAR is the strongest
    "everything is perfect" signal a page can send — on the one artifact that
    gets forwarded into a report. The paragraph below the meters already carried
    the raw number; the bar did not, and the bar is what gets looked at.
    """
    name = escape(label)
    if fraction is None:  # noqa: SIM108 — kept explicit; `finite` covers NaN below
        return (
            f'<div class="meter"><div class="meter-label">{name}</div>'
            f'<div class="meter-refused">{escape(refused) or "not measurable"}</div></div>'
        )
    known = finite(fraction)
    if known is None:
        # NaN is the OTHER not-a-number, and the clamp below promoted it to a full
        # green bar labelled 100.0% — on the headline factor. It means exactly what
        # `fraction is None` means, so it takes the same refusal.
        return (
            f'<div class="meter"><div class="meter-label">{name}</div>'
            f'<div class="meter-refused">{escape(refused) or "not measurable"}</div></div>'
        )
    pct = max(0.0, min(100.0, 100.0 * known))
    var = "ok" if pct >= 85 else ("warn" if pct >= 60 else "bad")

    raw = finite(clamped_from)
    clamp_note = ""
    reading = f"{pct:.1f}%"
    if raw is not None and round(raw, 4) > round(known, 4):
        # The bar is at its ceiling because the input is wrong, not because the
        # line is perfect. Say so on the meter, and in the accessible name.
        clamp_note = f'<div class="meter-clamp">clamped from {100.0 * raw:.1f}%</div>'
        reading = f"{pct:.1f}%, clamped from {100.0 * raw:.1f}%"

    return (
        f'<div class="meter"><div class="meter-label">{name}</div>'
        f'<svg viewBox="0 0 200 8" style="width:100%;height:auto" role="img" '
        f'aria-label="{name} {escape(reading)}">'
        f"<title>{name} {escape(reading)}</title>"
        f'<rect x="0" y="0" width="200" height="8" rx="4" fill="var(--line)"></rect>'
        f'<rect x="0" y="0" width="{pct * 2:.2f}" height="8" rx="4" '
        f'fill="var(--{var})"></rect></svg>'
        f'<div class="meter-value">{pct:.1f}%</div>{clamp_note}</div>'
    )


__all__ = ["meter_svg", "stacked_bar_svg"]
