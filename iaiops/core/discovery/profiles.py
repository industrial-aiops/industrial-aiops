"""Scan profiles — named safety postures, from "emits nothing" to "opt-in deep".

A profile is the one knob an operator should have to think about. It fixes the
stage ladder, the port set, and the pacing together, so a cautious posture
cannot be half-applied (slow rate but deep stages, say).

``inventory`` is the default deliberately: it finds and identifies devices
without ever walking an address space, which is the answer to "what is on this
network" that a first visit actually needs.

``legacy-safe`` exists for the case that decides whether this product is
trusted: a line of 1990s controllers where even a well-formed identify request
is a risk. It sweeps only, one host at a time, five connects a second.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from iaiops.core.discovery.types import (
    L0_BROADCAST,
    L0_PASSIVE,
    L1_SWEEP,
    L2_IDENTIFY,
    L3_FINGERPRINT,
    L4_BROWSE,
    PacingPolicy,
)


@dataclass(frozen=True)
class ScanProfile:
    name: str
    stages: tuple[str, ...]
    pacing: PacingPolicy
    #: Include the opt-in ports (HTTP-ish, MQTT) as well as the defaults.
    include_optional_ports: bool
    summary: str


PROFILES: Final[dict[str, ScanProfile]] = {
    "passive": ScanProfile(
        name="passive",
        stages=(L0_PASSIVE,),
        pacing=PacingPolicy(),
        include_optional_ports=False,
        summary=(
            "Emits nothing. Reads the local ARP/route tables and any inventory you "
            "import. The honest starting point on a network you do not own yet."
        ),
    ),
    "inventory": ScanProfile(
        name="inventory",
        stages=(L0_PASSIVE, L1_SWEEP, L2_IDENTIFY),
        pacing=PacingPolicy(),
        include_optional_ports=False,
        summary=(
            "Default. Finds hosts and identifies which industrial protocol each "
            "speaks, using one minimal in-spec read per candidate. Never walks an "
            "address space."
        ),
    ),
    "standard": ScanProfile(
        name="standard",
        stages=(L0_PASSIVE, L1_SWEEP, L2_IDENTIFY, L3_FINGERPRINT),
        pacing=PacingPolicy(),
        include_optional_ports=False,
        summary=(
            "Adds vendor/model/firmware/serial identity reads to the inventory "
            "profile. Requires a recorded authorization."
        ),
    ),
    "deep": ScanProfile(
        name="deep",
        stages=(
            L0_PASSIVE,
            L0_BROADCAST,
            L1_SWEEP,
            L2_IDENTIFY,
            L3_FINGERPRINT,
            L4_BROWSE,
        ),
        pacing=PacingPolicy(connects_per_second=10.0, max_concurrency=2),
        include_optional_ports=True,
        summary=(
            "Everything, including the address-space walk — but L4 still runs only "
            "for devices named individually in allow_browse. There is no browse-all. "
            "Requires a recorded authorization."
        ),
    ),
    "legacy-safe": ScanProfile(
        name="legacy-safe",
        stages=(L0_PASSIVE, L1_SWEEP),
        pacing=PacingPolicy(
            connects_per_second=5.0,
            max_concurrency=1,
            per_host_gap_ms=3000,
            connect_timeout_s=3.0,
            host_backoff_after=2,
        ),
        include_optional_ports=False,
        summary=(
            "For fragile 1990s-era controllers. Reachability only — NO protocol "
            "identify at all, one host at a time, five connects a second. Tells you "
            "what is listening, and nothing more."
        ),
    ),
}

DEFAULT_PROFILE: Final = "inventory"

#: Profiles whose stages can disturb more than a TCP handshake, and so must
#: carry a named sign-off before they run.
REQUIRES_AUTHORIZATION: Final[frozenset[str]] = frozenset({"standard", "deep"})


def get_profile(name: str) -> ScanProfile:
    """Look up a profile, with a teaching error listing the real options."""
    key = (name or DEFAULT_PROFILE).strip().lower()
    profile = PROFILES.get(key)
    if profile is None:
        options = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown scan profile {name!r}. Available: {options}.")
    return profile


def profile_menu() -> tuple[dict[str, str], ...]:
    """Human-facing list of profiles, for the CLI and the report appendix."""
    return tuple(
        {
            "name": p.name,
            "stages": ", ".join(p.stages),
            "rate": f"{p.pacing.connects_per_second:g}/s, concurrency {p.pacing.max_concurrency}",
            "authorization": "required" if p.name in REQUIRES_AUTHORIZATION else "not required",
            "summary": p.summary,
        }
        for p in PROFILES.values()
    )


__all__ = [
    "ScanProfile",
    "PROFILES",
    "DEFAULT_PROFILE",
    "REQUIRES_AUTHORIZATION",
    "get_profile",
    "profile_menu",
]
