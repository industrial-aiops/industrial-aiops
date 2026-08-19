"""L2 — identification. One minimal, in-spec read per candidate protocol.

L1 tells you a port is open. That is not an answer: TCP 502 open means "probably
Modbus", and an inventory built on "probably" is one a controls engineer will
throw out on the first wrong row. This stage asks each candidate device what it
is, using the cheapest question the protocol defines — and never a data-plane
read.

**The four probes this module exists to route around.** The diagnostic probes
elsewhere in this codebase were written for endpoints an operator had already
configured, where the device is known and consented. Reusing them against
unknown hosts would be the fastest way to earn this product a site ban:

============  =======================================  ============================
Protocol      What the obvious probe does              What is done here instead
============  =======================================  ============================
Modbus        Reads holding register 0 — a data-plane  FC43/MEI-14 device
              request at an address the slave may not  identification: a protocol-
              map. Legacy slaves answer an unmapped    layer question that touches
              address by dropping the session or       nothing in the process image.
              faulting.
OPC-UA        Opens a SESSION. Embedded servers        GetEndpoints on the secure
              commonly allow only two to five, so an   channel — no session exists,
              unattended re-scan evicts the plant's    so nothing is consumed.
              real SCADA client from its own PLC.
SECS/GEM      Opens an HSMS session. A fab tool        Never attempted. ``secsgem``
              typically accepts exactly ONE host       is absent from every port's
              connection — the probe stops a           candidate list and from this
              production tool by taking the MES        table; see
              host's slot.                             :data:`NO_SAFE_IDENTIFY`.
MQTT          Connects with a fixed client-id. A       Not part of L2 at all — see
              collision disconnects the broker's       :data:`NO_SAFE_IDENTIFY`.
              real subscriber.
============  =======================================  ============================

**A rejection is a confirmation.** If a device answers FC43 with "illegal
function", it has spoken Modbus: it is confirmed as a Modbus device whose
identity is simply unknown. That is an :class:`OTProtocolError` and it raises
confidence. A transport failure (:class:`OTConnectionError`) does not — the port
stays ``port_only`` and **no vendor is ever invented**. The difference between
those two lines in a report is the difference between an inventory and a guess.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from iaiops.core.discovery import wirelog
from iaiops.core.discovery.pacing import HostBackedOff, Pacer, SegmentUnhealthy
from iaiops.core.discovery.ports import NEVER_IDENTIFIED, describe_port
from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    CONF_PORT_ONLY,
    PORT_OPEN,
    HostResult,
    PacingPolicy,
    ProtocolCandidate,
)
from iaiops.core.runtime.session_factory import OTConnectionError, OTProtocolError

#: Identification is a round trip, not a handshake, so it gets more room than
#: the sweep's connect timeout — but still far less than the fleet default of
#: 10s, because a scan waiting on a dead host is a scan nobody finishes.
DEFAULT_IDENTIFY_TIMEOUT_S: Final = 4.0

#: The normalized identity columns every probe maps onto. Anything a protocol
#: reports beyond these lands in ``extra``; the full raw payload is deliberately
#: NOT carried (an MTConnect probe response alone can be megabytes, and this
#: dict is written to a row per device).
IDENTITY_FIELDS: Final[tuple[str, ...]] = ("vendor", "model", "serial", "firmware", "name")

#: Siemens slot numbers, tried in this order. The ONLY probe here that makes a
#: second attempt, and it is worth the packet: S7-1200/1500 answer on slot 1 and
#: S7-300/400 on slot 2, so a single guess mis-identifies half the installed
#: base as "port open, unidentified". Both attempts are counted on the wire log.
_S7_SLOTS: Final[tuple[int, ...]] = (1, 2)


class ProbeUnavailable(RuntimeError):
    """This machine cannot load the probe. The device was never asked.

    Distinct from a device failure: the finding is about THIS machine, and the
    report must say so rather than blame the device.
    """


def _unavailable(protocol: str, extra: str, exc: Exception) -> ProbeUnavailable:
    """Name the module that is actually missing, not the one we assume.

    A probe import failing does NOT prove the protocol extra is absent — the
    connector also reaches base dependencies through the config layer. Saying
    "modbus extra not installed" when the missing module is ``cryptography``
    sends someone to ``pip install iaiops[modbus]``, which changes nothing, and
    costs an afternoon on a plant floor where there may be no second attempt.
    """
    missing = getattr(exc, "name", "") or str(exc)
    return ProbeUnavailable(
        f"cannot load the {protocol} probe here — missing module {missing!r}. "
        f"If it is a driver, install iaiops[{extra}]; if it is a base dependency, "
        "this install is incomplete."
    )


def _identity(
    *,
    vendor: str = "",
    model: str = "",
    serial: str = "",
    firmware: str = "",
    name: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Assemble an identity, dropping every field the device did not supply.

    Empty is not "unknown vendor" — it is an absent column, and a report that
    renders it as a blank cell rather than a guess is the whole point.
    """
    out = {
        k: str(v).strip()
        for k, v in (
            ("vendor", vendor),
            ("model", model),
            ("serial", serial),
            ("firmware", firmware),
            ("name", name),
        )
        if str(v).strip()
    }
    clean_extra = {k: v for k, v in extra.items() if v not in ("", None, {}, [])}
    if clean_extra:
        out["extra"] = clean_extra
    return out


