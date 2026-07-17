"""EtherNet/IP (Rockwell / Allen-Bradley CIP) operations — read-first.

Uses ``pycomm3`` — a **pure-Python** CIP / EtherNet/IP client (no native deps) —
so the venv installs cleanly everywhere. Three controller families are reachable,
selected by the target's ``plctype`` (config key or per-call override):

  * ``logix`` (default) — **ControlLogix / CompactLogix / GuardLogix** symbolic tag
    access: tags read/written by name (``Program:Main.Speed``,
    ``Conveyor[2].Running``) and the tag list discovered at runtime
    (``eip_list_tags``).
  * ``slc`` — **PLC-5 / SLC-500 / MicroLogix** via **PCCC** data-table addressing:
    ``N7:0`` (integer), ``B3:0/0`` (bit), ``F8:0`` (float), ``T4:0.ACC`` /
    ``C5:0.ACC`` (timer/counter), ``ST18:0`` (string). PCCC has no online symbol
    table, so ``eip_list_tags`` returns the data-file directory instead.
  * ``micro800`` — **Micro820/850/870** symbolic variables (LogixDriver variant,
    IP only, no chassis slot).

Real PLC-5 / SLC-500 / MicroLogix / Micro800 hardware behaviour is 待核实 — the
PCCC and Micro800 paths are exercised against mocked pycomm3 drivers only.

READ tools are non-destructive. ``eip_write_tag`` is an OT-DANGEROUS write — it
is governed (high risk_tier), captures the BEFORE value for undo, and must run
through dry-run + double-confirm. 未经授权勿对生产控制系统写入.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import replace
from typing import Any

from iaiops.connectors.eip.transport import _resolve_eip_kind
from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, eip_session

MAX_TAGS = 2000  # bounded tag-list / batch size (defensive against over-requests)

# Controller identity fields kept from a Logix get_plc_info() reply.
_LOGIX_INFO_KEYS = (
    "vendor",
    "product_type",
    "product_code",
    "version",
    "revision",
    "serial",
    "product_name",
    "keyswitch",
    "name",
    "programs",
    "tasks",
    "modules",
)


def _effective_target(target: Any, plctype: str | None) -> Any:
    """Return an immutable copy of ``target`` with an overridden ``plctype``.

    A blank/None ``plctype`` leaves the target unchanged so a config-level
    ``plctype:`` still applies; a non-blank value (``logix`` | ``slc`` |
    ``micro800`` and aliases) overrides the driver selector for this call only.
    Never mutates the passed target (frozen dataclass ``replace``).
    """
    if not plctype:
        return target
    return replace(target, plctype=str(plctype))


def _coerce(value: Any) -> Any:
    """Make a CIP value JSON-safe (scalars pass through; collections recurse)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value][:MAX_TAGS]
    if isinstance(value, dict):
        return {s(str(k), 64): _coerce(v) for k, v in list(value.items())[:MAX_TAGS]}
    return s(value, 256)


def _tag_result(t: Any) -> dict:
    """Normalize a pycomm3 ``Tag`` namedtuple to a JSON-safe descriptor."""
    error = getattr(t, "error", None)
    return {
        "tag": s(getattr(t, "tag", ""), 96),
        "value": _coerce(getattr(t, "value", None)),
        "type": s(getattr(t, "type", "") or "", 48),
        "error": s(error, 160) if error else "",
        "good": not error,
    }


def _collect_identity(plc: Any, kind: str) -> tuple[dict, str]:
    """Return ``(controller_fields, info_error)`` for the open driver of ``kind``.

    Logix / Micro800 expose the rich CIP identity via ``get_plc_info()``. SLC/PCCC
    (PLC-5 / SLC-500 / MicroLogix) has no such object; SLCDriver's DF1 diagnostic
    ``get_processor_type()`` returns the processor-type string instead.
    """
    try:
        if kind == "slc":
            proc = plc.get_processor_type()
            return ({"processor_type": s(proc, 64)} if proc else {}), ""
        info = dict(plc.get_plc_info() or {})
    except Exception as exc:  # noqa: BLE001 — some controllers restrict identity
        return {}, s(str(exc), 160)
    return {k: _coerce(info[k]) for k in _LOGIX_INFO_KEYS if k in info}, ""


