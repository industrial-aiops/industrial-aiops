"""Site discovery — find what is on a plant network, as gently as possible.

Everything above the connectors already assumes you know your endpoints. This
package answers the question that comes *before* that one: point it at a subnet
and it reports what is there, what each device probably speaks, and — only when
asked — what points it exposes.

The whole design is organised around one fact: **aggressive active scanning of
an OT network is a documented way to fault legacy PLCs.** So the scanner has no
full-port mode, no raw sockets, no half-open SYNs, no malformed frames, and no
write path of any kind. What it may touch is a fixed allowlist
(:mod:`iaiops.core.discovery.ports`), how fast is capped by a policy the caller
cannot raise past a hard ceiling (:class:`~iaiops.core.discovery.types.PacingPolicy`),
and how deep is a named posture (:mod:`iaiops.core.discovery.profiles`) whose
timid end emits nothing at all.

Read :mod:`iaiops.core.discovery.ports` first — it documents, per port, why the
identify call for that protocol is the one that cannot disturb the device.
"""

from __future__ import annotations

from iaiops.core.discovery.ports import (
    ALLOWLIST,
    NEVER_IDENTIFIED,
    NEVER_SCAN,
    IndustrialPort,
    is_allowlisted,
    ports_for_protocols,
    sweepable_ports,
)
from iaiops.core.discovery.preview import (
    MAX_HOSTS_PER_SCAN,
    Scope,
    ScopeTooLarge,
    expand_scope,
    plan_preview,
    preview_text,
    resolve_ports,
)
from iaiops.core.discovery.profiles import (
    DEFAULT_PROFILE,
    PROFILES,
    REQUIRES_AUTHORIZATION,
    ScanProfile,
    get_profile,
    profile_menu,
)
from iaiops.core.discovery.sweep import (
    ProbeOutcome,
    diagnose_empty_sweep,
    probe_port,
    sweep_hosts,
)
from iaiops.core.discovery.types import (
    CONF_CONFIRMED,
    CONF_PORT_ONLY,
    PORT_FILTERED,
    PORT_OPEN,
    PORT_REFUSED,
    VERDICT_ABORTED_UNHEALTHY,
    VERDICT_NO_DEVICES,
    VERDICT_OK,
    VERDICT_PARTIAL,
    Authorization,
    HostResult,
    PacingPolicy,
    PortResult,
    ProtocolCandidate,
    ScanPlan,
    ScanResult,
)

__all__ = [
    "ALLOWLIST",
    "NEVER_SCAN",
    "NEVER_IDENTIFIED",
    "IndustrialPort",
    "sweepable_ports",
    "ports_for_protocols",
    "is_allowlisted",
    "PROFILES",
    "DEFAULT_PROFILE",
    "REQUIRES_AUTHORIZATION",
    "ScanProfile",
    "get_profile",
    "profile_menu",
    "MAX_HOSTS_PER_SCAN",
    "Scope",
    "ScopeTooLarge",
    "expand_scope",
    "resolve_ports",
    "plan_preview",
    "preview_text",
    "ProbeOutcome",
    "probe_port",
    "sweep_hosts",
    "diagnose_empty_sweep",
    "PacingPolicy",
    "Authorization",
    "ScanPlan",
    "PortResult",
    "ProtocolCandidate",
    "HostResult",
    "ScanResult",
    "PORT_OPEN",
    "PORT_REFUSED",
    "PORT_FILTERED",
    "VERDICT_OK",
    "VERDICT_PARTIAL",
    "VERDICT_NO_DEVICES",
    "VERDICT_ABORTED_UNHEALTHY",
    "CONF_CONFIRMED",
    "CONF_PORT_ONLY",
]