def _target(*, protocol: str, label: str, timeout_s: float, **fields: Any) -> Any:
    """Build a throwaway :class:`TargetConfig` for one probe.

    Everything is keyword-only on purpose: ``host`` and ``port`` are both
    connection FIELDS of a TargetConfig and would collide with any positional
    parameter of the same name — a collision that is a ``TypeError`` at call
    time, i.e. a probe that never runs against a live device.

    ``config`` is imported lazily because it pulls in yaml and the secret store,
    and this module is imported by the dry-run preview, which must stay cheap
    and must never touch a config file.
    """
    from iaiops.core.runtime.config import TargetConfig

    return TargetConfig(name=f"scan:{label}", protocol=protocol, timeout_s=timeout_s, **fields)


# --- the probes ------------------------------------------------------------
# Each takes (host, port, timeout_s, log), records its own emissions so retries
# stay honestly counted, and returns a normalized identity dict.


def _probe_modbus(host: str, port: int, timeout_s: float, log: wirelog.WireLog) -> dict[str, Any]:
    try:
        from iaiops.connectors.modbus import ops
    except ImportError as exc:  # pragma: no cover - exercised via _run_probe
        raise _unavailable("modbus", "modbus", exc) from exc

    # Unit id 1 only. A serial-bridged slave may sit at any id, but walking ids
    # to find it is a request storm against a device that has not answered yet —
    # exactly the sweep this product refuses to do. Configure the endpoint and
    # the ordinary read path finds it.
    target = _target(
        protocol="modbus",
        label=f"{host}:{port}",
        timeout_s=timeout_s,
        host=host,
        port=port,
        unit_id=1,
    )
    log.record(wirelog.MODBUS_FC43, host=host, detail=str(port))
    raw = ops.modbus_read_device_identification(target)
    return _identity(
        vendor=raw.get("vendor", ""),
        model=raw.get("product_code", ""),
        firmware=raw.get("revision", ""),
        unit_id=raw.get("unit_id"),
        objects=raw.get("objects") or {},
        undecodable=raw.get("undecodable") or [],
    )


