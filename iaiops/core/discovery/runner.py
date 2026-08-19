"""The scan itself — a plan in, a :class:`ScanResult` out.

Everything this orchestrates already exists and is already honest on its own;
what this module adds is the part that is easy to get wrong once the pieces are
together: **the result must never be quieter than the run was.**

Three rules encode that:

* **A stage that is not implemented says so.** If a plan asks for a stage this
  build cannot run, the result carries a note naming it. Silently running four
  stages when the operator authorised six is how a report comes to claim
  coverage it does not have.
* **An empty result is a verdict with a diagnosis**, never an empty list. "No
  device answered" and "every port was silently dropped" and "the hosts are
  right there and run nothing we speak" are three different findings that look
  identical in a summary.
* **The wire summary is taken from the log, not recomputed.** The trust page
  counts what was actually emitted, including the emissions of probes that
  failed — a page that counted only successes would not be a trust page.

Authorization is enforced here rather than at the CLI, so it cannot be skipped
by calling the library directly.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from iaiops.core.discovery import identify, passive, preview, wirelog
from iaiops.core.discovery.profiles import REQUIRES_AUTHORIZATION, get_profile
from iaiops.core.discovery.sweep import diagnose_empty_sweep, sweep_hosts
from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    L0_BROADCAST,
    L0_PASSIVE,
    L1_SWEEP,
    L2_IDENTIFY,
    L3_FINGERPRINT,
    L4_BROWSE,
    VERDICT_ABORTED_UNHEALTHY,
    VERDICT_NO_DEVICES,
    VERDICT_OK,
    VERDICT_PARTIAL,
    HostResult,
    ScanPlan,
    ScanResult,
)

#: Stages this build does not implement, with what a caller should do instead.
#: Named rather than ignored — see the module docstring.
NOT_IMPLEMENTED: dict[str, str] = {
    L0_BROADCAST: (
        "broadcast discovery (BACnet Who-Is, PROFINET DCP) is not wired into the "
        "scan runner in this build; it needs an operator-named interface"
    ),
    L3_FINGERPRINT: (
        "the deep fingerprint stage is not wired into the scan runner in this "
        "build; L2 already returns vendor/model/serial where the protocol offers it"
    ),
    L4_BROWSE: (
        "the address-space walk is not wired into the scan runner in this build; "
        "it runs per device from the connectors' own browse tools"
    ),
}


class AuthorizationRequired(PermissionError):
    """A profile that can disturb more than a TCP handshake, with no sign-off."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_scan(
    plan: ScanPlan,
    *,
    log: wirelog.WireLog | None = None,
    connector: Callable[..., socket.socket] = socket.create_connection,
    arp_reader: Callable[[], tuple[tuple[Any, ...], tuple[str, ...]]] = passive.read_arp_table,
    clock: Callable[[], str] = _now,
    identify_plan: dict[str, identify.IdentifyProbe] | None = None,
) -> ScanResult:
    """Run ``plan`` and return everything that happened, including what did not.

    Raises :class:`AuthorizationRequired` before emitting anything if the
    profile needs a recorded sign-off and the plan carries none.
    """
    profile = get_profile(plan.profile)
    if profile.name in REQUIRES_AUTHORIZATION and not plan.authorization.recorded:
        raise AuthorizationRequired(
            f"The {profile.name!r} profile does more than open and close TCP "
            "connections, so it requires a recorded authorization. Set "
            "authorization.approved_by (and ideally a ticket) on the plan. "
            "Run the 'inventory' profile, or 'scan plan --dry-run', if you do not "
            "have sign-off yet — neither needs one."
        )

    log = log or wirelog.WireLog()
    started = clock()
    stages = set(plan.stages)
    notes: list[str] = [
        f"{stage} was requested but {reason}"
        for stage, reason in NOT_IMPLEMENTED.items()
        if stage in stages
    ]

    scope = preview.expand_scope(plan)
    ports = [entry.port for entry in preview.resolve_ports(plan)]

    passive_known: tuple[HostResult, ...] = ()
    if L0_PASSIVE in stages:
        entries, arp_notes = arp_reader()
        notes.extend(arp_notes)
        passive_known = passive.passive_hosts(entries, scope=scope.hosts or None)

    swept: tuple[HostResult, ...] = ()
    aborted = False
    if L1_SWEEP in stages and scope.hosts and ports:
        swept, sweep_notes, aborted = sweep_hosts(
            scope.hosts,
            ports,
            pacing=plan.pacing,
            log=log,
            seed=plan.seed,
            connector=connector,
        )
        notes.extend(sweep_notes)

    hosts = passive.merge_passive(swept, passive_known)

    if L2_IDENTIFY in stages and hosts:
        hosts, identify_notes = identify.identify_hosts(
            hosts, log=log, pacing=plan.pacing, plan=identify_plan
        )
        notes.extend(identify_notes)

    if L1_SWEEP in stages:
        notes.extend(diagnose_empty_sweep(hosts))

    hosts = tuple(sorted(hosts, key=_ip_sort_key))
    return ScanResult(
        plan=plan,
        hosts=hosts,
        verdict=_verdict(hosts, aborted),
        wire_summary=log.summary(),
        notes=tuple(dict.fromkeys(notes)),
        started_at=started,
        finished_at=clock(),
    )


def _ip_sort_key(host: HostResult) -> tuple:
    """Numeric where possible, so 10.0.0.9 precedes 10.0.0.10 in the report."""
    parts = host.ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return (0, tuple(int(p) for p in parts))
    return (1, host.ip)


def _verdict(hosts: tuple[HostResult, ...], aborted: bool) -> str:
    """Four outcomes, kept apart because they are acted on differently.

    ``aborted`` is passed in as a flag, not recovered from the notes: a verdict
    that keyed on the word "aborting" appearing in an exception message would
    turn an aborted, possibly plant-disturbing run into a clean "ok" the day
    that message was reworded.
    """
    if aborted:
        return VERDICT_ABORTED_UNHEALTHY
    if any(c.confidence == CONF_CONFIRMED for h in hosts for c in h.protocols):
        return VERDICT_OK
    if any(h.alive for h in hosts):
        # Hosts are demonstrably there; nothing confirmed an industrial protocol.
        # A real and common answer on an IT segment, and not the same thing as
        # finding nothing at all.
        return VERDICT_PARTIAL
    return VERDICT_NO_DEVICES


__all__ = ["NOT_IMPLEMENTED", "AuthorizationRequired", "run_scan"]
