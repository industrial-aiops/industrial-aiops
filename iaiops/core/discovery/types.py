"""Pure types for site discovery — scan plans, results, and pacing policy.

No I/O lives here, so the whole scan surface (what would be touched, at what
rate, with what verdict) is testable without a network. That matters more than
usual for this feature: the artifact a plant's controls engineer signs off on is
produced entirely from these types, before a single packet exists.

Two deliberate choices:

* **Findings are never merged.** ``refused`` and ``filtered`` are different
  verdicts with different diagnoses (a refused port means the host is *alive*
  and simply is not running that service; a filtered one usually means an ACL
  dropped the packet). Collapsing them into "closed" is how a scan report starts
  lying to the person holding it.
* **An empty result is a verdict, not an empty list.** :class:`ScanResult`
  carries a ``verdict`` so "found nothing" always arrives with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

# --- scan stages -----------------------------------------------------------
# Ordered least-invasive first. A profile selects a prefix of this ladder.
L0_PASSIVE: Final = "L0_passive"  # local ARP/route tables, operator import — zero packets
L0_BROADCAST: Final = "L0_broadcast"  # one broadcast frame (BACnet Who-Is, PROFINET DCP)
L1_SWEEP: Final = "L1_sweep"  # TCP connect→close on the allowlist
L2_IDENTIFY: Final = "L2_identify"  # one minimal in-spec read per candidate protocol
L3_FINGERPRINT: Final = "L3_fingerprint"  # vendor/model/firmware/serial identity read
L4_BROWSE: Final = "L4_browse"  # address-space walk — per-device opt-in only

STAGE_ORDER: Final[tuple[str, ...]] = (
    L0_PASSIVE,
    L0_BROADCAST,
    L1_SWEEP,
    L2_IDENTIFY,
    L3_FINGERPRINT,
    L4_BROWSE,
)

# --- port verdicts ---------------------------------------------------------
PORT_OPEN: Final = "open"
PORT_REFUSED: Final = "refused"  # host is ALIVE, nothing listening on this port
PORT_FILTERED: Final = "filtered"  # timeout — usually an ACL silently dropping

# --- scan verdicts ---------------------------------------------------------
VERDICT_OK: Final = "ok"
VERDICT_PARTIAL: Final = "partial"
VERDICT_NO_DEVICES: Final = "no_devices_found"
VERDICT_ABORTED_UNHEALTHY: Final = "aborted_unhealthy_segment"

# --- confidence ------------------------------------------------------------
#: The protocol answered a spec-conformant identify call.
CONF_CONFIRMED: Final = "confirmed"
#: The port is open and allowlisted to this protocol, but nothing confirmed it.
#: The report must say "probably X, unconfirmed" and never invent a vendor.
CONF_PORT_ONLY: Final = "port_only"


@dataclass(frozen=True)
class PacingPolicy:
    """Rate and concurrency limits. Defaults are deliberately timid.

    The hard caps are not configuration — they are the ceiling a caller cannot
    raise, so an operator in a hurry cannot turn this into a flood.
    """

    connects_per_second: float = 20.0
    max_concurrency: int = 4
    #: Minimum gap between two probes of the SAME host. One in-flight probe per
    #: host is enforced separately; this spaces them out on top of that.
    per_host_gap_ms: int = 250
    #: Gap between two identify calls to the same host (heavier than a connect).
    identify_gap_ms: int = 500
    connect_timeout_s: float = 1.5
    #: Consecutive timeouts against one host before it is dropped for this run.
    host_backoff_after: int = 3
    #: Consecutive errors across the whole segment before the run aborts.
    segment_abort_after: int = 50

    # ClassVar, NOT Final: a bare `Final` annotation still makes a dataclass
    # FIELD, which would let a caller pass HARD_MAX_CPS=9999 and raise its own
    # ceiling — exactly the thing this class promises is impossible. Pinned by
    # test_ceilings_are_class_constants_not_overridable_fields.
    HARD_MAX_CPS: ClassVar[float] = 100.0
    HARD_MAX_CONCURRENCY: ClassVar[int] = 16

    def __post_init__(self) -> None:
        if not 0 < self.connects_per_second <= self.HARD_MAX_CPS:
            raise ValueError(
                f"connects_per_second must be in (0, {self.HARD_MAX_CPS}] — "
                f"got {self.connects_per_second}. This ceiling is not configurable: "
                "aggressive sweeps fault legacy PLCs."
            )
        if not 0 < self.max_concurrency <= self.HARD_MAX_CONCURRENCY:
            raise ValueError(
                f"max_concurrency must be in (0, {self.HARD_MAX_CONCURRENCY}] — "
                f"got {self.max_concurrency}."
            )
        if self.per_host_gap_ms < 0 or self.identify_gap_ms < 0:
            raise ValueError("gaps must be non-negative")
        if self.connect_timeout_s <= 0:
            raise ValueError("connect_timeout_s must be positive")


@dataclass(frozen=True)
class Authorization:
    """Who signed off on this scan. Embedded in the artifact and printed first.

    Cheap to carry, and it is the difference between a tool an OT team accepts
    and one that gets banned after the first surprise.
    """

    approved_by: str = ""
    ticket: str = ""
    valid_until: str = ""

    @property
    def recorded(self) -> bool:
        return bool(self.approved_by.strip())


@dataclass(frozen=True)
class ScanPlan:
    """Everything a scan will do, decided before anything is emitted."""

    site: str = ""
    cidrs: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    #: Protocol hints. May only NARROW the port set, never widen it.
    protocols: tuple[str, ...] = ()
    #: Explicit ports. Must be a subset of the allowlist; validated at build time.
    ports: tuple[int, ...] = ()
    profile: str = "inventory"
    stages: tuple[str, ...] = (L0_PASSIVE, L1_SWEEP, L2_IDENTIFY)
    pacing: PacingPolicy = field(default_factory=PacingPolicy)
    authorization: Authorization = field(default_factory=Authorization)
    #: Deterministic host-order shuffle. A marching sweep hammers one switch's
    #: port group and reads as an attack; a seeded shuffle stays reproducible.
    seed: int = 0
    #: Devices explicitly opted in to the L4 address-space walk.
    allow_browse: tuple[str, ...] = ()

    def with_stages(self, stages: tuple[str, ...]) -> ScanPlan:
        unknown = [s for s in stages if s not in STAGE_ORDER]
        if unknown:
            raise ValueError(f"unknown scan stages: {unknown}")
        return ScanPlan(**{**self.__dict__, "stages": stages})

    @property
    def emits_packets(self) -> bool:
        """False only when the plan is L0-passive — the true zero-emission case."""
        return any(s != L0_PASSIVE for s in self.stages)


@dataclass(frozen=True)
class PortResult:
    port: int
    state: str  # PORT_OPEN | PORT_REFUSED | PORT_FILTERED
    rtt_ms: float | None = None


@dataclass(frozen=True)
class ProtocolCandidate:
    protocol: str
    confidence: str  # CONF_CONFIRMED | CONF_PORT_ONLY
    #: What actually justified this — e.g. "fc43_identity", "tcp_open".
    evidence: str
    detail: str = ""


@dataclass(frozen=True)
class HostResult:
    ip: str
    #: How this host came to our attention: "arp", "tcp", "broadcast", "import".
    sources: tuple[str, ...] = ()
    mac: str = ""
    ports: tuple[PortResult, ...] = ()
    protocols: tuple[ProtocolCandidate, ...] = ()
    identity: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    @property
    def alive(self) -> bool:
        """A refused port proves liveness just as well as an open one."""
        return bool(self.mac) or any(p.state in (PORT_OPEN, PORT_REFUSED) for p in self.ports)


@dataclass(frozen=True)
class ScanResult:
    """The outcome. ``verdict`` is always set — an empty scan explains itself."""

    plan: ScanPlan
    hosts: tuple[HostResult, ...] = ()
    verdict: str = VERDICT_OK
    #: Counts of every packet class actually emitted, e.g. {"tcp_connect": 1524}.
    wire_summary: dict[str, int] = field(default_factory=dict)
    #: Operator-facing diagnosis when nothing was found, or why a run aborted.
    notes: tuple[str, ...] = ()
    started_at: str = ""
    finished_at: str = ""

    @property
    def devices(self) -> tuple[HostResult, ...]:
        return tuple(h for h in self.hosts if h.protocols)


__all__ = [
    "L0_PASSIVE",
    "L0_BROADCAST",
    "L1_SWEEP",
    "L2_IDENTIFY",
    "L3_FINGERPRINT",
    "L4_BROWSE",
    "STAGE_ORDER",
    "PORT_OPEN",
    "PORT_REFUSED",
    "PORT_FILTERED",
    "VERDICT_OK",
    "VERDICT_PARTIAL",
    "VERDICT_NO_DEVICES",
    "VERDICT_ABORTED_UNHEALTHY",
    "CONF_CONFIRMED",
    "CONF_PORT_ONLY",
    "PacingPolicy",
    "Authorization",
    "ScanPlan",
    "PortResult",
    "ProtocolCandidate",
    "HostResult",
    "ScanResult",
]