def _probe_opcua(host: str, port: int, timeout_s: float, log: wirelog.WireLog) -> dict[str, Any]:
    try:
        from iaiops.connectors.opcua import ops
    except ImportError as exc:  # pragma: no cover - exercised via _run_probe
        raise _unavailable("opcua", "opcua", exc) from exc

    scheme = "opc.tcp"
    target = _target(
        protocol="opcua",
        label=f"{host}:{port}",
        timeout_s=timeout_s,
        endpoint_url=f"{scheme}://{host}:{port}/",
    )
    log.record(wirelog.OPCUA_GETENDPOINTS, host=host, detail=str(port))
    raw = ops.opcua_endpoints(target)
    return _identity(
        name=raw.get("application_name", ""),
        model=raw.get("product_uri", ""),
        application_uri=raw.get("application_uri", ""),
        endpoint_count=raw.get("endpoint_count"),
        # Visible without authenticating, and exactly what a 62443 review acts
        # on — so it rides along with the identification rather than needing a
        # second, deeper pass.
        allows_none_security=raw.get("allows_none_security"),
        allows_anonymous=raw.get("allows_anonymous"),
    )


def _probe_s7(host: str, port: int, timeout_s: float, log: wirelog.WireLog) -> dict[str, Any]:
    try:
        from iaiops.connectors.s7 import ops
    except ImportError as exc:  # pragma: no cover - exercised via _run_probe
        raise _unavailable("s7", "s7", exc) from exc

    last: OTConnectionError | None = None
    for slot in _S7_SLOTS:
        target = _target(
            protocol="s7",
            label=f"{host}:{port}",
            timeout_s=timeout_s,
            host=host,
            port=port,
            rack=0,
            slot=slot,
        )
        log.record(wirelog.S7_CPU_INFO, host=host, detail=f"{port} slot={slot}")
        try:
            raw = ops.s7_cpu_info(target)
        except OTProtocolError:
            # The CPU answered in-protocol and refused. That is a confirmation,
            # not a reason to try the other slot with another packet.
            raise
        except OTConnectionError as exc:
            last = exc
            continue
        info = raw.get("cpu_info") or {}
        return _identity(
            vendor="Siemens" if info else "",
            model=info.get("ModuleTypeName", "") or info.get("ModuleName", ""),
            serial=info.get("SerialNumber", ""),
            firmware=info.get("ModuleVersion", "") or info.get("HardwareVersion", ""),
            name=info.get("ASName", ""),
            slot=slot,
            cpu_status=raw.get("cpu_status", ""),
            info_error=info.get("info_error", ""),
        )
    raise last if last is not None else OTConnectionError("S7 identification made no attempt")


def _probe_eip(host: str, port: int, timeout_s: float, log: wirelog.WireLog) -> dict[str, Any]:
    try:
        from iaiops.connectors.eip import ops
    except ImportError as exc:  # pragma: no cover - exercised via _run_probe
        raise _unavailable("ethernetip", "eip", exc) from exc

    target = _target(
        protocol="ethernetip",
        label=f"{host}:{port}",
        timeout_s=timeout_s,
        host=host,
        port=port,
        slot=0,
    )
    log.record(wirelog.EIP_LIST_IDENTITY, host=host, detail=str(port))
    raw = ops.eip_controller_info(target)
    ctrl = raw.get("controller") or {}
    return _identity(
        vendor=ctrl.get("vendor", ""),
        model=ctrl.get("product_name", "") or ctrl.get("processor_type", ""),
        serial=str(ctrl.get("serial", "") or ""),
        firmware=str(ctrl.get("revision", "") or ""),
        name=ctrl.get("name", ""),
        plctype=raw.get("plctype", ""),
        info_error=raw.get("info_error", ""),
    )


def _probe_mc(host: str, port: int, timeout_s: float, log: wirelog.WireLog) -> dict[str, Any]:
    try:
        from iaiops.connectors.mc import ops
    except ImportError as exc:  # pragma: no cover - exercised via _run_probe
        raise _unavailable("mc", "mc", exc) from exc

    target = _target(
        protocol="mc",
        label=f"{host}:{port}",
        timeout_s=timeout_s,
        host=host,
        port=port,
    )
    log.record(wirelog.MC_CPU_STATUS, host=host, detail=str(port))
    raw = ops.mc_cpu_status(target)
    return _identity(
        vendor="Mitsubishi" if raw.get("cpu_type") else "",
        model=raw.get("cpu_type", ""),
        cpu_code=raw.get("cpu_code", ""),
        plctype=raw.get("plctype", ""),
    )


