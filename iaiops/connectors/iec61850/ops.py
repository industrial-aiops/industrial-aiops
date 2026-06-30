"""IEC 61850 MMS operations — read-only model browse + read (``iec61850`` extra).

IEC 61850 is the substation-automation standard; its MMS mapping lets a client
browse the device's data model (logical devices → logical nodes → data objects)
and read data attributes by object-reference + functional constraint (FC). This
connector is **read-only**: device directory, model browse, and attribute read.
Control (Oper / select-before-operate) is OT-dangerous and NOT exposed here.

All libiec61850 calls are isolated in ``iaiops.connectors.iec61850.driver``
(待核实 — unverified against a live IED). The ops use the adapter's uniform
interface and are mock-testable.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import num, s
from iaiops.core.runtime.connection import OTConnectionError, iec61850_session

MAX_NODES = 2000


def iec61850_device_directory(target: Any, include_children: bool = False) -> dict:
    """[READ] Connect and list the IED's logical devices (optionally their children).

    With ``include_children`` each logical device's immediate model children
    (logical nodes / data objects) are browsed too — a one-level model map.
    """
    with iec61850_session(target) as adapter:
        lds = list(adapter.get_logical_devices() or [])[:MAX_NODES]
        devices = []
        for ld in lds:
            row: dict[str, Any] = {"logical_device": s(ld, 128)}
            if include_children:
                children = list(adapter.get_data_directory(ld) or [])[:MAX_NODES]
                row["children"] = [s(c, 128) for c in children]
                row["child_count"] = len(children)
            devices.append(row)
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "logical_device_count": len(devices),
        "logical_devices": devices,
        "note": "IEC 61850 MMS model (read-only). Control blocks are not exposed.",
    }


def iec61850_browse(target: Any, reference: str) -> dict:
    """[READ] Browse the immediate model children under a reference (LD/LN/DO)."""
    ref = str(reference or "").strip()
    if not ref:
        return {"error": "reference is required (e.g. 'IED1LD0' or 'IED1LD0/LLN0')."}
    with iec61850_session(target) as adapter:
        children = list(adapter.get_data_directory(ref) or [])[:MAX_NODES]
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "reference": s(ref, 200),
        "child_count": len(children),
        "children": [s(c, 160) for c in children],
    }


def iec61850_read(target: Any, reference: str, fc: str = "MX") -> dict:
    """[READ] Read one data attribute by object-reference + functional constraint.

    ``fc`` is the IEC 61850 functional constraint — ``MX`` (measurands), ``ST``
    (status), ``CF`` (config), etc. Read-only.
    """
    ref = str(reference or "").strip()
    if not ref:
        return {"error": "reference is required (e.g. 'IED1MMXU1.TotW.mag.f')."}
    with iec61850_session(target) as adapter:
        result = adapter.read(ref, str(fc or "MX").upper())
    value = result.get("value")
    return {
        "endpoint": s(getattr(target, "name", ""), 64),
        "reference": s(ref, 200),
        "fc": s(result.get("fc", fc), 8),
        "value": num(value) if num(value) is not None else s(value, 200),
        "error": s(result.get("error", ""), 160) if result.get("error") else "",
    }


__all__ = [
    "iec61850_device_directory",
    "iec61850_browse",
    "iec61850_read",
    "OTConnectionError",
]
