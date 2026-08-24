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

from iaiops.core.report.html import escape

#: Bar geometry, in the SVG's own user units. The viewBox scales to the column,
#: so these are proportions rather than pixels.
_BAR_W = 720.0
_BAR_H = 34.0
_ROW_H = 22.0

#: Segments thinner than this are still drawn, but their inline label is dropped:
#: at a few user units the text is wider than the block it names and overlaps its
#: neighbours. The legend still carries every segment, so nothing is lost —
#: dropping the VALUE instead would be the dishonest way to tidy a chart.
_MIN_LABEL_W = 46.0


def _pct(value: float, total: float) -> float:
    return 0.0 if total <= 0 else max(0.0, min(100.0, 100.0 * value / total))


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
    if total <= 0 or not segments:
        return ""
    x = 0.0
    blocks: list[str] = []
    rows: list[str] = []
    for index, seg in enumerate(segments):
        label, value = seg["label"], float(seg["value"])
        var, opacity = seg["var"], (0.5 if seg.get("dim") else 0.85)
        width = min(_BAR_W * (max(0.0, value) / total), _BAR_W - x)
        if width > 0:
            blocks.append(
                f'<rect x="{x:.2f}" y="0" width="{width:.2f}" height="{_BAR_H:.0f}" '
                f'fill="var(--{escape(var)})" opacity="{opacity}"></rect>'
            )
            if width >= _MIN_LABEL_W:
                blocks.append(
                    f'<text x="{x + width / 2:.2f}" y="{_BAR_H / 2 + 4:.1f}" '
                    f'text-anchor="middle" font-size="11" fill="var(--bg)" '
                    f'font-weight="700">{_pct(value, total):.0f}%</text>'
                )
            x += width
        y = _BAR_H + 14 + index * _ROW_H
        rows.append(
            f'<rect x="0" y="{y - 9:.0f}" width="10" height="10" '
            f'fill="var(--{escape(var)})" opacity="{opacity}"></rect>'
            f'<text x="18" y="{y:.0f}" font-size="12" fill="var(--fg)">{escape(label)}</text>'
            f'<text x="{_BAR_W:.0f}" y="{y:.0f}" font-size="12" text-anchor="end" '
            f'fill="var(--muted)">{value:,.1f}{escape(unit)} · '
            f"{_pct(value, total):.1f}%</text>"
        )
    height = _BAR_H + 14 + len(segments) * _ROW_H
    return (
        f'<svg viewBox="0 0 {_BAR_W:.0f} {height:.0f}" width="100%" '
        f'height="{height:.0f}" role="img" aria-label="{escape(title)}" '
        f'preserveAspectRatio="xMinYMin meet">'
        f"<title>{escape(title)}</title>" + "".join(blocks) + "".join(rows) + "</svg>"
    )


def meter_svg(label: str, fraction: float | None, *, refused: str = "") -> str:
    """One 0–100% meter, or an explicit refusal where the bar would have been.

    ``fraction is None`` means the factor was not measurable. It renders the
    reason, not an empty track: a blank meter reads as zero, and zero is a
    measurement. This is the same rule the CLI follows for a refused factor.
    """
    name = escape(label)
    if fraction is None:
        return (
            f'<div class="meter"><div class="meter-label">{name}</div>'
            f'<div class="meter-refused">{escape(refused) or "not measurable"}</div></div>'
        )
    pct = max(0.0, min(100.0, 100.0 * float(fraction)))
    var = "ok" if pct >= 85 else ("warn" if pct >= 60 else "bad")
    return (
        f'<div class="meter"><div class="meter-label">{name}</div>'
        f'<svg viewBox="0 0 200 10" width="100%" height="10" role="img" '
        f'aria-label="{name} {pct:.1f} percent">'
        f"<title>{name} {pct:.1f}%</title>"
        f'<rect x="0" y="0" width="200" height="10" rx="5" fill="var(--line)"></rect>'
        f'<rect x="0" y="0" width="{pct * 2:.2f}" height="10" rx="5" '
        f'fill="var(--{var})"></rect></svg>'
        f'<div class="meter-value">{pct:.1f}%</div></div>'
    )


__all__ = ["meter_svg", "stacked_bar_svg"]