def _probe_mtconnect(
    host: str, port: int, timeout_s: float, log: wirelog.WireLog
) -> dict[str, Any]:
    try:
        from iaiops.connectors.mtconnect import ops
    except ImportError as exc:  # pragma: no cover - exercised via _run_probe
        raise _unavailable("mtconnect", "mtconnect", exc) from exc

    target = _target(
        protocol="mtconnect",
        label=f"{host}:{port}",
        timeout_s=timeout_s,
        agent_url=f"http://{host}:{port}",
    )
    log.record(wirelog.MTCONNECT_PROBE, host=host, detail=str(port))
    raw = ops.mtconnect_probe(target)
    devices = raw.get("devices") or []
    first = devices[0] if devices else {}
    # Only the head of the device tree is kept. The full probe response carries
    # every data item of every component and belongs to L4, not to an
    # inventory row.
    return _identity(
        name=first.get("name", ""),
        serial=first.get("uuid", ""),
        device_count=raw.get("device_count"),
        devices=[d.get("name", "") for d in devices[:20] if d.get("name")],
    )


def _probe_iolink(host: str, port: int, timeout_s: float, log: wirelog.WireLog) -> dict[str, Any]:
    try:
        from iaiops.connectors.iolink import ops
    except ImportError as exc:  # pragma: no cover - exercised via _run_probe
        raise _unavailable("iolink", "iolink", exc) from exc

    target = _target(
        protocol="iolink",
        label=f"{host}:{port}",
        timeout_s=timeout_s,
        agent_url=f"http://{host}:{port}",
    )
    log.record(wirelog.IOLINK_HTTP, host=host, detail=str(port))
    raw = ops.master_info(target)
    master = raw.get("master") or {}
    return _identity(
        vendor=master.get("vendor", ""),
        model=master.get("productcode", "") or master.get("devicefamily", ""),
        serial=master.get("serialnumber", ""),
        firmware=master.get("swrevision", "") or master.get("hwrevision", ""),
        name=master.get("devicename", ""),
        flavor=raw.get("flavor", ""),
    )


@dataclass(frozen=True)
class IdentifyProbe:
    """One protocol's safe identification call.

    ``rationale`` is not decoration: it is rendered into the dry-run preview an
    operator signs, next to the packet class it emits.
    """

    protocol: str
    wire_kind: str
    rationale: str
    run: Callable[[str, int, float, wirelog.WireLog], dict[str, Any]]
    #: Emits more than one request in the worst case (only S7, and only because
    #: the slot is unknowable in advance). Surfaced so the preview's estimate is
    #: an upper bound rather than an optimistic one.
    max_requests: int = 1


IDENTIFY_PLAN: Final[dict[str, IdentifyProbe]] = {
    "modbus": IdentifyProbe(
        protocol="modbus",
        wire_kind=wirelog.MODBUS_FC43,
        rationale=(
            "FC43/MEI-14 device identification — a protocol-layer question. No "
            "register is read, so nothing in the process image is touched."
        ),
        run=_probe_modbus,
    ),
    "opcua": IdentifyProbe(
        protocol="opcua",
        wire_kind=wirelog.OPCUA_GETENDPOINTS,
        rationale=(
            "GetEndpoints on the secure channel. No session is created, so none "
            "of the server's two-to-five session slots is consumed."
        ),
        run=_probe_opcua,
    ),
    "s7": IdentifyProbe(
        protocol="s7",
        wire_kind=wirelog.S7_CPU_INFO,
        rationale=(
            "CPU identity read (SZL). Slot 1 then slot 2 — the only probe that "
            "retries, because S7-1200/1500 and S7-300/400 differ and a single "
            "guess mis-reports half the installed base. No data block is read."
        ),
        run=_probe_s7,
        max_requests=len(_S7_SLOTS),
    ),
    "ethernetip": IdentifyProbe(
        protocol="ethernetip",
        wire_kind=wirelog.EIP_LIST_IDENTITY,
        rationale=(
            "CIP identity object read over explicit messaging. Explicit messaging "
            "is the out-of-band channel; the implicit I/O channel (UDP 2222) that "
            "carries live process data is never touched."
        ),
        run=_probe_eip,
    ),
    "mc": IdentifyProbe(
        protocol="mc",
        wire_kind=wirelog.MC_CPU_STATUS,
        rationale="MELSEC CPU type read — identity only, no device memory.",
        run=_probe_mc,
    ),
    "mtconnect": IdentifyProbe(
        protocol="mtconnect",
        wire_kind=wirelog.MTCONNECT_PROBE,
        rationale=(
            "HTTP GET /probe against the agent. On port 5000, which MTConnect "
            "shares with SECS/GEM HSMS, an HSMS listener simply refuses the GET "
            "— which is why identification here can never take a fab tool's "
            "single host slot."
        ),
        run=_probe_mtconnect,
    ),
    "iolink": IdentifyProbe(
        protocol="iolink",
        wire_kind=wirelog.IOLINK_HTTP,
        rationale="IO-Link master /deviceinfo read over HTTP — master identity only.",
        run=_probe_iolink,
    ),
}

