"""SECS/GEM operations — semiconductor / display fab equipment (READ-FIRST).

We are the HOST. SECS/GEM (SEMI E5 SECS-II · E30 GEM · E37 HSMS over TCP) is the
standard fab equipment ↔ MES language — the entry ticket for panel/semiconductor
fabs. Every op here is READ: equipment status, status variables (SVID), equipment
constants (ECID), alarms, and process programs, over a short-lived host session.

Verified (read paths) against a **real secsgem GEM equipment** over a real HSMS
link — connect/select handshake, SECS-II encode, reply decode — in
``tests/test_secsgem_live.py``. **NOT real fab equipment**: 待核实.
Returns are best-effort flattened from secsgem's decoded SECS-II (``.get()``).

An equipment that does not implement a requested function is ordinary, not
exotic — S7 process-program transfer and S5F5 are OPTIONAL GEM capabilities. In
that case secsgem hands back undecoded message bytes, which every read here now
turns into a teaching error rather than hex under a data label (``_undecodable``).
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


def _undecodable(value: Any, *, what: str, stream_function: str) -> dict | None:
    """Return a teaching error when a reply is raw bytes instead of decoded data.

    secsgem hands back the **undecoded message bytes** when the equipment answers a
    function it does not implement (or answers unparseably). Everything in this
    module then flowed through ``_plain``, which hex-encodes bytes — so an
    unsupported ``S7F19`` surfaced as::

        {"count": null, "process_programs": "0000871300009e036f8a"}

    That blob is the echoed request header. It is not a fabricated *value*, but it
    is non-data presented under a data label, and ``count: null`` is the only hint.
    An operator — or a model reading the tool result — would reasonably conclude the
    equipment reported something. Say what actually happened instead.

    Optional GEM capabilities make this ordinary, not exotic: process-program
    transfer (S7) and the alarm list (S5F5) are frequently absent on real tools.
    """
    if not isinstance(value, (bytes, bytearray)):
        return None
    return {
        "error": (
            f"The equipment did not return a usable {what} — the reply to "
            f"{stream_function} could not be decoded (secsgem handed back raw "
            f"message bytes). The usual cause is that this tool does not implement "
            f"{stream_function}: it is an OPTIONAL GEM capability."
        ),
        "hint": (
            f"Confirm the equipment supports {stream_function} (check its GEM "
            f"compliance statement / SEMI E30 capability list). Run 'iaiops doctor' "
            f"to verify the HSMS link itself is healthy."
        ),
    }


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
        raw = _decoded(h.list_svs())
        if err := _undecodable(raw, what="status-variable namelist", stream_function="S1F11"):
            return err
        svs = _plain(raw)
        return {"count": len(svs) if isinstance(svs, list) else None, "status_variables": svs}


def read_status_variables(target: Any, svids: list) -> dict:
    """[READ] Status-variable values (S1F3/F4) for the given SVIDs."""
    ids = list(svids or [])[:_MAX_ITEMS]
    if not ids:
        return {"error": "Pass a non-empty list of SVIDs to read."}
    with secsgem_session(target) as h:
        raw = _decoded(h.request_svs(ids))
        if err := _undecodable(raw, what="status-variable value", stream_function="S1F3"):
            return err
        return {"svids": _plain(ids), "values": _plain(raw)}


def list_equipment_constants(target: Any) -> dict:
    """[READ] Equipment-constant namelist (S2F29/F30): ECID → name/min/max/default."""
    with secsgem_session(target) as h:
        raw = _decoded(h.list_ecs())
        if err := _undecodable(raw, what="equipment-constant namelist", stream_function="S2F29"):
            return err
        ecs = _plain(raw)
        return {"count": len(ecs) if isinstance(ecs, list) else None, "equipment_constants": ecs}


def read_equipment_constants(target: Any, ecids: list) -> dict:
    """[READ] Equipment-constant values (S2F13/F14) for the given ECIDs."""
    ids = list(ecids or [])[:_MAX_ITEMS]
    if not ids:
        return {"error": "Pass a non-empty list of ECIDs to read."}
    with secsgem_session(target) as h:
        raw = _decoded(h.request_ecs(ids))
        if err := _undecodable(raw, what="equipment-constant value", stream_function="S2F13"):
            return err
        return {"ecids": _plain(ids), "values": _plain(raw)}


def list_alarms(target: Any) -> dict:
    """[READ] Alarm list (S5F5/F6): ALID, ALCD (severity), alarm text."""
    with secsgem_session(target) as h:
        raw = h.list_alarms()
        if err := _undecodable(raw, what="alarm list", stream_function="S5F5"):
            return err
        alarms = _plain(raw)
        return {"count": len(alarms) if isinstance(alarms, list) else None, "alarms": alarms}


def list_process_programs(target: Any) -> dict:
    """[READ] Process-program directory (S7F19/F20): the PPID list."""
    with secsgem_session(target) as h:
        raw = h.get_process_program_list()
        if err := _undecodable(raw, what="process-program directory", stream_function="S7F19"):
            return err
        ppids = _plain(raw)
        return {"count": len(ppids) if isinstance(ppids, list) else None, "process_programs": ppids}
