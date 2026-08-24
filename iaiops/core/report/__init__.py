"""Self-contained HTML report primitives, shared by every report the tool emits."""

from __future__ import annotations

from iaiops.core.report.html import CSS, JS, cell, document, escape, kv
from iaiops.core.report.svg import meter_svg, stacked_bar_svg

__all__ = ["CSS", "JS", "cell", "document", "escape", "kv", "meter_svg", "stacked_bar_svg"]
