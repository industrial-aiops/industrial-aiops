"""One authoritative per-protocol capability registry.

Historically each protocol's behaviour was duplicated across ~7 parallel
if/elif ladders (doctor probe, doctor ``where``, dataflow connect probe, per-ref
read, CoV monitor read, connection session routing), each supporting a DIFFERENT
subset of protocols — which is exactly how "hart missing from the doctor probe"
class of bug crept in.

This module collapses those ladders into ONE mapping keyed by protocol name.
Each protocol registers a callable for a capability it supports, or the explicit
:data:`UNSUPPORTED` sentinel for one it does not — so a call site raises a clear
teaching error instead of silently falling through to a wrong default. A new
protocol that forgets to register is caught by the drift-guard test
(``tests/test_capability_registry.py``) rather than mis-defaulting at runtime.

The capability callables import their connector ``ops`` lazily (kept identical to
the pre-registry inline blocks so a test that monkeypatches
``iaiops.connectors.<proto>.ops.<fn>`` still works) and never depend on the
call-site modules, so there is no import cycle. Session builders are late-bound
against :mod:`iaiops.core.runtime.connection` for the same reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from iaiops.core.runtime.config import DEFAULT_SECSGEM_PORT


class _Unsupported:
    """Sentinel: a protocol explicitly does NOT provide a capability.

    Distinct from ``None`` so "not registered at all" (a bug the drift guard
    catches) is never confused with "deliberately not supported here".
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "UNSUPPORTED"


UNSUPPORTED: Final = _Unsupported()

# Capability signatures (each takes the endpoint ``target``; read paths also a ref).
WhereHint = Callable[[Any], str]
ProbeFn = Callable[[Any], tuple[bool, str]]
ReadRefFn = Callable[[Any, str], dict]
MonitorReadFn = Callable[[Any, str], tuple[Any, str]]
SessionBuilder = Callable[[Any], Any]

# Doctor run-loop reporting style per protocol:
#   "hard"          — a failed probe is a counted, red ✗ problem
#   "opcua"         — on failure, classify + remediate (may recover on retry)
#   "informational" — an environmental miss is a yellow status, never counted
PROBE_HARD: Final = "hard"
PROBE_OPCUA: Final = "opcua"
PROBE_INFORMATIONAL: Final = "informational"


@dataclass(frozen=True)
class ProtocolCapabilities:
    """Everything the per-protocol dispatch ladders need for one protocol.

    ``where_hint`` is always a callable (the fleet default is ``host:port``);
    every other capability is either a callable or :data:`UNSUPPORTED`.
    """

    where_hint: WhereHint
    probe_style: str
    doctor_probe: ProbeFn | _Unsupported
    diagnose_connect: ProbeFn | _Unsupported
    read_ref: ReadRefFn | _Unsupported
    monitor_read: MonitorReadFn | _Unsupported
    session_builder: SessionBuilder | _Unsupported


# ─── where hints (human-readable 'where' for an endpoint) ────────────────────


def _where_default(t: Any) -> str:
    return f"{t.host}:{t.port}"


def _where_opcua(t: Any) -> str:
    return t.endpoint_url or "?"


def _where_http_agent(t: Any) -> str:
    return t.agent_url or f"{t.host}:{t.port}"


def _where_s7(t: Any) -> str:
    return f"{t.host}:{t.port} rack={t.rack} slot={t.slot}"


def _where_mc(t: Any) -> str:
    return f"{t.host}:{t.port} ({t.plctype})"


def _where_fins(t: Any) -> str:
    return f"{t.host}:{t.port} ({t.transport or 'udp'})"


def _where_mqtt(t: Any) -> str:
    return f"{t.host}:{t.port} topic={t.topic or '#'} tls={t.use_tls}"


def _where_eip(t: Any) -> str:
    return f"{t.host} slot={t.slot}"


def _where_ethercat(t: Any) -> str:
    return f"nic={t.nic or t.host or '?'}"


def _where_profinet(t: Any) -> str:
    # Layer-2 DCP: there is no TCP port — show the local interface IP.
    return f"local-ip={t.host or t.nic or '?'}"


def _where_secsgem(t: Any) -> str:
    return f"{t.host}:{t.port or DEFAULT_SECSGEM_PORT} device={t.unit_id}"


# ─── doctor probes (generic read-only reachability; return (ok, detail)) ─────