def eip_controller_info(target: Any, plctype: str | None = None) -> dict:
    """[READ] Controller identity for the selected driver (Logix / SLC / Micro800)."""
    tgt = _effective_target(target, plctype)
    kind = _resolve_eip_kind(tgt.plctype)
    with eip_session(tgt) as plc:
        fields, info_error = _collect_identity(plc, kind)
    return {
        "endpoint": s(tgt.name, 64),
        "host": s(tgt.host, 64),
        "slot": tgt.slot,
        "plctype": kind,
        "controller": fields,
        "info_error": info_error,
    }


def _slc_file_directory(target: Any) -> dict:
    """PCCC analog to a Logix tag list: the SLC/PLC-5/MicroLogix data-file directory.

    PCCC has **no** online symbol table, so there is nothing to enumerate the way
    ``get_tag_list()`` does for Logix. SLCDriver's ``get_file_directory()`` instead
    reports which data files exist (N/B/F/T/C/…) and their element counts — i.e.
    what you then address as ``N7:0`` / ``B3:0/0`` / ``F8:0``. Real-device
    directory structure is 待核实 (pycomm3 marks some MicroLogix families untested).
    """
    directory: dict = {}
    dir_error = ""
    with eip_session(target) as plc:
        get_dir = getattr(plc, "get_file_directory", None)
        if callable(get_dir):
            try:
                # pycomm3's get_file_directory prints progress to stdout; capture it
                # so it can never corrupt an MCP stdio JSON-RPC stream.
                with contextlib.redirect_stdout(io.StringIO()):
                    directory = dict(get_dir() or {})
            except Exception as exc:  # noqa: BLE001 — some MicroLogix families unsupported
                dir_error = s(str(exc), 160)
        else:
            dir_error = "driver exposes no get_file_directory (not an SLC/PCCC session)"
    files = []
    for name, meta in list(directory.items())[:MAX_TAGS]:
        m = meta if isinstance(meta, dict) else {}
        files.append(
            {
                "file": s(str(name), 32),
                "elements": int(m.get("elements", 0) or 0),
                "length": int(m.get("length", 0) or 0),
            }
        )
    return {
        "endpoint": s(target.name, 64),
        "plctype": "slc",
        "file_count": len(files),
        "files": files,
        "directory_error": dir_error,
        "note": "PCCC has no online symbol table; this is the SLC/PLC-5/MicroLogix "
        "data-file directory (SLCDriver.get_file_directory). Address data tables "
        "directly with eip_read_tag/eip_read_many: N7:0 (int), B3:0/0 (bit), F8:0 "
        "(float), T4:0.ACC, C5:0.ACC, ST18:0 (string). Real-device structure 待核实.",
    }


def eip_list_tags(target: Any, plctype: str | None = None) -> dict:
    """[READ] Discover the controller's tags (Logix symbol table) or PCCC data files.

    For Logix/Micro800 the controller advertises its symbol table, so an agent can
    enumerate tags without prior knowledge. For an SLC/PCCC session there is no
    symbol table — the data-file directory is returned instead. Bounded at MAX_TAGS.
    """
    tgt = _effective_target(target, plctype)
    kind = _resolve_eip_kind(tgt.plctype)
    if kind == "slc":
        return _slc_file_directory(tgt)
    with eip_session(tgt) as plc:
        raw = plc.get_tag_list() or []
    tags: list[dict] = []
    for t in list(raw)[:MAX_TAGS]:
        if not isinstance(t, dict):
            continue
        data_type = t.get("data_type")
        # data_type is a str for atomics, a dict (template) for structures.
        is_struct = isinstance(data_type, dict)
        type_name = s(data_type.get("name", "STRUCT"), 64) if is_struct else s(str(data_type), 64)
        tags.append(
            {
                "name": s(t.get("tag_name", ""), 96),
                "data_type": type_name,
                "tag_type": s(t.get("tag_type", "atomic"), 16),
                "structure": is_struct,
                "dimensions": _coerce(t.get("dimensions", [])),
            }
        )
    return {
        "endpoint": s(tgt.name, 64),
        "plctype": kind,
        "tag_count": len(tags),
        "tags": tags,
        "note": "Controller-scoped tags. Program-scoped tags appear as "
        "'Program:<prog>.<tag>'. Truncated at the bounded cap if very large.",
    }


