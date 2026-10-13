"""Inline SVG charts for the half-hourly meter report — no library, no script.

Same rules as :mod:`iaiops.core.report.svg`: colours are page tokens so dark mode
is free, every label is escaped, and a value that is not a finite number is drawn
as "no data" — never as zero, which is a reading, and never as a full bar.
"""

from __future__ import annotations

from iaiops.core.report.fmt import finite
from iaiops.core.report.html import escape

_W = 1060.0
_BARS_H = 200.0
_AXIS = 46.0
_CELL_H = 18.0
_LABEL_W = 40.0


def _svg(width: float, height: float, title: str, body: str) -> str:
    return (
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" style="width:100%;height:auto" '
        f'role="img" aria-label="{escape(title)}" preserveAspectRatio="xMinYMin meet">'
        f"<title>{escape(title)}</title>{body}</svg>"
    )


def daily_bars_svg(daily: list[dict]) -> str:
    """One bar per local day; incomplete days drawn in the warning colour."""
    if not daily:
        return ""
    values = [finite(d.get("kwh")) for d in daily]
    top = max((v for v in values if v is not None), default=0.0)
    plot_w = _W - _AXIS
    step = plot_w / len(daily)
    bar_w = max(1.0, step * 0.8)
    parts: list[str] = []
    for i, (day, value) in enumerate(zip(daily, values, strict=True)):
        x = _AXIS + i * step
        label = escape(day.get("date", ""))
        if value is None or top <= 0:
            parts.append(
                f'<rect x="{x:.2f}" y="{_BARS_H - 3:.0f}" width="{bar_w:.2f}" height="3" '
                f'fill="var(--line)"><title>{label}: no data</title></rect>'
            )
            continue
        h = (_BARS_H - 10) * value / top
        complete = bool(day.get("complete"))
        fill = "var(--accent)" if complete else "var(--warn)"
        note = (
            ""
            if complete
            else (
                f" — incomplete ({day.get('periods_measured')}/"
                f"{day.get('periods_in_day')} half hours)"
            )
        )
        parts.append(
            f'<rect x="{x:.2f}" y="{_BARS_H - h:.2f}" width="{bar_w:.2f}" height="{h:.2f}" '
            f'fill="{fill}"><title>{label}: {value:,.0f} kWh{escape(note)}</title></rect>'
        )
    first, last = escape(daily[0].get("date", "")), escape(daily[-1].get("date", ""))
    axis = (
        f'<text x="{_AXIS - 6:.0f}" y="14" font-size="11" text-anchor="end" '
        f'fill="var(--muted)">{top:,.0f}</text>'
        f'<text x="{_AXIS - 6:.0f}" y="{_BARS_H:.0f}" font-size="11" text-anchor="end" '
        f'fill="var(--muted)">0</text>'
        f'<text x="{_AXIS:.0f}" y="{_BARS_H + 16:.0f}" font-size="11" '
        f'fill="var(--muted)">{first}</text>'
        f'<text x="{_W:.0f}" y="{_BARS_H + 16:.0f}" font-size="11" text-anchor="end" '
        f'fill="var(--muted)">{last}</text>'
        f'<line x1="{_AXIS:.0f}" y1="{_BARS_H:.0f}" x2="{_W:.0f}" y2="{_BARS_H:.0f}" '
        f'stroke="var(--line)"></line>'
    )
    return _svg(_W, _BARS_H + 22, "Daily consumption, kWh", "".join(parts) + axis)


def heatmap_svg(heatmap: dict) -> str:
    """Mean demand by weekday × half hour; empty cells say "no data"."""
    rows = heatmap.get("mean_kw") or []
    names = heatmap.get("weekdays") or []
    values = [finite(v) for row in rows for v in row]
    top = max((v for v in values if v is not None), default=0.0)
    cell_w = (_W - _LABEL_W) / 48
    parts: list[str] = []
    for d, row in enumerate(rows):
        y = 18 + d * _CELL_H
        name = escape(names[d] if d < len(names) else "")
        parts.append(
            f'<text x="0" y="{y + 13:.0f}" font-size="11" fill="var(--muted)">{name}</text>'
        )
        for s, raw in enumerate(row):
            x = _LABEL_W + s * cell_w
            clock = f"{s // 2:02d}:{30 * (s % 2):02d}"
            value = finite(raw)
            if value is None or top <= 0:
                parts.append(
                    f'<rect x="{x:.2f}" y="{y:.0f}" width="{cell_w - 1:.2f}" '
                    f'height="{_CELL_H - 2:.0f}" fill="var(--code)">'
                    f"<title>{name} {clock}: no data</title></rect>"
                )
                continue
            opacity = 0.08 + 0.92 * value / top
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.0f}" width="{cell_w - 1:.2f}" '
                f'height="{_CELL_H - 2:.0f}" fill="var(--accent)" fill-opacity="{opacity:.3f}">'
                f"<title>{name} {clock}: {value:,.1f} kW</title></rect>"
            )
    hours = "".join(
        f'<text x="{_LABEL_W + h * 2 * cell_w:.1f}" y="12" font-size="10" '
        f'fill="var(--muted)">{h:02d}:00</text>'
        for h in range(0, 24, 3)
    )
    height = 18 + len(rows) * _CELL_H + 18
    legend = (
        f'<text x="{_W:.0f}" y="{height - 4:.0f}" font-size="11" text-anchor="end" '
        f'fill="var(--muted)">darkest = {top:,.1f} kW mean demand · grey = no data</text>'
    )
    return _svg(
        _W, height, "Mean demand by weekday and time of day", hours + "".join(parts) + legend
    )


__all__ = ["daily_bars_svg", "heatmap_svg"]
