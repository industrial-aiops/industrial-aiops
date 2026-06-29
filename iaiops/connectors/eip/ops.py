"""EtherNet/IP (Rockwell / Allen-Bradley CIP) operations — read-first.

Uses ``pycomm3`` — a **pure-Python** CIP / EtherNet/IP client (no native deps) —
so the venv installs cleanly everywhere. Targets the Logix tag model:
**ControlLogix / CompactLogix** (and GuardLogix) controllers reached over CIP.
The headline capability is *symbolic tag access*: tags are read/written by name
(``Program:Main.Speed``, ``Conveyor[2].Running``), and the controller's tag list
can be discovered at runtime (``eip_list_tags``).

PLC-5 / SLC-500 (PCCC) and Micro800 are **not** covered by these tools — Logix
tag access only (PCCC is a roadmap item).

READ tools are non-destructive. ``eip_write_tag`` is an OT-DANGEROUS write — it
is governed (high risk_tier), captures the BEFORE value for undo, and must run
through dry-run + double-confirm. 未经授权勿对生产控制系统写入.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTConnectionError, eip_session

MAX_TAGS = 2000  # bounded tag-list / batch size (defensive against over-requests)


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


def eip_controller_info(target: Any) -> dict:
    """[READ] Logix controller identity: name, product type/code, revision, serial."""
    with eip_session(target) as plc:
        try:
            info = dict(plc.get_plc_info() or {})
        except Exception as exc:  # noqa: BLE001 — some controllers restrict identity
            info = {}
            info_error = s(str(exc), 160)
        else:
            info_error = ""
    keep = (
        "vendor", "product_type", "product_code", "version", "revision",
        "serial", "product_name", "keyswitch", "name", "programs",
        "tasks", "modules",
    )
    fields = {k: _coerce(info[k]) for k in keep if k in info}
    return {
        "endpoint": s(target.name, 64),
        "host": s(target.host, 64),
        "slot": target.slot,
        "controller": fields,
        "info_error": info_error,
    }


def eip_list_tags(target: Any) -> dict:
    """[READ] Discover the controller-scoped tag list (names, types, structures).

    The headline pycomm3 feature: the controller advertises its symbol table, so
    an agent can enumerate tags without prior knowledge. Bounded at MAX_TAGS.
    """
    with eip_session(target) as plc:
        raw = plc.get_tag_list() or []
    tags: list[dict] = []
    for t in list(raw)[:MAX_TAGS]:
        if not isinstance(t, dict):
            continue
        data_type = t.get("data_type")
        # data_type is a str for atomics, a dict (template) for structures.
        is_struct = isinstance(data_type, dict)
        type_name = (
            s(data_type.get("name", "STRUCT"), 64) if is_struct else s(str(data_type), 64)
        )
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
        "endpoint": s(target.name, 64),
        "tag_count": len(tags),
        "tags": tags,
        "note": "Controller-scoped tags. Program-scoped tags appear as "
        "'Program:<prog>.<tag>'. Truncated at the bounded cap if very large.",
    }


def eip_read_tag(target: Any, tag: str) -> dict:
    """[READ] Read one tag (or array element, e.g. ``Array[3]``) with its type."""
    with eip_session(target) as plc:
        result = plc.read(tag)
    # pycomm3 returns a single Tag (a namedtuple) for one tag, a list for many.
    one = result[0] if isinstance(result, list) else result
    return {"endpoint": s(target.name, 64), **_tag_result(one)}


def eip_read_many(target: Any, tags: list[str]) -> dict:
    """[READ] Batch-read many tags in one request (pycomm3 auto multi-packets)."""
    names = [str(t) for t in (tags or [])][:MAX_TAGS]
    if not names:
        return {"endpoint": s(target.name, 64), "items": [], "error": "No tags given."}
    with eip_session(target) as plc:
        results = plc.read(*names)
    items = results if isinstance(results, list) else [results]
    return {
        "endpoint": s(target.name, 64),
        "count": len(items),
        "items": [_tag_result(t) for t in items],
    }


def eip_write_tag(target: Any, tag: str, value: Any, *, dry_run: bool = True) -> dict:
    """[WRITE][HIGH RISK] Write one value to a Logix tag (off by default).

    OT-dangerous. Captures the BEFORE value (read-back) so the write is
    reversible, and refuses to act unless ``dry_run`` is explicitly False.
    未经授权勿对生产控制系统写入.
    """
    with eip_session(target) as plc:
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
                "endpoint": s(target.name, 64),
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
        "endpoint": s(target.name, 64),
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
