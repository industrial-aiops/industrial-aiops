"""CC-Link family reads *through the master PLC* — pure data + decode (no device I/O).

Feasibility + route: ``docs/CCLINK.md``. iaiops does NOT join a CC-Link network (master
cards / ASICs / device roles are hardware- and cert-gated, write-side). Instead everything
the network carries is already mirrored into the Mitsubishi master's address space, readable
over the existing SLMP/MC 3E link:

* **link devices** — RX/RY/RWr/RWw are refreshed into PLC devices (B/W/X/Y…) by the
  project's *refresh parameters* → the templates below are documented DEFAULT layouts,
  ``待核实`` per project (same discipline as the Modbus vendor templates);
* **network health** — link special registers expose per-station data-link status:
  classic CC-Link ``SW0080–0083`` (QJ61BT11N master/local manual), CC-Link IE Field
  ``SB0049`` (own-station error) + ``SW00B0–B7`` (per-station) + ``SW00A0–A7`` (baton
  pass). Bit semantics: 0 = normal, 1 = error/lost.

Pure functions only — the MC session I/O lives in ``ops.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_STATION_WORDS = 8  # SW00B0–B7 / SW0080–0083 style bitmaps never exceed 8 words


@dataclass(frozen=True)
class LinkArea:
    """One refreshed link-device area (head device is the PLC-side refresh image)."""

    name: str  # rx | ry | rwr | rww
    device: str  # PLC-side head device, e.g. "X1000", "B0", "W0"
    kind: str  # bit | word
    count: int
    label: str = ""


@dataclass(frozen=True)
class LinkTemplate:
    """A named default refresh layout for a CC-Link family network."""

    name: str
    network: str  # cclink | cclink_ie_field
    description: str
    areas: tuple[LinkArea, ...]
    caveat: str = ""


_TEMPLATES: dict[str, LinkTemplate] = {
    # Classic CC-Link master (e.g. QJ61BT11N): a very common GX Works refresh assignment —
    # remote inputs/outputs into the X/Y image, link registers into W. Per-station sizing is
    # RX/RY 32 bits + RWr/RWw 4 words; the defaults below cover 4 stations.
    "cclink_classic_default": LinkTemplate(
        name="cclink_classic_default",
        network="cclink",
        description="Classic CC-Link master refresh image — common X/Y/W assignment "
        "(RX→X1000, RY→Y1000, RWr→W0, RWw→W100), sized for 4 stations.",
        caveat="待核实 — the refresh assignment is set per project in the master parameters "
        "(GX Works); confirm the actual RX/RY/RWr/RWw device ranges against the project "
        "before trusting the mapping.",
        areas=(
            LinkArea("rx", "X1000", "bit", 128, "Remote inputs RX (32 bits/station)"),
            LinkArea("ry", "Y1000", "bit", 128, "Remote outputs RY (32 bits/station)"),
            LinkArea("rwr", "W0", "word", 16, "Remote registers RWr (4 words/station)"),
            LinkArea("rww", "W100", "word", 16, "Remote registers RWw (4 words/station)"),
        ),
    ),
    # CC-Link IE Field master: a common training-manual style B/W assignment.
    "cclink_ie_field_default": LinkTemplate(
        name="cclink_ie_field_default",
        network="cclink_ie_field",
        description="CC-Link IE Field master refresh image — common B/W assignment "
        "(RX→B0, RY→B1000, RWr→W0, RWw→W1000).",
        caveat="待核实 — IE Field refresh parameters are engineering-configured; confirm "
        "the actual link-device ↔ B/W ranges against the project's network parameters.",
        areas=(
            LinkArea("rx", "B0", "bit", 128, "Remote inputs RX refresh image"),
            LinkArea("ry", "B1000", "bit", 128, "Remote outputs RY refresh image"),
            LinkArea("rwr", "W0", "word", 32, "Remote registers RWr refresh image"),
            LinkArea("rww", "W1000", "word", 32, "Remote registers RWw refresh image"),
        ),
    ),
}


@dataclass(frozen=True)
class NetworkDiag:
    """Where a CC-Link family master exposes its network health (SB/SW map)."""

    network: str
    description: str
    stations_status_base: str  # SW bitmap: bit 0 = normal, 1 = data-link error
    max_stations: int
    own_error_bit: str = ""  # SB own-station data-link error (empty = not defined here)
    baton_pass_base: str = ""  # SW bitmap: baton pass status (IE Field)
    source: str = ""


_NETWORKS: dict[str, NetworkDiag] = {
    "cclink": NetworkDiag(
        network="cclink",
        description="Classic CC-Link (master/local module, e.g. QJ61BT11N)",
        stations_status_base="SW0080",
        max_stations=64,
        source="QJ61BT11N master/local manual — SW0080–0083: each station's data-link "
        "status, one bit per station (0=normal, 1=error).",
    ),
    "cclink_ie_field": NetworkDiag(
        network="cclink_ie_field",
        description="CC-Link IE Field master station",
        stations_status_base="SW00B0",
        max_stations=120,
        own_error_bit="SB0049",
        baton_pass_base="SW00A0",
        source="CC-Link IE Field manuals — SB0049: own-station data-link error; "
        "SW00B0–B7: each station's data-link status; SW00A0–A7: baton-pass status "
        "(0=normal, 1=error/lost).",
    ),
}


def list_link_templates() -> list[dict[str, Any]]:
    """Summaries of the built-in CC-Link refresh templates (pure)."""
    return [
        {
            "name": t.name,
            "network": t.network,
            "description": t.description,
            "areas": [
                {
                    "name": a.name,
                    "device": a.device,
                    "kind": a.kind,
                    "count": a.count,
                    "label": a.label,
                }
                for a in t.areas
            ],
            "caveat": t.caveat,
        }
        for t in _TEMPLATES.values()
    ]


def get_link_template(name: str) -> LinkTemplate:
    """Return a template by name, or raise ``KeyError`` naming the known ones."""
    try:
        return _TEMPLATES[name]
    except KeyError:
        known = ", ".join(_TEMPLATES) or "(none)"
        raise KeyError(f"Unknown CC-Link template {name!r}. Available: {known}.") from None


def get_network_diag(network: str) -> NetworkDiag:
    """Return the SB/SW diagnostics map for ``network``, or raise ``KeyError``."""
    try:
        return _NETWORKS[(network or "").strip().lower()]
    except KeyError:
        known = ", ".join(_NETWORKS)
        raise KeyError(f"Unknown CC-Link network {network!r}. Available: {known}.") from None


def resolve_area(area: LinkArea, override: str | None) -> LinkArea:
    """Apply a ``"HEAD"`` or ``"HEAD:COUNT"`` override to a template area (pure).

    Returns a NEW ``LinkArea`` (immutability rule) with the overridden head device
    and/or count; the count stays within 1..1024.
    """
    if not override:
        return area
    head, _, count_s = str(override).partition(":")
    head = head.strip() or area.device
    count = area.count
    if count_s.strip():
        try:
            count = int(count_s)
        except ValueError:
            raise ValueError(
                f"Bad override {override!r} for area {area.name!r} — use 'HEAD' or 'HEAD:COUNT'."
            ) from None
    count = max(1, min(count, 1024))
    return LinkArea(name=area.name, device=head, kind=area.kind, count=count, label=area.label)


def decode_station_bitmap(words: list[int], stations: int) -> list[dict[str, Any]]:
    """Decode an SW status bitmap into per-station rows (pure).

    Station *n* (1-based) is bit ``(n-1) % 16`` of word ``(n-1) // 16``; bit value
    0 = normal, 1 = error/lost — the SW0080/SW00B0/SW00A0 convention.
    """
    stations = max(1, min(int(stations), 16 * MAX_STATION_WORDS))
    rows: list[dict[str, Any]] = []
    for n in range(1, stations + 1):
        word_idx, bit_idx = (n - 1) // 16, (n - 1) % 16
        word = int(words[word_idx]) if word_idx < len(words) else 0
        rows.append({"station": n, "ok": not (word >> bit_idx) & 1})
    return rows


__all__ = [
    "LinkArea",
    "LinkTemplate",
    "NetworkDiag",
    "MAX_STATION_WORDS",
    "list_link_templates",
    "get_link_template",
    "get_network_diag",
    "resolve_area",
    "decode_station_bitmap",
]
