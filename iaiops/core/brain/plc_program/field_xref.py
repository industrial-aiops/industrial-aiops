"""Program ↔ configured field point cross-reference (READ-ONLY, exact address only).

The question a field engineer actually asks of a program export is "which of
these symbols is that point on the line?". This answers it the only way that
cannot be wrong in a plausible-looking way: a program operand and a configured
point are joined when **both name the same address in the same address space**.

Never by name. A configured label that reads like a program symbol, a ref that
is one character away from a tag, a symbol whose address sits in a tag table
that is not part of the export — none of these is a match (HLD D16: what a
point means is given by a person; a guessed mapping is the defect this product
exists to refuse). Where the program format and the endpoint's protocol share
no address space at all, the result says so and carries **no lists** — an empty
"configured but unused" list would itself be a claim.

Three lists and their scope:

* ``matched`` — same address on both sides, with the configured label + role
  (as a person declared them) and the program sites (file line / rung).
* ``in_export_not_configured`` — the export names it; the endpoint does not read it.
* ``configured_not_in_export`` — the endpoint reads it; THIS export never names it
  directly. Not "unused by the PLC": another block, a symbol, or indirect access
  can still reach it.

Pure: one exported file in, one endpoint description in, a dict out. No device
is touched (live values are a separate, opt-in step — ``field_live``).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: S405 — only for its ParseError type
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from iaiops.core.brain.plc_program import field_logix, field_scan
from iaiops.core.brain.plc_program.addresses import S7Address, parse_s7_config_ref
from iaiops.core.brain.plc_program.awl_parser import parse_awl
from iaiops.core.brain.plc_program.fingerprint import content_sha256
from iaiops.core.brain.plc_program.l5x_parser import parse_l5x
from iaiops.core.brain.plc_program.outline import load_program
from iaiops.core.brain.plc_program.st_parser import parse_st

MAX_SITES = 20
S7_SPACE = "s7_absolute"
LOGIX_SPACE = "logix_symbolic"

_EIP = ("ethernetip", "eip")
_DIFFERENT_VENDORS = (
    "Siemens S7 absolute addresses and Rockwell Logix tag paths are different "
    "vendors' address spaces; no translation between them exists, so none is attempted."
)
_ST_REASON = (
    "A generic IEC 61131-3 .st export is not assumed to be Siemens: direct addresses "
    "are numbered per vendor (CODESYS %MW10 is word 10 = bytes 20-21, S7 MW10 is byte "
    "10), so reading one as the other joins the wrong memory. If this is a TIA Portal "
    "SCL export, export it as .scl."
)
_PROTOCOL_REASONS = {
    "modbus": (
        "Modbus register numbers are assigned in the device's Modbus server mapping, "
        "which a program export does not contain — not comparable, no translation attempted."
    ),
    "opcua": (
        "OPC UA node ids are defined by the server's address space; even a server that "
        "mirrors PLC addresses in its node ids does so by server configuration this "
        "export does not contain — not comparable."
    ),
    "mqtt": (
        "MQTT topics and Sparkplug metric names are chosen by whatever publishes them; "
        "a program export holds no topic — not comparable."
    ),
}
_PLCTYPE_REASONS = {
    "slc": (
        "This endpoint reads a PLC-5 / SLC-500 / MicroLogix by PCCC data-table address "
        "(N7:0); an L5X is a Logix export with symbolic tags — not comparable."
    ),
    "micro800": (
        "A Micro800 program is a CCW project, not an L5X; its variables are not the "
        "tags in this file — not comparable."
    ),
}
_S7_NOTES = (
    "Symbols named only by name (quoted symbols, symbolic DB access) get their "
    "address from the PLC tag table / symbol table, which is not part of this export; "
    "they are listed under symbolic_only and never matched by name. Export the tag "
    "table with the program to compare them.",
    "Matching is exact: area, DB, byte, bit and width must all agree. Same memory at "
    "a different width is an overlap, not a match.",
)
_LOGIX_NOTES = (
    "A Logix tag path is the address the CIP connector reads by, so equal paths "
    "(case-insensitive, as Logix tag names are) are the same tag. A member or "
    "element (`Tag.ACC`, `Tag[2]`) joins its tag as member_of_tag.",
    "This join assumes the export is from this endpoint's controller — the file "
    "cannot prove that; program.controller names the controller the export came from, "
    "so check it against the endpoint. Common tag names (Start, Run) match on any "
    "controller that has them.",
    "An alias tag joins by its own name. I/O module tags (Local:1:I.Data) are not "
    "extracted by the L5X parser, so a configured alias TARGET can show as not in export.",
)
_S7_IDENTITY_NOTE = (
    "An AWL/SCL export does not name the CPU it came from: M and DB addresses exist on "
    "every S7 CPU, so a match is only meaningful if this export is from this endpoint's CPU."
)
_SCOPE_NOTE = (
    "configured_not_in_export means THIS export never names the address directly — "
    "not that the PLC does not use it (another block, a symbol or indirect access can)."
)


def _protocol(raw: str) -> str:
    text = str(raw or "").strip().lower()
    return "ethernetip" if text in _EIP else text


def eip_kind(plctype: str) -> str:
    """The EtherNet/IP driver kind a ``plctype`` selects (logix / slc / micro800)."""
    from iaiops.connectors.eip.transport import _resolve_eip_kind

    return _resolve_eip_kind(plctype)


def program_format(path: Path, fmt: str) -> str:
    """``scl`` only for a Siemens .scl file; other ST-sniffed text is generic ``st``."""
    if fmt == "scl" and path.suffix.lower() != ".scl":
        return "st"
    return fmt


def address_space(fmt: str, protocol: str, kind: str = "logix") -> tuple[str | None, str]:
    """(shared address space, "") or (None, why there is none) for one pair."""
    protocol = _protocol(protocol)
    if fmt == "st":
        return None, _ST_REASON
    if fmt in ("awl", "scl") and protocol == "s7":
        return S7_SPACE, ""
    if fmt == "l5x" and protocol == "ethernetip":
        if kind in _PLCTYPE_REASONS:
            return None, _PLCTYPE_REASONS[kind]
        return LOGIX_SPACE, ""
    if protocol in ("s7", "ethernetip"):
        return None, _DIFFERENT_VENDORS
    if protocol in _PROTOCOL_REASONS:
        return None, _PROTOCOL_REASONS[protocol]
    return None, (
        f"no parser here reads a program export for {protocol or 'this'} devices, so a "
        f"{fmt} export shares no address space with this endpoint — not comparable."
    )


def comparability_table() -> list[dict[str, Any]]:
    """Every program-format × endpoint-protocol pair, with its verdict."""
    pairs = [("s7", "logix"), ("ethernetip", "logix"), ("ethernetip", "slc")]
    pairs += [("ethernetip", "micro800"), ("modbus", ""), ("opcua", ""), ("mqtt", "")]
    pairs += [("mc", ""), ("fins", "")]
    rows = []
    for fmt in ("awl", "scl", "st", "l5x"):
        for protocol, kind in pairs:
            space, reason = address_space(fmt, protocol, kind or "logix")
            rows.append(
                {
                    "program_format": fmt,
                    "protocol": protocol + (f" ({kind})" if protocol == "ethernetip" else ""),
                    "comparable": space is not None,
                    "address_space": space,
                    "reason": reason,
                }
            )
    return rows


def _tag_row(tag: Any) -> dict[str, Any]:
    return {
        "configured_ref": str(tag.ref),
        "label": str(getattr(tag, "label", "") or ""),
        "role": str(getattr(tag, "role", "") or ""),
    }


def _sites(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    return {"sites": rows[:MAX_SITES], "site_count": len(rows)}


# ─── S7 ──────────────────────────────────────────────────────────────────────


def _s7_join(scan: field_scan.S7Scan, tags: Iterable[Any]) -> dict[str, Any]:
    by_address: dict[S7Address, list[field_scan.AddressSite]] = {}
    for site in scan.addresses:
        by_address.setdefault(site.address, []).append(site)

    matched, not_in_export, not_comparable, overlaps = [], [], [], []
    used: set[S7Address] = set()
    for tag in tags:
        address = parse_s7_config_ref(tag.ref)
        if address is None:
            not_comparable.append(
                {**_tag_row(tag), "reason": "not a fixed-width S7 address (string or unparseable)"}
            )
            continue
        sites = by_address.get(address)
        if sites:
            used.add(address)
            matched.append(
                {
                    "address": address.text,
                    "program_symbol": None,  # an absolute operand carries no symbol in the export
                    **_tag_row(tag),
                    "match": "exact_address",
                    **_sites(_site_dict(s) for s in sites),
                }
            )
        else:
            not_in_export.append(_tag_row(tag))
        for program_address in by_address:
            if address.overlaps(program_address):
                overlaps.append(
                    {
                        **_tag_row(tag),
                        "configured_address": address.text,
                        "program_address": program_address.text,
                        "note": "same memory, different width or bit — not a match",
                    }
                )

    in_export = [
        {
            "address": address.text,
            "symbol": None,
            "note": _unreadable_note(address),
            **_sites(_site_dict(s) for s in sites),
        }
        for address, sites in by_address.items()
        if address not in used
    ]
    return {
        "matched": matched,
        "in_export_not_configured": in_export,
        "configured_not_in_export": not_in_export,
        "configured_not_comparable": not_comparable,
        "overlaps": overlaps,
        "symbolic_only": _symbolic(scan.symbols),
        "indirect_access_sites": [
            {"block": b, "line": n, "source_line": q} for b, n, q in scan.indirect
        ][:MAX_SITES],
    }


def _site_dict(site: field_scan.AddressSite) -> dict[str, Any]:
    return {
        "access": site.access,
        "block": site.block,
        "line": site.line,
        "source_line": site.source_line,
    }


def _unreadable_note(address: S7Address) -> str:
    if address.area in ("T", "C"):
        return "timer/counter — the S7 connector cannot read this area"
    if address.area in ("PI", "PQ"):
        return "peripheral access — the S7 connector reads the process image, not this"
    return ""


def _symbolic(symbols: Iterable[field_scan.SymbolSite]) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        row = counts.setdefault(sym.symbol, {"symbol": sym.symbol, "site_count": 0, "lines": []})
        row["site_count"] += 1
        if len(row["lines"]) < MAX_SITES:
            row["lines"].append(sym.line)
    return list(counts.values())


# ─── Logix ───────────────────────────────────────────────────────────────────


def _logix_join(text: str, source_file: str, outline: Any, tags: Iterable[Any]) -> dict:
    declared = {t.key: t for t in field_logix.logix_tags(outline)}
    local_names: dict[str, set[str]] = {}
    for t in declared.values():
        if t.program:
            local_names.setdefault(t.name.casefold(), set()).add(t.program)
    index = field_logix.site_index(text, source_file)

    matched, not_in_export, used = [], [], set()
    for tag in tags:
        key, whole = field_logix.logix_ref_key(tag.ref)
        found = declared.get(key)
        if found is None:
            not_in_export.append(_tag_row(tag))
            continue
        used.add(key)
        shadow = local_names.get(found.name.casefold(), set())
        matched.append(
            {
                "address": found.path,
                "program_symbol": found.name,
                "data_type": found.data_type,
                **_tag_row(tag),
                "match": "exact_address" if whole else "member_of_tag",
                # A site belongs to the whole tag, not to the configured element.
                "sites_scope": "tag" if whole else "whole_tag",
                **_sites(field_logix.sites_for(found, index, shadow)),
            }
        )
    in_export = [
        {"address": t.path, "symbol": t.name, "data_type": t.data_type, "note": ""}
        for k, t in declared.items()
        if k not in used
    ]
    return {
        "matched": matched,
        "in_export_not_configured": in_export,
        "configured_not_in_export": not_in_export,
        "configured_not_comparable": [],
        "overlaps": [],
        "symbolic_only": [],
        "indirect_access_sites": [],
    }


# ─── entry point ─────────────────────────────────────────────────────────────

_LIST_KEYS = (
    "matched",
    "in_export_not_configured",
    "configured_not_in_export",
    "configured_not_comparable",
    "overlaps",
    "symbolic_only",
    "indirect_access_sites",
)


def xref_program_endpoint(path: str, target: Any) -> dict[str, Any]:
    """Join one exported program with one configured endpoint by exact address.

    ``target`` needs ``name``, ``protocol``, ``plctype`` and ``tags`` (refs +
    the labels/roles a person declared) — a ``TargetConfig`` or anything shaped
    like one. Raises ``ValueError`` only for an unreadable path.
    """
    resolved, text, fmt = load_program(path)
    fmt = program_format(resolved, fmt)
    protocol = _protocol(getattr(target, "protocol", ""))
    kind = eip_kind(getattr(target, "plctype", "")) if protocol == "ethernetip" else ""
    space, reason = address_space(fmt, protocol, kind or "logix")
    tags = tuple(getattr(target, "tags", ()) or ())
    head = {
        "program": {
            "source_file": str(resolved),
            "format": fmt,
            "content_sha256": content_sha256(text),
        },
        "endpoint": {
            "name": str(getattr(target, "name", "")),
            "protocol": protocol,
            **({"plctype": kind} if kind else {}),
            "configured_tag_count": len(tags),
        },
        "comparable": space is not None,
        "address_space": space,
    }
    if space is None:
        return _without_lists(
            head,
            unmatchable={"program_format": fmt, "protocol": protocol, "reason": reason},
            note="No lists are given: with no shared address space, 'configured but not "
            "in the program' would be a claim this comparison cannot make.",
        )
    if space == S7_SPACE:
        return _s7_result(head, fmt, text, tags)
    return _logix_result(head, text, str(resolved), tags)


def _without_lists(
    head: dict[str, Any], *, note: str, unmatchable: dict | None = None, refused: str = ""
) -> dict[str, Any]:
    return {
        **head,
        "unmatchable": unmatchable,
        "refused": refused or None,
        **dict.fromkeys(_LIST_KEYS),
        "notes": [note],
    }


def _refuse(head: dict[str, Any], why: str, parse_errors: tuple[str, ...] = ()) -> dict:
    result = _without_lists(
        head,
        refused=why,
        note="Refused rather than answered: every configured point would otherwise read "
        "as 'not in the export' for a file that was never read.",
    )
    return {**result, "parse_errors": list(parse_errors)}


def _s7_result(head: dict[str, Any], fmt: str, text: str, tags: tuple) -> dict[str, Any]:
    if not text.strip():
        return _refuse(head, "the export is empty")
    outline = (parse_awl if fmt == "awl" else parse_st)(text, head["program"]["source_file"])
    if not outline.blocks:
        why = "no program block (OB/FB/FC/DB) was found — this is not a readable export"
        return _refuse(head, why, outline.parse_errors)
    scan = field_scan.scan_awl(text) if fmt == "awl" else field_scan.scan_scl(text)
    body = _s7_join(scan, tags)
    notes = [*_S7_NOTES, _SCOPE_NOTE, _S7_IDENTITY_NOTE]
    if not scan.addresses:
        notes.insert(
            0,
            "This export names no absolute address — its code is symbolic, so nothing "
            "can be joined; the configured points are not shown to be unused.",
        )
    if scan.indirect:
        notes.append(
            f"{len(scan.indirect)} indirect access site(s) (pointer, AR register, "
            "DB-relative operand) touch addresses this extraction cannot resolve — "
            "listed, not guessed."
        )
    return {
        **head,
        "unmatchable": None,
        "refused": None,
        **body,
        "parse_errors": list(outline.parse_errors),
        "notes": notes,
        **_counts(body),
    }


def _logix_result(head: dict[str, Any], text: str, source_file: str, tags: tuple) -> dict:
    outline = parse_l5x(text, source_file)
    if outline.parse_errors and not outline.blocks:
        return _refuse(head, "the L5X could not be parsed", outline.parse_errors)
    if not field_logix.logix_tags(outline):
        return _refuse(head, "the L5X declares no tags", outline.parse_errors)
    try:
        body = _logix_join(text, source_file, outline, tags)
    except (ValueError, ET.ParseError) as exc:
        return _refuse(head, f"the L5X rungs could not be read ({exc})", outline.parse_errors)
    controller = field_logix.controller_identity(text)
    program = {**head["program"], "controller": controller}
    return {
        **head,
        "program": program,
        "unmatchable": None,
        "refused": None,
        **body,
        "parse_errors": list(outline.parse_errors),
        "notes": [*_LOGIX_NOTES, _SCOPE_NOTE],
        **_counts(body),
    }


def _counts(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "counts": {
            key: len(body[key])
            for key in ("matched", "in_export_not_configured", "configured_not_in_export")
        }
    }


__all__ = [
    "LOGIX_SPACE",
    "MAX_SITES",
    "S7_SPACE",
    "address_space",
    "comparability_table",
    "eip_kind",
    "program_format",
    "xref_program_endpoint",
]