def _probe_opcua(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.opcua.ops import server_info

    info = server_info(t)
    return True, f"OPC-UA state={info.get('state')} ({info.get('product_name', '?')})"


def _probe_modbus(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.modbus.ops import modbus_read_holding

    result = modbus_read_holding(t, address=0, count=1)
    return True, f"Modbus holding[0]={result.get('decoded')}"


def _probe_s7(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.s7.ops import s7_cpu_info

    info = s7_cpu_info(t)
    return True, f"S7 cpu_status={info.get('cpu_status')}"


def _probe_mc(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.mc.ops import mc_cpu_status

    info = mc_cpu_status(t)
    return True, f"MC cpu={info.get('cpu_type')}"


def _probe_fins(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.fins.ops import fins_cpu_info

    info = fins_cpu_info(t)
    return True, f"FINS cpu={info.get('model')}"


def _probe_hart(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.hart.ops import hart_device_identity

    info = hart_device_identity(t)
    if "error" in info:
        return False, str(info["error"])
    return True, (
        f"HART identity mfr={info.get('manufacturer_id')} "
        f"device_id={info.get('device_id')}"
    )


def _probe_mtconnect(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.mtconnect.ops import mtconnect_current

    cur = mtconnect_current(t)
    return True, f"MTConnect observations={cur.get('observation_count')}"


def _probe_iolink(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.iolink.ops import master_info

    info = master_info(t)
    return True, f"IO-Link master={info.get('master', {}).get('productcode', '?')}"


def _probe_mqtt(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.sparkplug.ops import mqtt_read_topic

    out = mqtt_read_topic(t, count=1, timeout_s=3)
    return True, f"MQTT connected, messages={out.get('message_count')}"


def _probe_eip(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.eip.ops import eip_controller_info

    info = eip_controller_info(t)
    ctrl = info.get("controller", {})
    return True, f"EtherNet/IP controller={ctrl.get('product_name', '?')}"


def _probe_secsgem(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.secsgem.ops import equipment_status

    info = equipment_status(t)
    return True, f"SECS/GEM comm={info.get('communication_state')}"


# ─── dataflow connect probes (lightweight; OTProtocolError => alive upstream) ─


def _connect_opcua(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.opcua.ops import server_info

    info = server_info(t)
    return True, f"OPC-UA state={info.get('state')}"


def _connect_modbus(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.modbus.ops import modbus_read_holding

    modbus_read_holding(t, address=0, count=1)
    return True, "Modbus read OK"


def _connect_s7(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.s7.ops import s7_cpu_info

    info = s7_cpu_info(t)
    return True, f"S7 status={info.get('cpu_status')}"


def _connect_mc(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.mc.ops import mc_cpu_status

    info = mc_cpu_status(t)
    return True, f"MC cpu={info.get('cpu_type')}"


def _connect_mtconnect(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.mtconnect.ops import mtconnect_current

    cur = mtconnect_current(t)
    return True, f"MTConnect obs={cur.get('observation_count')}"


def _connect_mqtt(t: Any) -> tuple[bool, str]:
    from iaiops.connectors.sparkplug.ops import mqtt_read_topic

    out = mqtt_read_topic(t, count=1, timeout_s=3)
    return True, f"MQTT msgs={out.get('message_count')}"


# ─── per-ref reads (uniform {value, good, source_timestamp?} or {error}) ─────


def _readref_opcua(t: Any, ref: str) -> dict:
    from iaiops.connectors.opcua.ops import read_node

    return read_node(t, ref)


def _readref_modbus(t: Any, ref: str) -> dict:
    from iaiops.connectors.modbus.ops import modbus_read_holding

    r = modbus_read_holding(t, address=int(ref), count=1)
    return {"value": (r.get("decoded") or [None])[0], "good": True}


def _readref_s7(t: Any, ref: str) -> dict:
    from iaiops.connectors.s7.ops import s7_read_many

    items = s7_read_many(t, [ref]).get("items") or []
    return {"value": items[0]["value"] if items else None, "good": bool(items)}


def _readref_mc(t: Any, ref: str) -> dict:
    from iaiops.connectors.mc.ops import mc_read_words

    words = mc_read_words(t, ref, count=1).get("words") or []
    return {"value": words[0] if words else None, "good": bool(words)}


# ─── CoV monitor reads (value, source_timestamp) ─────────────────────────────


def _monitor_opcua(t: Any, ref: str) -> tuple[Any, str]:
    from iaiops.connectors.opcua.ops import read_node

    desc = read_node(t, ref)
    return desc.get("value"), desc.get("source_timestamp", "")


def _monitor_modbus(t: Any, ref: str) -> tuple[Any, str]:
    from iaiops.connectors.modbus.ops import modbus_read_holding

    r = modbus_read_holding(t, address=int(ref), count=1)
    return (r.get("decoded") or [None])[0], ""


def _monitor_s7(t: Any, ref: str) -> tuple[Any, str]:
    from iaiops.connectors.s7.ops import s7_read_many

    items = s7_read_many(t, [ref]).get("items") or []
    return (items[0]["value"] if items else None), ""


def _monitor_mc(t: Any, ref: str) -> tuple[Any, str]:
    from iaiops.connectors.mc.ops import mc_read_words

    words = mc_read_words(t, ref, count=1).get("words") or []
    return (words[0] if words else None), ""


def _monitor_eip(t: Any, ref: str) -> tuple[Any, str]:
    from iaiops.connectors.eip.ops import eip_read_tag

    desc = eip_read_tag(t, ref)
    return desc.get("value"), ""


# ─── stateful session builders (late-bound against connection.py, no cycle) ──


def _session(attr: str) -> SessionBuilder:
    """A builder that resolves ``connection.<attr>`` at call time.

    Late binding keeps the documented ``monkeypatch.setattr(connection, ...)``
    test seams working and avoids an import cycle (this module never imports
    ``connection`` at module load).
    """

    def build(target: Any) -> Any:
        from iaiops.core.runtime import connection

        return getattr(connection, attr)(target)

    return build


# ─── the registry ────────────────────────────────────────────────────────────


def _caps(
    where_hint: WhereHint,
    *,
    probe_style: str = PROBE_HARD,
    doctor_probe: ProbeFn | _Unsupported = UNSUPPORTED,
    diagnose_connect: ProbeFn | _Unsupported = UNSUPPORTED,
    read_ref: ReadRefFn | _Unsupported = UNSUPPORTED,
    monitor_read: MonitorReadFn | _Unsupported = UNSUPPORTED,
    session_builder: SessionBuilder | _Unsupported = UNSUPPORTED,
) -> ProtocolCapabilities:
    return ProtocolCapabilities(
        where_hint=where_hint,
        probe_style=probe_style,
        doctor_probe=doctor_probe,
        diagnose_connect=diagnose_connect,
        read_ref=read_ref,
        monitor_read=monitor_read,
        session_builder=session_builder,
    )


REGISTRY: Final[dict[str, ProtocolCapabilities]] = {
    "opcua": _caps(
        _where_opcua,
        probe_style=PROBE_OPCUA,
        doctor_probe=_probe_opcua,
        diagnose_connect=_connect_opcua,
        read_ref=_readref_opcua,
        monitor_read=_monitor_opcua,
        session_builder=_session("opcua_session"),
    ),
    "modbus": _caps(
        _where_default,
        doctor_probe=_probe_modbus,
        diagnose_connect=_connect_modbus,
        read_ref=_readref_modbus,
        monitor_read=_monitor_modbus,
        session_builder=_session("modbus_session"),
    ),
    "s7": _caps(
        _where_s7,
        doctor_probe=_probe_s7,
        diagnose_connect=_connect_s7,
        read_ref=_readref_s7,
        monitor_read=_monitor_s7,
        session_builder=_session("s7_session"),
    ),
    "mc": _caps(
        _where_mc,
        doctor_probe=_probe_mc,
        diagnose_connect=_connect_mc,
        read_ref=_readref_mc,
        monitor_read=_monitor_mc,
        session_builder=_session("mc_session"),
    ),
    "fins": _caps(
        _where_fins,
        doctor_probe=_probe_fins,
        session_builder=_session("fins_session"),
    ),
    "mtconnect": _caps(
        _where_http_agent,
        doctor_probe=_probe_mtconnect,
        diagnose_connect=_connect_mtconnect,
    ),
    "mqtt": _caps(
        _where_mqtt,
        doctor_probe=_probe_mqtt,
        diagnose_connect=_connect_mqtt,
        session_builder=_session("mqtt_session"),
    ),
    "ethernetip": _caps(
        _where_eip,
        doctor_probe=_probe_eip,
        monitor_read=_monitor_eip,
        session_builder=_session("eip_session"),
    ),
    "eip": _caps(
        _where_eip,
        doctor_probe=_probe_eip,
        monitor_read=_monitor_eip,
        session_builder=_session("eip_session"),
    ),
    "iolink": _caps(
        _where_http_agent,
        doctor_probe=_probe_iolink,
        session_builder=_session("iolink_session"),
    ),
    "secsgem": _caps(
        _where_secsgem,
        doctor_probe=_probe_secsgem,
        session_builder=_session("secsgem_session"),
    ),
    "hart": _caps(
        _where_default,
        doctor_probe=_probe_hart,
    ),
    # Environmental (layer-2 / optional lib / live-segment) protocols: a doctor
    # miss is informational, not a counted failure, and they expose no generic
    # probe / stateful session here (their run-loop handling lives in doctor.py).
    "ethercat": _caps(_where_ethercat, probe_style=PROBE_INFORMATIONAL),
    "profinet": _caps(_where_profinet, probe_style=PROBE_INFORMATIONAL),
    "bacnet": _caps(_where_default, probe_style=PROBE_INFORMATIONAL),
}


def get_capabilities(protocol: str) -> ProtocolCapabilities | None:
    """Return the capability record for ``protocol``, or ``None`` if unknown."""
    return REGISTRY.get(protocol)


def session_supported_protocols() -> list[str]:
    """Sorted protocol names that route to a stateful session builder."""
    return sorted(p for p, c in REGISTRY.items() if c.session_builder is not UNSUPPORTED)


__all__ = [
    "PROBE_HARD",
    "PROBE_INFORMATIONAL",
    "PROBE_OPCUA",
    "REGISTRY",
    "ProtocolCapabilities",
    "UNSUPPORTED",
    "get_capabilities",
    "session_supported_protocols",
]
