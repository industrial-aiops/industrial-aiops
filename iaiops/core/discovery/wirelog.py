"""The wire log — an append-only record of every packet class this scan emitted.

This is the trust page of the report, and it is deliberately the *first* section
a reader sees. "We connected to 1,524 TCP ports and made 12 Modbus device-ID
requests" is checkable against a packet capture; "the scan was safe" is not.

The one design decision that gives it teeth: :func:`WireLog.record` accepts only
a **known** packet class. A stage that starts emitting something new cannot
quietly do so — it has to add the class here, where the declaration sits next to
every other thing this product is willing to put on an OT network. An unknown
kind raises rather than being logged as "other".

Counts are always kept; individual events are kept up to a cap, because a /16
sweep would otherwise hold a million records in memory to say the same thing.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass
from typing import Final

# --- the complete set of packet classes this product may put on a network ---
#: A full TCP handshake, immediately closed. No payload.
TCP_CONNECT: Final = "tcp_connect"
#: BACnet Who-Is, one UDP broadcast on an operator-named interface.
UDP_BROADCAST_WHOIS: Final = "udp_broadcast_whois"
#: PROFINET DCP IdentifyAll, one L2 broadcast on an operator-named interface.
L2_DCP_IDENTIFY: Final = "l2_dcp_identify"
#: Modbus FC43 / MEI-14 read device identification.
MODBUS_FC43: Final = "modbus_fc43"
#: OPC-UA GetEndpoints — no session is created.
OPCUA_GETENDPOINTS: Final = "opcua_getendpoints"
#: OPC-UA session opened (L4 browse only, per-device opt-in).
OPCUA_SESSION: Final = "opcua_session"
#: OPC-UA address-space browse request (L4 only).
OPCUA_BROWSE: Final = "opcua_browse"
#: S7 COTP connect + CPU info read.
S7_CPU_INFO: Final = "s7_cpu_info"
#: EtherNet/IP ListIdentity.
EIP_LIST_IDENTITY: Final = "eip_list_identity"
#: Mitsubishi MC CPU status read.
MC_CPU_STATUS: Final = "mc_cpu_status"
#: MTConnect HTTP GET /probe.
MTCONNECT_PROBE: Final = "mtconnect_probe"
#: IO-Link master HTTP read.
IOLINK_HTTP: Final = "iolink_http"
#: BAS / Ignition supervisory HTTPS read.
HTTP_READ: Final = "http_read"
#: MQTT connect+subscribe with a random unique client-id (opt-in).
MQTT_SUBSCRIBE: Final = "mqtt_subscribe"
#: BACnet object-list read against one already-discovered device (L4 only).
BACNET_OBJECT_LIST: Final = "bacnet_object_list"

#: Every class, with the plain-language description that reaches the report.
KNOWN_KINDS: Final[dict[str, str]] = {
    TCP_CONNECT: "TCP connect and immediate close, no payload",
    UDP_BROADCAST_WHOIS: "BACnet Who-Is broadcast (one UDP frame)",
    L2_DCP_IDENTIFY: "PROFINET DCP IdentifyAll broadcast (one L2 frame)",
    MODBUS_FC43: "Modbus read-device-identification (FC43/MEI-14)",
    OPCUA_GETENDPOINTS: "OPC-UA GetEndpoints — no session opened",
    OPCUA_SESSION: "OPC-UA session opened (deep browse, opted in per device)",
    OPCUA_BROWSE: "OPC-UA address-space browse (deep browse, opted in per device)",
    S7_CPU_INFO: "S7 CPU information read",
    EIP_LIST_IDENTITY: "EtherNet/IP ListIdentity",
    MC_CPU_STATUS: "Mitsubishi MC CPU status read",
    MTCONNECT_PROBE: "MTConnect HTTP GET /probe",
    IOLINK_HTTP: "IO-Link master HTTP read",
    HTTP_READ: "Supervisory controller HTTPS read",
    MQTT_SUBSCRIBE: "MQTT connect and subscribe, random unique client-id",
    BACNET_OBJECT_LIST: "BACnet object-list read on a discovered device",
}

#: What this product never does. Rendered verbatim in the report next to the
#: counts above, because an honest list of absences is what makes the counts
#: mean anything.
NEVER_DONE: Final[tuple[str, ...]] = (
    "No writes of any kind — no register, tag, setpoint, property or program write",
    "No full-port scanning — only the fixed industrial port allowlist",
    "No raw sockets, no half-open SYN scans, no ICMP sweeps",
    "No malformed or fuzzed frames — every request is spec-conformant",
    "No Modbus register sweeps — register maps come from templates you choose",
    "No PROFINET DCP Set (station renaming / re-addressing)",
    "No SECS/GEM HSMS sessions — a fab tool's single host slot is never taken",
    "No credential retries — one attempt per host and protocol, never a spray",
    "No EtherNet/IP implicit I/O (UDP 2222) and no PROFINET real-time channels",
)

DEFAULT_EVENT_CAP: Final = 5000


@dataclass(frozen=True)
class WireEvent:
    kind: str
    host: str = ""
    detail: str = ""


class UnknownWireKind(ValueError):
    """A stage tried to emit a packet class that was never declared here."""


class WireLog:
    """Append-only, thread-safe tally of what actually went on the wire."""

    def __init__(self, event_cap: int = DEFAULT_EVENT_CAP) -> None:
        self._counts: Counter[str] = Counter()
        self._events: list[WireEvent] = []
        self._cap = event_cap
        self._dropped = 0
        self._lock = threading.Lock()

    def record(self, kind: str, host: str = "", detail: str = "") -> None:
        if kind not in KNOWN_KINDS:
            raise UnknownWireKind(
                f"{kind!r} is not a declared packet class. Every emission must be "
                "declared in iaiops.core.discovery.wirelog.KNOWN_KINDS — that "
                "declaration is what the scan report is able to promise."
            )
        with self._lock:
            self._counts[kind] += 1
            if len(self._events) < self._cap:
                self._events.append(WireEvent(kind=kind, host=host, detail=detail))
            else:
                self._dropped += 1

    def summary(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))

    def total(self) -> int:
        with self._lock:
            return sum(self._counts.values())

    def events(self) -> tuple[WireEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def events_dropped(self) -> int:
        """Events past the cap. Counts are still exact; only detail was dropped."""
        with self._lock:
            return self._dropped

    def report(self) -> dict[str, object]:
        """The trust section of the scan report."""
        counts = self.summary()
        return {
            "total_emissions": sum(counts.values()),
            "by_class": [
                {"kind": k, "count": v, "description": KNOWN_KINDS[k]} for k, v in counts.items()
            ],
            "never_done": list(NEVER_DONE),
            "detail_events_kept": len(self.events()),
            "detail_events_dropped": self.events_dropped,
        }


__all__ = [
    "WireLog",
    "WireEvent",
    "UnknownWireKind",
    "KNOWN_KINDS",
    "NEVER_DONE",
    "TCP_CONNECT",
    "UDP_BROADCAST_WHOIS",
    "L2_DCP_IDENTIFY",
    "MODBUS_FC43",
    "OPCUA_GETENDPOINTS",
    "OPCUA_SESSION",
    "OPCUA_BROWSE",
    "S7_CPU_INFO",
    "EIP_LIST_IDENTITY",
    "MC_CPU_STATUS",
    "MTCONNECT_PROBE",
    "IOLINK_HTTP",
    "HTTP_READ",
    "MQTT_SUBSCRIBE",
    "BACNET_OBJECT_LIST",
]