def eip_read_tag(target: Any, tag: str, plctype: str | None = None) -> dict:
    """[READ] Read one tag/address with its type.

    Logix: a symbolic tag or array element (``Conveyor.Speed``, ``Array[3]``).
    SLC/PCCC: a data-table address (``N7:0``, ``B3:0/0``, ``F8:0``, ``T4:0.ACC``);
    append ``{count}`` for a slice (``N7:0{10}``).
    """
    tgt = _effective_target(target, plctype)
    with eip_session(tgt) as plc:
        result = plc.read(tag)
    # pycomm3 returns a single Tag (a namedtuple) for one tag, a list for many.
    one = result[0] if isinstance(result, list) else result
    return {
        "endpoint": s(tgt.name, 64),
        "plctype": _resolve_eip_kind(tgt.plctype),
        **_tag_result(one),
    }


def eip_read_many(target: Any, tags: list[str], plctype: str | None = None) -> dict:
    """[READ] Batch-read many tags/addresses in one request.

    Logix batches auto multi-packets; SLC/PCCC reads each data-table address
    (``N7:0``, ``F8:0``, ``B3:0/0``, …). Micro800 does not support multi-request
    packets — pycomm3 splits the batch internally.
    """
    names = [str(t) for t in (tags or [])][:MAX_TAGS]
    tgt = _effective_target(target, plctype)
    kind = _resolve_eip_kind(tgt.plctype)
    if not names:
        return {
            "endpoint": s(tgt.name, 64),
            "plctype": kind,
            "items": [],
            "error": "No tags given.",
        }
    with eip_session(tgt) as plc:
        results = plc.read(*names)
    items = results if isinstance(results, list) else [results]
    return {
        "endpoint": s(tgt.name, 64),
        "plctype": kind,
        "count": len(items),
        "items": [_tag_result(t) for t in items],
    }


def eip_write_tag(
    target: Any, tag: str, value: Any, *, plctype: str | None = None, dry_run: bool = True
) -> dict:
    """[WRITE][HIGH RISK] Write one value to a tag/data-table address (off by default).

    OT-dangerous. Works for a Logix/Micro800 symbolic tag or an SLC/PCCC data-table
    address (``N7:0``, ``F8:0``, ``B3:0/0``). Captures the BEFORE value (read-back)
    so the write is reversible, and refuses to act unless ``dry_run`` is explicitly
    False. 未经授权勿对生产控制系统写入.
    """
    tgt = _effective_target(target, plctype)
    kind = _resolve_eip_kind(tgt.plctype)
    with eip_session(tgt) as plc:
        try:
            before_tag = plc.read(tag)
            before_one = before_tag[0] if isinstance(before_tag, list) else before_tag
            before = _coerce(getattr(before_one, "value", None))
            read_error = s(getattr(before_one, "error", "") or "", 160)
        except Exception as exc:  # noqa: BLE001 — record the read-back failure
            before = None
            read_error = s(str(exc), 160)
        if dry_run:
            return {
                "endpoint": s(tgt.name, 64),
                "plctype": kind,
                "tag": s(tag, 96),
                "dry_run": True,
                "before": before,
                "would_write": _coerce(value),
                "read_back_error": read_error,
                "note": "Dry run — nothing written. Re-run with dry_run=False AND a "
                "recorded approver to apply. 未经授权勿对生产控制系统写入.",
            }
        result = plc.write((tag, value))
        written_ok = not getattr(result, "error", None)
    return {
        "endpoint": s(tgt.name, 64),
        "plctype": kind,
        "tag": s(tag, 96),
        "dry_run": False,
        "before": before,
        "written": _coerce(value),
        "applied": bool(written_ok),
    }


__all__ = [
    "eip_controller_info",
    "eip_list_tags",
    "eip_read_tag",
    "eip_read_many",
    "eip_write_tag",
    "OTConnectionError",
]
