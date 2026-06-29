"""SECS/GEM operations — semiconductor / display fab equipment (READ-FIRST).

We are the HOST. SECS/GEM (SEMI E5 SECS-II · E30 GEM · E37 HSMS over TCP) is the
standard fab equipment ↔ MES language — the entry ticket for panel/semiconductor
fabs. Every op here is READ: equipment status, status variables (SVID), equipment
constants (ECID), alarms, and process programs, over a short-lived host session.

Preview: validated against an in-process secsgem fake, NOT real fab equipment.
Returns are best-effort flattened from secsgem's decoded SECS-II (``.get()``).
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import secsgem_session

_MAX_ITEMS = 1000


def _decoded(value: Any) -> Any:
    """Decode a secsgem return into plain Python.

    secsgem 0.3 is inconsistent: ``list_svs`` / ``request_svs`` / ``list_ecs`` /
    ``request_ecs`` (and ``are_you_there``) return an *undecoded* SecsStreamFunction /
    message whose no-arg ``.get()`` yields the Python structure, whereas
    ``list_alarms`` / ``get_process_program_list`` already ``.get()`` internally. We
    only call ``.get()`` on non-plain objects (a plain dict also has ``.get`` but it
    takes a key — never call it there).
    """
    if value is None or isinstance(
        value, (list, dict, tuple, str, int, float, bool, bytes, bytearray)
    ):
        return value
    getter = getattr(value, "get", None)
    if callable(getter):
        try:
            return getter()
        except TypeError:
            return value
    return value


def _plain(value: Any, depth: int = 0) -> Any:
    """Best-effort convert a secsgem decoded value into JSON-friendly plain data."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return s(value, 300)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()[:600]
    if depth > 6:
        return s(str(value), 200)
    if isinstance(value, (list, tuple)):
        return [_plain(v, depth + 1) for v in list(value)[:_MAX_ITEMS]]
    if isinstance(value, dict):
        return {str(k): _plain(v, depth + 1) for k, v in list(value.items())[:_MAX_ITEMS]}
    return s(str(value), 300)


def equipment_status(target: Any) -> dict:
    """[READ] Establish the GEM host link; report communication state + identity (S1F1/F2)."""
    with secsgem_session(target) as h:
        state = getattr(h, "communication_state", None)
        return {
            "communication_state": s(str(getattr(state, "current", state)), 60),
            "are_you_there": _plain(_decoded(h.are_you_there())),
        }


def list_status_variables(target: Any) -> dict:
    """[READ] Status-variable namelist (S1F11/F12): SVID → name/units."""
    with secsgem_session(target) as h:
        svs = _plain(_decoded(h.list_svs()))
        return {"count": len(svs) if isinstance(svs, list) else None, "status_variables": svs}


def read_status_variables(target: Any, svids: list) -> dict:
    """[READ] Status-variable values (S1F3/F4) for the given SVIDs."""
    ids = list(svids or [])[:_MAX_ITEMS]
    if not ids:
        return {"error": "Pass a non-empty list of SVIDs to read."}
    with secsgem_session(target) as h:
        return {"svids": _plain(ids), "values": _plain(_decoded(h.request_svs(ids)))}


def list_equipment_constants(target: Any) -> dict:
    """[READ] Equipment-constant namelist (S2F29/F30): ECID → name/min/max/default."""
    with secsgem_session(target) as h:
        ecs = _plain(_decoded(h.list_ecs()))
        return {"count": len(ecs) if isinstance(ecs, list) else None, "equipment_constants": ecs}


def read_equipment_constants(target: Any, ecids: list) -> dict:
    """[READ] Equipment-constant values (S2F13/F14) for the given ECIDs."""
    ids = list(ecids or [])[:_MAX_ITEMS]
    if not ids:
        return {"error": "Pass a non-empty list of ECIDs to read."}
    with secsgem_session(target) as h:
        return {"ecids": _plain(ids), "values": _plain(_decoded(h.request_ecs(ids)))}


def list_alarms(target: Any) -> dict:
    """[READ] Alarm list (S5F5/F6): ALID, ALCD (severity), alarm text."""
    with secsgem_session(target) as h:
        alarms = _plain(h.list_alarms())
        return {"count": len(alarms) if isinstance(alarms, list) else None, "alarms": alarms}


def list_process_programs(target: Any) -> dict:
    """[READ] Process-program directory (S7F19/F20): the PPID list."""
    with secsgem_session(target) as h:
        ppids = _plain(h.get_process_program_list())
        return {"count": len(ppids) if isinstance(ppids, list) else None, "process_programs": ppids}