#: Protocols reachable on an allowlisted port for which L2 deliberately has NO
#: probe, each with the reason. Kept as data so the report can explain an open
#: port that stayed unidentified, instead of leaving a silent hole that reads
#: like a bug.
NO_SAFE_IDENTIFY: Final[dict[str, str]] = {
    "mqtt": (
        "A broker identifies itself only to a client that has connected and "
        "subscribed, and a client-id collision disconnects the broker's real "
        "subscriber. Requires an explicit per-broker opt-in with a generated "
        "unique client-id; it is not part of automatic identification."
    ),
    "bas": (
        "Supervisory controllers (Metasys / Niagara) expose nothing without "
        "credentials, and this scanner never guesses or sprays them. Configure "
        "the endpoint with a token and it becomes an ordinary read."
    ),
    "ignition": (
        "The gateway API requires an API token. Same rule as above: an "
        "unauthenticated scan reports the open port and stops there."
    ),
}


def _validate_plan() -> None:
    """Structural guarantees, checked at import so a bad edit cannot ship.

    These are the invariants a reviewer would otherwise have to re-derive by
    reading three modules; failing at import turns them into facts.
    """
    forbidden = set(IDENTIFY_PLAN) & set(NEVER_IDENTIFIED)
    if forbidden:
        raise RuntimeError(
            f"IDENTIFY_PLAN contains protocols that must never be probed by a scan: "
            f"{sorted(forbidden)}. See iaiops.core.discovery.ports.NEVER_IDENTIFIED."
        )
    undeclared = {p.wire_kind for p in IDENTIFY_PLAN.values()} - set(wirelog.KNOWN_KINDS)
    if undeclared:
        raise RuntimeError(
            f"IDENTIFY_PLAN emits undeclared packet classes: {sorted(undeclared)}. "
            "Declare them in iaiops.core.discovery.wirelog.KNOWN_KINDS first — that "
            "declaration is what the scan report is able to promise."
        )
    overlap = set(IDENTIFY_PLAN) & set(NO_SAFE_IDENTIFY)
    if overlap:
        raise RuntimeError(
            f"{sorted(overlap)} are listed both as having a safe probe and as having "
            "none. One of the two statements is a lie; fix the table."
        )


_validate_plan()


def identify_emissions() -> tuple[str, ...]:
    """Every packet class L2 can emit, derived from the table rather than listed.

    The dry-run preview uses this, so the promise an operator signs cannot drift
    from the probes that actually run.
    """
    return tuple(sorted({p.wire_kind for p in IDENTIFY_PLAN.values()}))


def candidates_for_port(port: int) -> tuple[str, ...]:
    """Protocols worth trying on ``port``, cheapest first, with a probe available."""
    entry = describe_port(port)
    if entry is None:
        return ()
    return tuple(p for p in entry.protocols if p in IDENTIFY_PLAN)


