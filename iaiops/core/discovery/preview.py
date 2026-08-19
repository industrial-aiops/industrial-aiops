"""The dry-run preview — everything a scan would touch, emitting nothing.

This module exists before the scanner does, on purpose. The first thing anyone
can run against a plant network is the thing that puts **zero packets** on it:
a preview that states the exact host list, the exact ports, the exact protocol
call that may be made on each, the worst-case duration under the rate limits,
and — as prominently as the rest — the list of things this scan will never do.

That artifact is what a plant's controls engineer signs off on. Its value comes
entirely from being derivable without touching anything, so this module does no
I/O of any kind: given a :class:`~iaiops.core.discovery.types.ScanPlan` it is
pure arithmetic over the allowlist and the pacing policy.

Two refusals are built in, because a preview that quietly accepts a bad scope is
worse than none:

* A scope larger than :data:`MAX_HOSTS_PER_SCAN` is refused outright. An OT
  segment with four thousand hosts on it is a typo, not a plant.
* A profile that needs a named sign-off says so, and the preview reports
  ``authorized: false`` rather than proceeding to look ready.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Final

from iaiops.core.discovery import identify, wirelog
from iaiops.core.discovery import ports as port_table
from iaiops.core.discovery.profiles import REQUIRES_AUTHORIZATION, get_profile
from iaiops.core.discovery.types import (
    L0_BROADCAST,
    L0_PASSIVE,
    L1_SWEEP,
    L2_IDENTIFY,
    L3_FINGERPRINT,
    L4_BROWSE,
    ScanPlan,
)

#: Hosts one scan may cover. A /22 is already a very large OT segment; beyond
#: this the operator almost certainly mistyped a prefix length.
MAX_HOSTS_PER_SCAN: Final = 4096

#: Prefix lengths shorter than this need an explicit acknowledgement on the plan.
LARGE_SCOPE_PREFIX: Final = 16

#: Which packet classes each stage may emit. This is what the preview promises,
#: and the wire log is what the report proves — the two are compared in the
#: report's trust section, so a stage that emits something unlisted is visible.
STAGE_EMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    L0_PASSIVE: (),
    L0_BROADCAST: (wirelog.UDP_BROADCAST_WHOIS, wirelog.L2_DCP_IDENTIFY),
    L1_SWEEP: (wirelog.TCP_CONNECT,),
    # DERIVED from the probe table, never listed by hand. A hand-written list
    # drifts the moment a probe is added or removed, and this preview is the
    # document an operator signs — it has to describe the code that will run,
    # not the code that ran when someone last edited this constant.
    L2_IDENTIFY: identify.identify_emissions(),
    L3_FINGERPRINT: (
        wirelog.MODBUS_FC43,
        wirelog.S7_CPU_INFO,
        wirelog.EIP_LIST_IDENTITY,
        wirelog.MC_CPU_STATUS,
        wirelog.MTCONNECT_PROBE,
    ),
    L4_BROWSE: (
        wirelog.OPCUA_SESSION,
        wirelog.OPCUA_BROWSE,
        wirelog.BACNET_OBJECT_LIST,
        wirelog.IOLINK_HTTP,
    ),
}


class ScopeTooLarge(ValueError):
    """The host list is implausible for an OT segment — almost certainly a typo."""


@dataclass(frozen=True)
class Scope:
    """The expanded host list, and what was dropped getting there."""

    hosts: tuple[str, ...]
    #: Network and broadcast addresses removed automatically, per CIDR.
    structural_exclusions: tuple[str, ...]
    #: Addresses the operator excluded.
    operator_exclusions: tuple[str, ...]

    @property
    def host_count(self) -> int:
        return len(self.hosts)


def expand_scope(plan: ScanPlan) -> Scope:
    """Expand CIDRs and explicit hosts into the host list a sweep would visit.

    Network and broadcast addresses are dropped automatically: they are not
    devices, and a broadcast address is the one address a scan must never
    connect to. The default gateway is NOT excluded automatically — we cannot
    know it without reading the route table, which is an L0 concern; exclude it
    explicitly if the plant wants it left alone.
    """
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in plan.cidrs:
        net = ipaddress.ip_network(raw.strip(), strict=False)
        if net.prefixlen < LARGE_SCOPE_PREFIX and not plan.accept_large_scope:
            raise ScopeTooLarge(
                f"{raw} is a /{net.prefixlen}: {net.num_addresses:,} addresses. "
                "An OT segment this size is nearly always a mistyped prefix. If you "
                "really mean it, set accept_large_scope on the plan — and expect the "
                f"{MAX_HOSTS_PER_SCAN}-host cap to apply anyway."
            )
        networks.append(net)

    excluded_nets = [
        ipaddress.ip_network(raw.strip(), strict=False)
        for raw in plan.excluded
        if raw.strip() and "/" in raw
    ]
    excluded_singles = {raw.strip() for raw in plan.excluded if raw.strip() and "/" not in raw}

    # Size the scope from address arithmetic BEFORE expanding it. A /8 holds 16.7M
    # addresses; materialising those just to discover they exceed the cap is slow
    # on a laptop and an out-of-memory on an edge box.
    projected = sum(
        max(0, net.num_addresses - (2 if net.num_addresses > 2 else 0)) for net in networks
    )
    projected += len([h for h in plan.hosts if h.strip()])
    projected -= sum(net.num_addresses for net in excluded_nets)
    projected -= len(excluded_singles)
    if projected > MAX_HOSTS_PER_SCAN:
        raise ScopeTooLarge(
            f"{projected:,} hosts exceeds the {MAX_HOSTS_PER_SCAN:,}-host cap for one "
            "scan. Split the scope — a smaller run you can reason about beats one "
            "nobody reviews."
        )

    structural: list[str] = []
    collected: list[str] = []
    for net in networks:
        if net.num_addresses > 2:
            structural.extend([str(net.network_address), str(net.broadcast_address)])
            collected.extend(str(ip) for ip in net.hosts())
        else:
            # /31 and /32 have no host range to speak of.
            collected.extend(str(ip) for ip in net)

    collected.extend(h.strip() for h in plan.hosts if h.strip())

    excluded: set[str] = set(excluded_singles)
    for net in excluded_nets:
        excluded.update(str(ip) for ip in net)

    seen: dict[str, None] = {}
    for host in collected:
        if host not in excluded:
            seen.setdefault(host, None)

    hosts = tuple(seen)
    if len(hosts) > MAX_HOSTS_PER_SCAN:  # pragma: no cover - projection is exact
        raise ScopeTooLarge(f"{len(hosts):,} hosts exceeds the {MAX_HOSTS_PER_SCAN:,}-host cap.")

    return Scope(
        hosts=hosts,
        structural_exclusions=tuple(structural),
        operator_exclusions=tuple(sorted(excluded)),
    )


def resolve_ports(plan: ScanPlan) -> tuple[port_table.IndustrialPort, ...]:
    """The exact ports this plan would connect to.

    Precedence is narrowing-only: explicit ports ⊂ protocol hints ⊂ profile
    default set ⊂ allowlist. Nothing here can introduce a port the allowlist
    does not already contain.
    """
    profile = get_profile(plan.profile)
    # Driven by the PROFILE alone. Letting a hint flip this on is how "scan only
    # MTConnect" quietly starts connecting to 80 and 8080 — ports the allowlist
    # itself marks as ambiguous with IT. A hint narrows; the profile decides how
    # far the run may reach.
    candidates = port_table.sweepable_ports(include_optional=profile.include_optional_ports)

    if plan.protocols:
        allowed = {p.port for p in port_table.ports_for_protocols(plan.protocols)}
        if not allowed:
            sweepable = sorted({n for e in port_table.ALLOWLIST for n in e.protocols})
            # The narrowing primitive returns an empty set for a name it does not
            # serve; at plan level that must be loud. Silently resolving to no
            # ports skips the sweep, and the run then blames the operator's VLAN
            # for a silence a typo — or a UDP-only protocol — actually caused.
            raise ValueError(
                f"protocols {list(plan.protocols)} match no sweepable TCP port. "
                "Either the name is misspelled, or the protocol is not reachable by "
                "a TCP sweep at all: BACnet, FINS and HART are UDP and are found by "
                "broadcast or by an operator-supplied address, not by this stage. "
                f"Sweepable names: {sweepable}."
            )
        candidates = tuple(p for p in candidates if p.port in allowed)
        if not candidates:
            _refuse_opt_in(sorted(allowed), profile.name, f"protocols {list(plan.protocols)}")

    if plan.ports:
        requested = set(plan.ports)
        not_allowlisted = sorted(p for p in requested if not port_table.is_allowlisted(p))
        if not_allowlisted:
            reasons = {
                p: port_table.NEVER_SCAN[p] for p in not_allowlisted if p in port_table.NEVER_SCAN
            }
            detail = f" Forbidden: {reasons}." if reasons else ""
            raise ValueError(
                f"ports {not_allowlisted} are not on the industrial allowlist and cannot "
                f"be scanned.{detail} A port hint may only narrow the allowlist."
            )
        before = candidates
        candidates = tuple(p for p in candidates if p.port in requested)
        if not candidates and before:
            _refuse_opt_in(sorted(requested), profile.name, f"ports {sorted(requested)}")

    return candidates


def _refuse_opt_in(ports: list[int], profile_name: str, asked_for: str) -> None:
    """Explain an empty port set instead of sweeping nothing and reporting a sweep.

    Reached when every port a hint selected is opt-in and the profile is not.
    Opt-in ports are ambiguous with IT services or can disturb a third party, so
    reaching them is a profile decision, never a side effect of naming a
    protocol.
    """
    detail = ", ".join(
        f"{port} ({entry.note})" if (entry := port_table.describe_port(port)) else str(port)
        for port in ports
    )
    raise ValueError(
        f"{asked_for} resolves only to opt-in ports under the {profile_name!r} profile, "
        f"so there is nothing this run may sweep: {detail}. A hint may narrow the "
        "profile's port set, never widen it — choose a profile that includes the "
        "opt-in ports (e.g. 'deep') if you mean to touch them."
    )


def _worst_case_seconds(host_count: int, port_count: int, plan: ScanPlan) -> dict[str, float]:
    """Two independent bounds; the run is limited by whichever is slower.

    Deliberately worst-case: it assumes every probe times out, because that is
    the number an operator needs before agreeing to a maintenance window.
    """
    pacing = plan.pacing
    connects = host_count * port_count

    rate_bound = connects / pacing.connects_per_second if connects else 0.0

    # Each host's ports are probed one at a time, spaced by the host gap.
    per_host = port_count * (pacing.connect_timeout_s + pacing.per_host_gap_ms / 1000.0)
    serial_bound = (host_count * per_host) / max(1, pacing.max_concurrency)

    return {
        "rate_bound_s": round(rate_bound, 1),
        "host_serialization_bound_s": round(serial_bound, 1),
        "worst_case_s": round(max(rate_bound, serial_bound), 1),
    }


def plan_preview(plan: ScanPlan) -> dict[str, Any]:
    """The zero-emission artifact. Nothing in here touches the network."""
    profile = get_profile(plan.profile)
    scope = expand_scope(plan)
    ports = resolve_ports(plan)
    stages = plan.stages or profile.stages

    needs_auth = plan.profile.strip().lower() in REQUIRES_AUTHORIZATION
    emissions = {stage: list(STAGE_EMISSIONS.get(stage, ())) for stage in stages}
    connects = scope.host_count * len(ports) if L1_SWEEP in stages else 0

    return {
        "emits_packets": plan.emits_packets,
        "profile": {
            "name": profile.name,
            "summary": profile.summary,
            "stages": list(stages),
        },
        "authorization": {
            "required": needs_auth,
            "recorded": plan.authorization.recorded,
            "approved_by": plan.authorization.approved_by,
            "ticket": plan.authorization.ticket,
            "valid_until": plan.authorization.valid_until,
            "authorized": (not needs_auth) or plan.authorization.recorded,
        },
        "scope": {
            "cidrs": list(plan.cidrs),
            "explicit_hosts": list(plan.hosts),
            "host_count": scope.host_count,
            "hosts_preview": list(scope.hosts[:20]),
            "structural_exclusions": list(scope.structural_exclusions),
            "operator_exclusions": list(scope.operator_exclusions),
        },
        "ports": [
            {
                "port": p.port,
                "transport": p.transport,
                "may_identify": list(p.protocols),
                "note": p.note,
            }
            for p in ports
        ],
        "stage_emissions": emissions,
        "estimates": {
            "tcp_connects": connects,
            **_worst_case_seconds(scope.host_count, len(ports), plan),
            "note": (
                "Worst case assumes every probe times out. A responsive segment "
                "finishes far sooner."
            ),
        },
        "pacing": {
            "connects_per_second": plan.pacing.connects_per_second,
            "max_concurrency": plan.pacing.max_concurrency,
            "per_host_gap_ms": plan.pacing.per_host_gap_ms,
            "one_probe_in_flight_per_host": True,
            "connect_timeout_s": plan.pacing.connect_timeout_s,
        },
        "will_not_do": list(wirelog.NEVER_DONE),
        "forbidden_ports": {
            str(port): reason for port, reason in sorted(port_table.NEVER_SCAN.items())
        },
        "never_identified": dict(port_table.NEVER_IDENTIFIED),
    }


def preview_text(plan: ScanPlan) -> str:
    """The same preview as signable plain text, for a maintenance-window email."""
    data = plan_preview(plan)
    scope = data["scope"]
    est = data["estimates"]
    auth = data["authorization"]

    lines = [
        "SCAN PREVIEW — nothing has been sent to the network to produce this.",
        "",
        f"Profile          : {data['profile']['name']} — {data['profile']['summary']}",
        f"Stages           : {', '.join(data['profile']['stages'])}",
        f"Hosts in scope   : {scope['host_count']}",
        f"Ports per host   : {len(data['ports'])}  "
        f"({', '.join(str(p['port']) for p in data['ports']) or 'none'})",
        f"TCP connects     : {est['tcp_connects']:,} (worst case)",
        f"Worst-case time  : {est['worst_case_s']:,.0f}s — {est['note']}",
        f"Rate             : {data['pacing']['connects_per_second']:g}/s, "
        f"concurrency {data['pacing']['max_concurrency']}, "
        f"one probe in flight per host",
        "Authorization    : "
        + (
            "not required for this profile"
            if not auth["required"]
            else (f"{auth['approved_by']} / {auth['ticket']}" if auth["recorded"] else "MISSING")
        ),
        "",
        "This scan will NOT:",
    ]
    lines += [f"  · {item}" for item in data["will_not_do"]]
    if scope["structural_exclusions"]:
        lines += [
            "",
            "Automatically excluded (network / broadcast addresses):",
            "  " + ", ".join(scope["structural_exclusions"]),
        ]
    return "\n".join(lines)


__all__ = [
    "MAX_HOSTS_PER_SCAN",
    "LARGE_SCOPE_PREFIX",
    "STAGE_EMISSIONS",
    "ScopeTooLarge",
    "Scope",
    "expand_scope",
    "resolve_ports",
    "plan_preview",
    "preview_text",
]
