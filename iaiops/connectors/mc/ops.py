"""Mitsubishi MC protocol operations (三菱 Q/L/iQ-R/iQ-L, read-first).

Uses ``pymcprotocol`` — a **pure-Python** MELSEC Communication (MC) 3E-frame
client (binary), so the venv installs with no native dependency. Devices are
addressed MELSEC-style: ``D`` (data register), ``M`` (internal relay), ``X``/``Y``
(I/O), ``W`` (link register), etc. Only the 3E frame is implemented by the
library (1E/4E are not supported here).

READ tools are non-destructive. ``mc_write_words`` is an OT-DANGEROUS write: it
is governed (high risk_tier), captures the BEFORE values for undo, and must run
through dry-run + double-confirm. 未经授权勿对生产控制系统写入.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, mc_session

MAX_POINTS = 256  # bounded batch size (defensive against agent over-requests)


def _clamp(count: int) -> int:
    return max(1, min(int(count), MAX_POINTS))


def mc_cpu_status(target: Any) -> dict:
    """[READ] MELSEC CPU type/code identity (proves the MC link is alive)."""
    with mc_session(target) as client:
        cputype, cpucode = client.read_cputype()
    return {
        "endpoint": s(target.name, 64),
        "plctype": s(target.plctype, 16),
        "cpu_type": s(cputype, 64),
        "cpu_code": s(cpucode, 16),
    }


def mc_read_words(target: Any, headdevice: str, count: int = 1) -> dict:
    """[READ] Batch-read ``count`` 16-bit word devices from ``headdevice`` (e.g. D100)."""
    count = _clamp(count)
    with mc_session(target) as client:
        values = client.batchread_wordunits(headdevice=headdevice, readsize=count)
    return {
        "endpoint": s(target.name, 64),
        "headdevice": s(headdevice, 32),
        "count": count,
        "words": [int(v) for v in list(values)[:count]],
    }


def mc_read_bits(target: Any, headdevice: str, count: int = 1) -> dict:
    """[READ] Batch-read ``count`` bit devices from ``headdevice`` (e.g. M0, X10)."""
    count = _clamp(count)
    with mc_session(target) as client:
        values = client.batchread_bitunits(headdevice=headdevice, readsize=count)
    return {
        "endpoint": s(target.name, 64),
        "headdevice": s(headdevice, 32),
        "count": count,
        "bits": [bool(v) for v in list(values)[:count]],
    }


def mc_read_many(
    target: Any, word_devices: list[str] | None = None, dword_devices: list[str] | None = None
) -> dict:
    """[READ] Random-read scattered word + dword devices in one MC request."""
    words = [str(d) for d in (word_devices or [])][:MAX_POINTS]
    dwords = [str(d) for d in (dword_devices or [])][:MAX_POINTS]
    if not words and not dwords:
        return {"endpoint": s(target.name, 64), "error": "No devices given."}
    with mc_session(target) as client:
        wvals, dvals = client.randomread(word_devices=words, dword_devices=dwords)
    return {
        "endpoint": s(target.name, 64),
        "words": [
            {"device": s(d, 32), "value": int(v)} for d, v in zip(words, list(wvals), strict=False)
        ],
        "dwords": [
            {"device": s(d, 32), "value": int(v)} for d, v in zip(dwords, list(dvals), strict=False)
        ],
    }


def mc_write_words(
    target: Any, headdevice: str, values: list[int], *, dry_run: bool = True
) -> dict:
    """[WRITE][HIGH RISK] Write 16-bit words starting at ``headdevice``.

    OT-dangerous. Captures the BEFORE values (read-back of the same range) so the
    write is reversible, and refuses to act unless ``dry_run`` is explicitly
    False. 未经授权勿对生产控制系统写入.
    """
    vals = [int(v) for v in (values or [])][:MAX_POINTS]
    if not vals:
        return {"endpoint": s(target.name, 64), "error": "No values to write."}
    with mc_session(target) as client:
        try:
            before = [
                int(v)
                for v in client.batchread_wordunits(headdevice=headdevice, readsize=len(vals))
            ]
            read_error = ""
        except Exception as exc:  # noqa: BLE001 — record the read-back failure
            before = []
            read_error = s(str(exc), 160)
        if dry_run:
            return {
                "endpoint": s(target.name, 64),
                "headdevice": s(headdevice, 32),
                "dry_run": True,
                "before": before,
                "would_write": vals,
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        client.batchwrite_wordunits(headdevice=headdevice, values=vals)
    return {
        "endpoint": s(target.name, 64),
        "headdevice": s(headdevice, 32),
        "dry_run": False,
        "before": before,
        "written": vals,
        "applied": True,
    }


def mc_cclink_templates() -> dict:
    """[READ] List the built-in CC-Link refresh-image templates (pure, no device)."""
    from iaiops.connectors.mc import cclink

    return {"templates": cclink.list_link_templates()}


def mc_cclink_link_read(
    target: Any, template: str, overrides: dict[str, str] | None = None
) -> dict:
    """[READ] Read a CC-Link refresh image (RX/RY/RWr/RWw) through the master PLC.

    ``overrides`` remaps a template area's head device (and optionally count) as
    ``{"rx": "X1200"}`` or ``{"rwr": "W200:8"}`` — the refresh assignment is per-project
    configuration, so the template is a documented starting point (待核实 per site).
    """
    from iaiops.connectors.mc import cclink

    tpl = cclink.get_link_template(template)
    ovr = {str(k).strip().lower(): str(v) for k, v in (overrides or {}).items()}
    unknown = set(ovr) - {a.name for a in tpl.areas}
    if unknown:
        raise ValueError(
            f"Unknown override area(s) {sorted(unknown)}; template areas: "
            f"{[a.name for a in tpl.areas]}."
        )
    areas_out: list[dict[str, Any]] = []
    with mc_session(target) as client:
        for area in tpl.areas:
            resolved = cclink.resolve_area(area, ovr.get(area.name))
            count = _clamp(resolved.count)
            if resolved.kind == "bit":
                values = client.batchread_bitunits(headdevice=resolved.device, readsize=count)
                payload: Any = [bool(v) for v in list(values)[:count]]
            else:
                values = client.batchread_wordunits(headdevice=resolved.device, readsize=count)
                payload = [int(v) for v in list(values)[:count]]
            areas_out.append(
                {
                    "area": resolved.name,
                    "device": s(resolved.device, 32),
                    "kind": resolved.kind,
                    "count": count,
                    "label": s(resolved.label, 80),
                    "values": payload,
                }
            )
    return {
        "endpoint": s(target.name, 64),
        "template": s(tpl.name, 48),
        "network": s(tpl.network, 24),
        "areas": areas_out,
        "caveat": s(tpl.caveat, 240),
    }


def mc_cclink_network_health(
    target: Any, network: str = "cclink_ie_field", stations: int = 16
) -> dict:
    """[READ] Per-station CC-Link data-link health from the master's SB/SW registers.

    Reads the network's link special registers (classic: SW0080–; IE Field: SB0049 +
    SW00B0– + SW00A0– baton pass) and decodes one row per station — RCA evidence with
    zero network membership.
    """
    from iaiops.connectors.mc import cclink

    diag = cclink.get_network_diag(network)
    stations = max(1, min(int(stations), diag.max_stations))
    words_needed = (stations + 15) // 16
    with mc_session(target) as client:
        status_words = [
            int(v)
            for v in client.batchread_wordunits(
                headdevice=diag.stations_status_base, readsize=words_needed
            )
        ]
        own_error: bool | None = None
        if diag.own_error_bit:
            bits = client.batchread_bitunits(headdevice=diag.own_error_bit, readsize=1)
            own_error = bool(list(bits)[0]) if list(bits) else None
        baton_words: list[int] = []
        if diag.baton_pass_base:
            baton_words = [
                int(v)
                for v in client.batchread_wordunits(
                    headdevice=diag.baton_pass_base, readsize=words_needed
                )
            ]
    station_rows = cclink.decode_station_bitmap(status_words, stations)
    in_error = [r["station"] for r in station_rows if not r["ok"]]
    baton_lost = (
        [r["station"] for r in cclink.decode_station_bitmap(baton_words, stations) if not r["ok"]]
        if baton_words
        else []
    )
    return {
        "endpoint": s(target.name, 64),
        "network": s(diag.network, 24),
        "stations_checked": stations,
        "own_station_error": own_error,
        "stations": station_rows,
        "stations_in_error": in_error,
        "baton_pass_lost": baton_lost,
        "healthy": not in_error and not baton_lost and not own_error,
        "registers": {
            "stations_status": s(diag.stations_status_base, 16),
            "own_error": s(diag.own_error_bit, 16),
            "baton_pass": s(diag.baton_pass_base, 16),
        },
        "source": s(diag.source, 240),
    }


__all__ = [
    "mc_cpu_status",
    "mc_read_words",
    "mc_read_bits",
    "mc_read_many",
    "mc_write_words",
    "mc_cclink_templates",
    "mc_cclink_link_read",
    "mc_cclink_network_health",
    "OTConnectionError",
]