def _run_probe(
    probe: IdentifyProbe, host: str, port: int, timeout_s: float, log: wirelog.WireLog
) -> tuple[ProtocolCandidate, dict[str, Any]]:
    """Run one probe and turn every possible outcome into an honest verdict.

    Always returns ``(candidate, identity)``; the identity is empty for every
    outcome except a clean success, which is the only case where the device
    actually told us something.
    """
    try:
        identity = probe.run(host, port, timeout_s, log)
    except ProbeUnavailable as exc:
        # A finding about THIS machine, not about the device. Saying "could not
        # identify" here would blame a device that was never asked.
        return (
            ProtocolCandidate(
                protocol=probe.protocol,
                confidence=CONF_PORT_ONLY,
                evidence="probe_unavailable",
                detail=f"{exc} — this host was not asked; install the extra and re-scan",
            ),
            {},
        )
    except OTProtocolError as exc:
        # It ANSWERED, in-protocol, and refused. Protocol confirmed; identity
        # unknown. Not the same thing as silence, and never merged with it.
        return (
            ProtocolCandidate(
                protocol=probe.protocol,
                confidence=CONF_CONFIRMED,
                evidence=f"{probe.wire_kind}:rejected",
                detail=f"device answered in-protocol and declined: {_short(exc)}",
            ),
            {},
        )
    except OTConnectionError as exc:
        return (
            ProtocolCandidate(
                protocol=probe.protocol,
                confidence=CONF_PORT_ONLY,
                evidence="tcp_open",
                detail=_short(exc),
            ),
            {},
        )
    except Exception as exc:  # noqa: BLE001 — one odd device must not end a scan
        return (
            ProtocolCandidate(
                protocol=probe.protocol,
                confidence=CONF_PORT_ONLY,
                evidence="tcp_open",
                detail=f"unexpected {type(exc).__name__}: {_short(exc)}",
            ),
            {},
        )
    return (
        ProtocolCandidate(
            protocol=probe.protocol,
            confidence=CONF_CONFIRMED,
            evidence=probe.wire_kind,
            detail=_summarize(identity),
        ),
        identity,
    )


