"""The industrial port allowlist — what a scan is permitted to touch, and why.

This is a **allowlist, never a range**. Full-port sweeps are the single fastest
way to fault a legacy PLC and to look like an attacker on the plant's IDS; the
scanner has no mode that produces one. Every port below is here because a named
industrial protocol listens on it, and every port carries the reason it is on or
off by default.

Three rules this module exists to make structural rather than aspirational:

1. **SECS/GEM is never scanned.** ``secsgem`` appears in no port's candidate
   list. A fab tool typically accepts exactly ONE host connection, so opening an
   HSMS session to "identify" it can knock the real MES host offline and stop a
   production tool. Port 5000 IS scannable — because MTConnect agents also live
   there — but only ever with the MTConnect **HTTP** probe, which a SECS-GEM
   port simply refuses. Identification by accident is fine; a session is not.

2. **Some ports are reachable but must never be probed.** :data:`NEVER_SCAN`
   names them with the damage each would do. The guard test asserts the two sets
   never intersect, so a future "let's also check 2222" cannot pass review by
   being merely plausible.

3. **UDP protocols are not swept.** BACnet, FINS and HART are UDP; there is no
   handshake to make, and an unsolicited frame to a wrong node address raises
   device-side error counters. BACnet is found by its own ``Who-Is`` broadcast
   (an L0 capability that already exists); FINS and HART require the operator to
   supply the address, and are opt-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

TCP: Final = "tcp"
UDP: Final = "udp"


@dataclass(frozen=True)
class IndustrialPort:
    """One allowlisted port and the protocols that may be *identified* on it.

    ``protocols`` is ordered: the identify stage tries the cheapest, least
    invasive candidate first and stops at the first confirmation. An empty
    tuple means "reachability only" — the port is recorded as open and nothing
    is ever spoken to it.
    """

    port: int
    transport: str
    protocols: tuple[str, ...]
    #: In the default (``inventory``) profile? Opt-in ports are those that are
    #: ambiguous with IT services, or whose probe can disturb a third party.
    default: bool
    note: str


#: The allowlist. Nothing outside this table is ever contacted by a sweep.
ALLOWLIST: Final[tuple[IndustrialPort, ...]] = (
    IndustrialPort(
        port=102,
        transport=TCP,
        protocols=("s7",),
        default=True,
        note="ISO-on-TCP (RFC1006). Identify reads CPU info — identity-only, no data blocks.",
    ),
    IndustrialPort(
        port=502,
        transport=TCP,
        protocols=("modbus",),
        default=True,
        note=(
            "Modbus-TCP. Identify uses FC43/MEI-14 device identification, NOT a register "
            "read: some legacy slaves fault or drop the session on an unmapped address."
        ),
    ),
    IndustrialPort(
        port=4840,
        transport=TCP,
        protocols=("opcua",),
        default=True,
        note=(
            "OPC-UA binary. Identify uses GetEndpoints, which does NOT open a session — "
            "embedded servers often allow only 2-5 sessions and an unattended re-scan "
            "would otherwise evict the plant's real SCADA client."
        ),
    ),
    IndustrialPort(
        port=4843,
        transport=TCP,
        protocols=("opcua",),
        default=True,
        note="OPC-UA over TLS. Same GetEndpoints rule as 4840.",
    ),
    IndustrialPort(
        port=44818,
        transport=TCP,
        protocols=("ethernetip",),
        default=True,
        note="EtherNet/IP explicit messaging. Identify uses ListIdentity — identity-only.",
    ),
    IndustrialPort(
        port=5007,
        transport=TCP,
        protocols=("mc",),
        default=True,
        note="Mitsubishi MC/SLMP. Identify reads CPU status — identity-only.",
    ),
    IndustrialPort(
        port=8088,
        transport=TCP,
        protocols=("ignition",),
        default=False,
        note="Ignition gateway web API. Opt-in: an HTTP service, ambiguous with IT.",
    ),
    IndustrialPort(
        port=5000,
        transport=TCP,
        protocols=("mtconnect",),
        default=False,
        note=(
            "MTConnect agent. OPT-IN AND HTTP-ONLY. This port is also SECS/GEM HSMS; a "
            "GET /probe is harmlessly refused by an HSMS listener, whereas an HSMS "
            "session could evict a fab tool's real MES host. secsgem is deliberately "
            "absent from this candidate list — see the module docstring."
        ),
    ),
    IndustrialPort(
        port=80,
        transport=TCP,
        protocols=("mtconnect", "iolink"),
        default=False,
        note="Plain HTTP. Opt-in: heavily ambiguous with IT web services.",
    ),
    IndustrialPort(
        port=8080,
        transport=TCP,
        protocols=("mtconnect",),
        default=False,
        note="Alternate HTTP. Opt-in: ambiguous with IT.",
    ),
    IndustrialPort(
        port=443,
        transport=TCP,
        protocols=("bas",),
        default=False,
        note="HTTPS supervisory controllers (Metasys / Niagara). Opt-in: ambiguous with IT.",
    ),
    IndustrialPort(
        port=1883,
        transport=TCP,
        protocols=("mqtt",),
        default=False,
        note=(
            "MQTT. OPT-IN. Identify must use a random unique client-id: a collision "
            "disconnects the broker's real subscriber."
        ),
    ),
    IndustrialPort(
        port=8883,
        transport=TCP,
        protocols=("mqtt",),
        default=False,
        note="MQTT over TLS. Same client-id rule as 1883.",
    ),
    IndustrialPort(
        port=47808,
        transport=UDP,
        protocols=(),
        default=False,
        note=(
            "BACnet/IP. NOT swept — UDP has no handshake. BACnet devices are found by "
            "the L0 Who-Is broadcast instead. Listed so the report can explain the "
            "absence rather than leave a silent hole."
        ),
    ),
    IndustrialPort(
        port=9600,
        transport=UDP,
        protocols=(),
        default=False,
        note=(
            "Omron FINS. NOT swept — UDP, and a frame carrying a wrong network/node "
            "address raises device-side error counters. Operator must name the node."
        ),
    ),
    IndustrialPort(
        port=5094,
        transport=UDP,
        protocols=(),
        default=False,
        note=(
            "HART-IP. NOT swept — same UDP addressing hazard as FINS. Operator must "
            "supply the polling address."
        ),
    ),
)

#: Ports that are reachable in a plant but must never be contacted, with the
#: damage each probe would do. Kept as data so the guard test can assert the
#: allowlist never grows into it.
NEVER_SCAN: Final[dict[int, str]] = {
    2222: (
        "EtherNet/IP implicit I/O (UDP). Carries cyclic real-time process data; "
        "unsolicited traffic here can disturb a running control loop."
    ),
    34962: "PROFINET RT. Real-time cyclic channel — never touched over IP.",
    34963: "PROFINET RT. Real-time cyclic channel — never touched over IP.",
    34964: "PROFINET context manager. Handled only by the L0 DCP broadcast, never swept.",
    22: "SSH. Not an industrial service; scanning it makes this look like a pentest.",
    23: "Telnet. Same reason as SSH, and legacy devices expose fragile stacks here.",
    135: "MS-RPC. IT service; out of scope.",
    139: "NetBIOS. IT service; out of scope.",
    445: "SMB. IT service; out of scope.",
    3389: "RDP. IT service; out of scope.",
}

#: Protocols that no sweep may ever identify, and why. Enforced by a guard test
#: against every port's candidate list.
NEVER_IDENTIFIED: Final[dict[str, str]] = {
    "secsgem": (
        "A fab tool typically accepts ONE host connection; an HSMS session opened to "
        "identify it can evict the real MES host and stop a production tool."
    ),
    "ethercat": (
        "Layer-2 on a dedicated NIC with no IP. A scanner must exclude the EtherCAT "
        "interface entirely — there is nothing here to reach over TCP/IP."
    ),
    "profinet": (
        "Discovered only by the L0 DCP broadcast on an operator-named interface. The "
        "same connector module also exposes a station-renaming write, so it is kept "
        "out of the sweep path by construction."
    ),
}

_BY_PORT: Final[dict[tuple[int, str], IndustrialPort]] = {
    (p.port, p.transport): p for p in ALLOWLIST
}


def sweepable_ports(*, include_optional: bool = False) -> tuple[IndustrialPort, ...]:
    """TCP ports a sweep may connect to.

    UDP entries are never returned: they exist in the allowlist for reporting,
    not for sweeping (see the module docstring).
    """
    return tuple(p for p in ALLOWLIST if p.transport == TCP and (include_optional or p.default))


def ports_for_protocols(names: tuple[str, ...]) -> tuple[IndustrialPort, ...]:
    """Narrow the allowlist to the ports serving the named protocols.

    A protocol hint may only ever *narrow* the set — it can never introduce a
    port that is not already allowlisted, and never one that is
    :data:`NEVER_IDENTIFIED`.
    """
    wanted = {n.strip().lower() for n in names if n.strip()}
    unknown = wanted - {proto for p in ALLOWLIST for proto in p.protocols}
    if unknown:
        forbidden = sorted(unknown & set(NEVER_IDENTIFIED))
        if forbidden:
            reasons = "; ".join(f"{n}: {NEVER_IDENTIFIED[n]}" for n in forbidden)
            raise ValueError(f"These protocols are never discovered by scanning — {reasons}")
    return tuple(p for p in ALLOWLIST if p.transport == TCP and (set(p.protocols) & wanted))


def describe_port(port: int, transport: str = TCP) -> IndustrialPort | None:
    """Look up an allowlist entry, or ``None`` if the port is not allowlisted."""
    return _BY_PORT.get((port, transport))


def is_allowlisted(port: int, transport: str = TCP) -> bool:
    """True only for ports a sweep is permitted to contact."""
    entry = _BY_PORT.get((port, transport))
    return entry is not None and entry.transport == TCP


__all__ = [
    "ALLOWLIST",
    "NEVER_SCAN",
    "NEVER_IDENTIFIED",
    "IndustrialPort",
    "TCP",
    "UDP",
    "sweepable_ports",
    "ports_for_protocols",
    "describe_port",
    "is_allowlisted",
]
