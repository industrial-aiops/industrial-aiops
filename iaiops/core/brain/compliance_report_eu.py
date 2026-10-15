"""NIS2 / CRA self-assessment report — Markdown, English, from ``compliance_eu``.

Reuses the item tables verbatim (nothing re-typed here) and the Markdown table
helper of ``compliance_report``. Product evidence and organisational measures
are separate sections, so a reader cannot mistake "the plant's job" for "covered".
"""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

from iaiops.core.brain.compliance_eu import (
    COVERAGE,
    EU_DISCLAIMER,
    MECHANISMS,
    compliance_eu,
    normalize_eu_framework,
)

TableFn = Callable[[tuple[str, ...], list[tuple[str, ...]]], list[str]]

EU_SELECTORS = MappingProxyType({"nis2": ("nis2",), "cra": ("cra",), "eu": ("nis2", "cra")})


def eu_frameworks_for(framework: str) -> tuple[str, ...]:
    """'nis2' / 'cra' / 'eu' → the framework ids the report renders."""
    key = str(framework).strip().lower()
    if key in EU_SELECTORS:
        return EU_SELECTORS[key]
    return (normalize_eu_framework(key),)  # raises naming nis2 / cra / eu


def _header(data: dict, number: int, table: TableFn) -> list[str]:
    fw = data["framework"]
    summary = data["coverage_summary"]
    lines = [
        f"## {number}. {fw['name']}",
        "",
        f"- **Obliges**: {fw['obliges']}",
        f"- **Applies**: {data['applies']}",
        f"- **Scope**: {data['scope']}",
        "",
    ]
    lines.extend(
        table(
            ("Items", *COVERAGE), [(str(data["item_count"]), *(str(summary[c]) for c in COVERAGE))]
        )
    )
    return lines


def _row(item: dict) -> tuple[str, ...]:
    mechanisms = "; ".join(MECHANISMS[m]["name"] for m in item["mechanisms"]) or "—"
    return (
        item["ref"],
        item["measure"],
        item["coverage"],
        item["iaiops"],
        mechanisms,
        item["gap"] or "—",
    )


def _section(data: dict, number: int, table: TableFn) -> list[str]:
    items = data["items"]
    lines = _header(data, number, table)
    lines.extend(["", f"### {number}.1 Product evidence and gaps", ""])
    lines.extend(
        table(
            ("Item", "Measure", "Coverage", "iaiops", "Mechanism", "What is left"),
            [_row(i) for i in items if i["coverage"] != "organisational"],
        )
    )
    organisational = [i for i in items if i["coverage"] == "organisational"]
    lines.extend(["", f"### {number}.2 Organisational measures (no product evidence)", ""])
    if organisational:
        lines.extend(f"- **{i['ref']}** — {i['measure']} {i['iaiops']}" for i in organisational)
    else:
        lines.append("- (none)")
    lines.append("")
    return lines


def _appendix(selected: list[dict]) -> list[str]:
    cited = sorted({m for d in selected for i in d["items"] for m in i["mechanisms"]})
    lines = [
        "## Appendix A. Mechanisms cited",
        "",
        "Each mechanism with its known limit and where it lives in the code "
        "(anchors are resolved by the test suite).",
        "",
    ]
    for mech_id in cited:
        mech = MECHANISMS[mech_id]
        anchors = ", ".join(f"`{a.split(':', 1)[1]}`" for a in mech["anchors"])
        lines.extend([f"### {mech['name']}", "", mech["fact"], "", f"- Code: {anchors}", ""])
    return lines


def render_eu_markdown(
    *,
    framework: str,
    site: str,
    date: str,
    version: str,
    table: TableFn,
) -> str:
    """Render the NIS2 and/or CRA self-assessment as Markdown."""
    selected = [compliance_eu(fw) for fw in eu_frameworks_for(framework)]
    lines: list[str] = [
        "# Cybersecurity self-assessment — NIS2 / CRA (iaiops)",
        "",
        f"- **Site**: {site or '(not specified)'}",
        f"- **Date**: {date or '(not specified)'}",
        f"- **iaiops version**: {version}",
        f"- **Frameworks**: {' / '.join(d['framework']['name'] for d in selected)}",
        "",
        f"> {EU_DISCLAIMER}",
        "",
    ]
    for number, data in enumerate(selected, start=1):
        lines.extend(_section(data, number, table))
    lines.extend(_appendix(selected))
    lines.extend(
        [
            "## Appendix B. Source",
            "",
            selected[0]["source"],
            "",
            "---",
            "",
            f"> {EU_DISCLAIMER}",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["EU_SELECTORS", "eu_frameworks_for", "render_eu_markdown"]
