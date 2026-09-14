"""What ``iaiops onboard`` computes, as data. No rendering, no I/O.

Two shapes, and the split between them is the whole design:

:class:`OnboardPath` answers *where am I* — one ordered sequence with exactly one
step marked next, derived from what the store and ``config.yaml`` already say.

:class:`Draft` answers *what did the scan establish* — and every field it carries
records WHETHER the scan established it. A drafted value with an empty
``observed`` is not representable: :class:`DraftField` refuses to be built.
That refusal is the point. A config draft is the one artefact where a plausible
default is most dangerous, because it is pasted once and then trusted for years.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Step states. Exactly one step in a path is ``STATE_NEXT`` unless every step
#: is done, in which case none is.
STATE_DONE: str = "done"
STATE_NEXT: str = "next"
STATE_WAITING: str = "waiting"

#: Which journey a site is on. Derived from config.yaml, never remembered.
#: ``devices`` — the data is read straight off PLCs and instruments (no UNS yet,
#: or the site is building one); ``uns`` — the data already flows through an
#: MQTT/UNS broker and iaiops subscribes. ``undecided`` and ``mixed`` are the two
#: states where the files on disk cannot say which question is being asked, and
#: the path asks instead of picking.
TRACK_DEVICES: str = "devices"
TRACK_UNS: str = "uns"
TRACK_UNDECIDED: str = "undecided"
TRACK_MIXED: str = "mixed"


@dataclass(frozen=True)
class Step:
    """One stage of getting a site from nothing to an answer."""

    key: str
    label: str
    #: What was actually observed about this step, either way — "3 endpoints
    #: configured" or "no endpoints in config.yaml". Never a prescription.
    detail: str
    state: str
    #: The command that advances this step, whatever its state — empty only when
    #: no single command does (a Modbus register map is not askable over Modbus).
    #: A front-end shows the next step's; the rest are here so a test can reach
    #: every command this path is able to print.
    command: str = ""
    #: Why this step exists at all, for the reader who has not been told.
    why: str = ""
    #: ``(label, command)`` pairs, set only when the next move is a QUESTION the
    #: files on disk cannot answer — "is this site's data already in a broker?".
    #: Two labelled, mutually exclusive answers to one question are not the "five
    #: commands" the one-next-command rule forbids; guessing one of them would be.
    choices: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "detail": self.detail,
            "state": self.state,
            "command": self.command,
            "why": self.why,
            "choices": [{"label": label, "command": cmd} for label, cmd in self.choices],
        }


@dataclass(frozen=True)
class OnboardPath:
    steps: tuple[Step, ...]
    #: Anything true about this site that changes how the path reads — a config
    #: that will not parse, a role conflict. Never merged into a step's detail,
    #: because a problem that is not on the critical path still has to be seen.
    notes: tuple[str, ...] = ()
    #: One of the ``TRACK_*`` values, and what it was derived from — stated, so a
    #: reader can tell a journey the tool inferred from one they chose.
    track: str = ""
    track_detail: str = ""

    @property
    def next_step(self) -> Step | None:
        return next((s for s in self.steps if s.state == STATE_NEXT), None)

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.state == STATE_DONE)

    def as_dict(self) -> dict[str, Any]:
        nxt = self.next_step
        return {
            "steps": [s.as_dict() for s in self.steps],
            "done": self.done_count,
            "total": len(self.steps),
            "next_command": nxt.command if nxt else "",
            "next_step": nxt.key if nxt else "",
            "notes": list(self.notes),
            "track": self.track,
            "track_detail": self.track_detail,
            "next_choices": [
                {"label": label, "command": cmd} for label, cmd in (nxt.choices if nxt else ())
            ],
        }


@dataclass(frozen=True)
class DraftField:
    """One config line, and the evidence for it — or the absence of evidence.

    ``value is None`` means the scan did not establish this field. Such a field
    is still carried, and still rendered, as a commented line naming what is
    missing: dropping it would let a protocol default apply silently, which is
    the failure mode this whole module exists to prevent (a Modbus gateway read
    at unit 1 answers happily and shows you the wrong machine).
    """

    name: str
    value: Any
    #: What justifies the value. Required whenever there IS a value.
    observed: str = ""
    #: What could still be wrong even though the value is justified.
    caution: str = ""

    def __post_init__(self) -> None:
        if self.value is not None and not self.observed.strip():
            raise ValueError(
                f"draft field {self.name!r} carries a value with no evidence. "
                "Every drafted value must name what the scan observed to justify "
                "it; if nothing did, the value is None and the caution says so."
            )
        if self.value is None and not self.caution.strip():
            raise ValueError(
                f"draft field {self.name!r} has no value and no caution. An "
                "unestablished field must explain what it is waiting for, or a "
                "reader will simply delete the line."
            )

    @property
    def established(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "observed": self.observed,
            "caution": self.caution,
        }


@dataclass(frozen=True)
class DraftEndpoint:
    """One ``endpoints:`` entry a scan can justify."""

    name: str
    protocol: str
    ip: str
    fields: tuple[DraftField, ...]
    #: The scan's own words for why this host is this protocol.
    evidence: str = ""
    #: Set when ``config.yaml`` already has an endpoint by this name. Such an
    #: entry is reported and NOT offered for pasting — a second scan must not
    #: hand someone a block that silently replaces a site's tuned endpoint.
    already_configured: bool = False

    @property
    def open_questions(self) -> tuple[DraftField, ...]:
        return tuple(f for f in self.fields if not f.established)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "protocol": self.protocol,
            "ip": self.ip,
            "evidence": self.evidence,
            "already_configured": self.already_configured,
            "fields": [f.as_dict() for f in self.fields],
        }


@dataclass(frozen=True)
class SkippedHost:
    """A host the scan saw and the draft will not turn into an endpoint."""

    ip: str
    reason: str
    #: The protocols seen on it, confirmed or not, for the reader who expected
    #: this host to appear.
    seen: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"ip": self.ip, "reason": self.reason, "seen": list(self.seen)}


@dataclass(frozen=True)
class Draft:
    scan_id: str
    site: str = ""
    scanned_at: str = ""
    endpoints: tuple[DraftEndpoint, ...] = ()
    skipped: tuple[SkippedHost, ...] = ()
    #: Statements about what this draft cannot contain — the protocols a scan
    #: never identifies, the transports it never sweeps. Absence of a protocol
    #: here is not evidence of its absence at the site, and saying so is not
    #: optional.
    limits: tuple[str, ...] = field(default_factory=tuple)

    @property
    def pastable(self) -> tuple[DraftEndpoint, ...]:
        return tuple(e for e in self.endpoints if not e.already_configured)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "site": self.site,
            "scanned_at": self.scanned_at,
            "endpoints": [e.as_dict() for e in self.endpoints],
            "skipped": [h.as_dict() for h in self.skipped],
            "limits": list(self.limits),
        }


__all__ = [
    "STATE_DONE",
    "STATE_NEXT",
    "STATE_WAITING",
    "TRACK_DEVICES",
    "TRACK_MIXED",
    "TRACK_UNDECIDED",
    "TRACK_UNS",
    "Draft",
    "DraftEndpoint",
    "DraftField",
    "OnboardPath",
    "SkippedHost",
    "Step",
]
