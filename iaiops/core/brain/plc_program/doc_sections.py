"""HTML building blocks for ``program_doc`` — tables, sections, the field xref.

Every value goes through :func:`iaiops.core.report.html.cell` / ``escape``; the
functions here return markup, and nothing they receive is trusted as markup.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from iaiops.core.report.html import cell, escape


def section(title: str, body: str) -> str:
    """One titled card. ``body`` is markup built by this module."""
    return f"<section class='card'><h2>{escape(title)}</h2>{body}</section>"


def rows_table(cols: Sequence[str], rows: Sequence[Sequence[Any]], *, empty: str) -> str:
    """A table, or the ``empty`` sentence when there are no rows."""
    if not rows:
        return f"<p class='empty'>{escape(empty)}</p>" if empty else ""
    head = "".join(f"<th>{escape(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(cell(v) for v in row) + "</tr>" for row in rows)
    return f"<div class='scroll'><table><tr>{head}</tr>{body}</table></div>"


def _sites(row: dict[str, Any]) -> str:
    lines = [str(s.get("line")) for s in row.get("sites") or []]
    more = row.get("site_count", len(lines)) - len(lines)
    return ", ".join(lines) + (f" (+{more})" if more > 0 else "")


def _notes(notes: Sequence[str]) -> str:
    items = "".join(f"<li>{escape(n)}</li>" for n in notes)
    return f"<ul class='notes'>{items}</ul>" if items else ""


def _in_export_empty(result: dict[str, Any]) -> str:
    if result.get("symbolic_only") or result.get("indirect_access_sites"):
        return (
            "No absolute address in the export is left unconfigured — but the symbolic "
            "names and indirect access listed below are not resolved, so this is not "
            "complete coverage."
        )
    return "Every absolute address in the export is configured."


def _configured_empty(result: dict[str, Any]) -> str:
    if not result["endpoint"]["configured_tag_count"]:
        return "No points are configured on this endpoint."
    comparable = result["endpoint"]["configured_tag_count"] - len(
        result.get("configured_not_comparable") or []
    )
    if not comparable:
        return "No configured point is a comparable address (see below)."
    if result.get("configured_not_comparable"):
        return (
            "Every comparable configured point is named in the export "
            "(the non-comparable ones are listed below)."
        )
    return "Every configured point is named in the export."


def _refused(result: dict[str, Any], lead: str) -> str:
    errors = "".join(f"<li>{escape(e)}</li>" for e in result.get("parse_errors") or [])
    body = f"<p><span class='badge'>Refused</span> {escape(result['refused'])}</p>"
    if errors:
        body += f"<ul class='notes'>{errors}</ul>"
    return section("Field cross-reference", lead + body + _notes(result["notes"]))


def field_section(result: dict[str, Any]) -> str:
    """The exact-address cross-reference against one endpoint."""
    endpoint = result["endpoint"]
    lead = (
        f"<p class='sub'>Endpoint <span class='mono'>{escape(endpoint['name'])}</span> "
        f"({escape(endpoint['protocol'])}, {escape(endpoint['configured_tag_count'])} "
        "configured points). Joined by exact address only — never by name.</p>"
    )
    if result.get("refused"):
        return _refused(result, lead)
    if not result["comparable"]:
        reason = result["unmatchable"]["reason"]
        body = f"<p><span class='badge'>Not comparable</span> {escape(reason)}</p>"
        return section("Field cross-reference", lead + body + _notes(result["notes"]))
    matched = rows_table(
        ["Address", "Program symbol", "Configured ref", "Label", "Role", "Match", "Lines"],
        [
            [
                r["address"],
                r.get("program_symbol"),
                r["configured_ref"],
                r["label"],
                r["role"],
                r["match"],
                _sites(r),
            ]
            for r in result["matched"]
        ],
        empty="No configured point shares an address with this export.",
    )
    in_export = rows_table(
        ["Address", "Symbol", "Note", "Lines"],
        [
            [r["address"], r.get("symbol"), r.get("note"), _sites(r)]
            for r in result["in_export_not_configured"]
        ],
        empty=_in_export_empty(result),
    )
    configured = rows_table(
        ["Configured ref", "Label", "Role"],
        [[r["configured_ref"], r["label"], r["role"]] for r in result["configured_not_in_export"]],
        empty=_configured_empty(result),
    )
    extra = []
    if result.get("configured_not_comparable"):
        extra.append(
            "<h3>Configured, not comparable</h3>"
            + rows_table(
                ["Configured ref", "Label", "Reason"],
                [
                    [r["configured_ref"], r["label"], r["reason"]]
                    for r in result["configured_not_comparable"]
                ],
                empty="",
            )
        )
    if result.get("overlaps"):
        extra.append(
            "<h3>Overlaps (same memory, different width — not matches)</h3>"
            + rows_table(
                ["Configured ref", "Program address"],
                [[r["configured_ref"], r["program_address"]] for r in result["overlaps"]],
                empty="",
            )
        )
    if result.get("indirect_access_sites"):
        extra.append(
            "<h3>Indirect access (address not resolvable from the export — "
            "listed, not guessed)</h3>"
            + rows_table(
                ["Block", "Line", "Source"],
                [
                    [r["block"], r["line"], r["source_line"]]
                    for r in result["indirect_access_sites"]
                ],
                empty="",
            )
        )
    if result.get("symbolic_only"):
        extra.append(
            "<h3>Symbolic only (address not in this export — never matched by name)</h3>"
            + rows_table(
                ["Symbol", "Sites"],
                [[r["symbol"], r["site_count"]] for r in result["symbolic_only"]],
                empty="",
            )
        )
    body = (
        lead
        + "<h3>Matched</h3>"
        + matched
        + "<h3>In the export, not configured</h3>"
        + in_export
        + "<h3>Configured, not named in this export</h3>"
        + configured
        + "".join(extra)
        + _notes(result["notes"])
    )
    return section("Field cross-reference", body)


__all__ = ["field_section", "rows_table", "section"]