def _short(exc: Exception, limit: int = 160) -> str:
    text = " ".join(str(exc).split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _summarize(identity: dict[str, Any]) -> str:
    parts = [f"{k}={identity[k]}" for k in IDENTITY_FIELDS if identity.get(k)]
    return ", ".join(parts) if parts else "identified, no identity fields returned"


def identify_host(
    host: HostResult,
    *,
    log: wirelog.WireLog,
    pacer: Pacer | None = None,
    timeout_s: float = DEFAULT_IDENTIFY_TIMEOUT_S,
    plan: dict[str, IdentifyProbe] | None = None,
) -> HostResult:
    """Identify the protocols behind one host's OPEN ports.

    Only ``open`` ports are probed. A refused port is a positive finding about
    the host and is carried forward untouched; a filtered one proves nothing and
    is likewise never spoken to.

    The first CONFIRMED candidate on a port ends that port's probing. Remaining
    candidates are not tried, because a second request to a device that has
    already answered buys nothing and costs a packet.
    """
    plan = plan if plan is not None else IDENTIFY_PLAN
    open_ports = [p.port for p in host.ports if p.state == PORT_OPEN]
    if not open_ports:
        return host

    candidates: list[ProtocolCandidate] = []
    identity: dict[str, Any] = dict(host.identity)
    errors: list[str] = list(host.errors)

    for port in sorted(open_ports):
        for name in candidates_for_port(port):
            probe = plan.get(name)
            if probe is None:
                continue
            try:
                candidate, found = _probe_once(
                    probe, host.ip, port, timeout_s=timeout_s, log=log, pacer=pacer
                )
            except HostBackedOff as exc:
                errors.append(str(exc))
                return _rebuild(host, candidates, identity, errors)
            candidates.append(candidate)
            if found:
                # Namespaced so two protocols on one host cannot overwrite each
                # other's vendor — a gateway speaking Modbus and OPC-UA is a
                # normal thing, not a conflict to resolve by last-write-wins.
                identity[candidate.protocol] = found
            if candidate.confidence == CONF_CONFIRMED:
                break

    return _rebuild(host, candidates, identity, errors)


def _probe_once(
    probe: IdentifyProbe,
    ip: str,
    port: int,
    *,
    timeout_s: float,
    log: wirelog.WireLog,
    pacer: Pacer | None,
) -> tuple[ProtocolCandidate, dict[str, Any]]:
    """Run one probe under the pacer, and feed the verdict back to segment health.

    A ``port_only`` outcome counts as an error for backoff purposes even though
    it is a legitimate finding: whatever the reason, this host is not answering
    us, and hammering it with the next candidate protocol is precisely what the
    backoff exists to prevent.
    """
    if pacer is None:
        return _run_probe(probe, ip, port, timeout_s, log)
    with pacer.probe(ip):
        candidate, found = _run_probe(probe, ip, port, timeout_s, log)
    if candidate.confidence == CONF_CONFIRMED:
        pacer.health.record_ok(ip)
    else:
        pacer.health.record_error(ip)
    return candidate, found


def _rebuild(
    host: HostResult,
    candidates: Sequence[ProtocolCandidate],
    identity: dict[str, Any],
    errors: Sequence[str],
) -> HostResult:
    return dataclasses.replace(
        host,
        protocols=tuple(candidates),
        identity=identity,
        errors=tuple(errors[:20]),
    )


def identify_pacing(policy: PacingPolicy) -> PacingPolicy:
    """The sweep's policy, re-spaced for identification.

    An identify call is a round trip against a device's protocol stack, not a
    handshake the kernel answers, so the same host is left alone for
    ``identify_gap_ms`` between calls instead of ``per_host_gap_ms``.
    """
    return dataclasses.replace(policy, per_host_gap_ms=policy.identify_gap_ms)


def identify_hosts(
    hosts: Iterable[HostResult],
    *,
    log: wirelog.WireLog | None = None,
    pacing: PacingPolicy | None = None,
    timeout_s: float = DEFAULT_IDENTIFY_TIMEOUT_S,
    plan: dict[str, IdentifyProbe] | None = None,
) -> tuple[tuple[HostResult, ...], tuple[str, ...]]:
    """Identify a whole sweep's worth of hosts. Returns results and run notes.

    Deliberately sequential. The sweep parallelises because a TCP connect is
    answered by a kernel; an identify call is answered by a control CPU that is
    also running a machine, and four of those at once against one small plant
    network is a different kind of load. Throughput here is not the goal —
    finishing without anyone noticing is.
    """
    log = log or wirelog.WireLog()
    pacer = Pacer(identify_pacing(pacing or PacingPolicy()))
    out: list[HostResult] = []
    notes: list[str] = []

    for host in hosts:
        try:
            out.append(identify_host(host, log=log, pacer=pacer, timeout_s=timeout_s, plan=plan))
        except SegmentUnhealthy as exc:
            notes.append(str(exc))
            out.append(host)
            break
        except HostBackedOff:
            out.append(host)

    unidentified = [
        h
        for h in out
        if any(p.state == PORT_OPEN for p in h.ports)
        and not any(c.confidence == CONF_CONFIRMED for c in h.protocols)
    ]
    if unidentified:
        notes.append(
            f"{len(unidentified)} host(s) have an open industrial port that no probe "
            "confirmed. They are reported as 'port only' with no vendor — an open "
            "port is a location, not an identification."
        )
    return tuple(out), tuple(notes)


__all__ = [
    "DEFAULT_IDENTIFY_TIMEOUT_S",
    "IDENTITY_FIELDS",
    "IDENTIFY_PLAN",
    "NO_SAFE_IDENTIFY",
    "IdentifyProbe",
    "ProbeUnavailable",
    "identify_emissions",
    "candidates_for_port",
    "identify_host",
    "identify_hosts",
    "identify_pacing",
]
