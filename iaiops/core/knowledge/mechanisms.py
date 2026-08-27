"""A mountable fault-mechanism library — the slot step 07 was missing.

HLD §13.8. Until now the knowledge check reported ``expressible=False``: fault
mechanisms were hardcoded constants and there was no way to mount anything. This
is the slot, and its shape comes from what the field standardised rather than
from what would be convenient.

**ISO 14224's three levels, kept apart.** The standard separates the failure
MODE (the observed effect — "reading frozen"), the failure MECHANISM (the
physical process — "transmitter drift") and the failure CAUSE (the root
condition). This repo's seven ``CAUSE_KEYWORDS`` collapse all three into one
word, which is fine for ranking and useless for a knowledge check: the three
answer different questions — what you SAW, what to go and CHECK, what to FIX.

**Seven top-level causes is the right number and this does not add to them.**
Practitioner consensus is blunt: past roughly forty codes two operators stop
picking the same one and the data degrades. An entry *attaches to* a taxonomy
cause; it never invents one. (The large commercial failure-code libraries are
for machine-emitted codes, where nobody has to choose — a different layer.)

Four things it may never do, in order of the damage each would cause:

1. **Silence is not agreement.** Nothing known about a candidate produces
   ``nothing_known``, never "no objection". That reading is the flattering one
   and would make this step worse than not having it.
2. **It may exclude, never confirm** (D28/D29). Applicability constraints can
   rule a candidate out — the strong move a ranker cannot make. Raising one to
   ``confirmed`` still has to come from outside: a measurement, a reproduction,
   or a person.
3. **Every entry says where it came from.** A mechanism with no source is
   indistinguishable from a guess a year later.
4. **All-or-nothing mounting.** A half-mounted library is one nobody can reason
   about.

[PURE-ish] Reads a YAML file and one site file. No device, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.knowledge.model import DECLARED, Fact, KnowledgeBase
from iaiops.core.knowledge.store import load, save

KIND = "mechanism"
MAX_TEXT = 240
#: A hand-curated library is small by design; see the note on forty codes above.
MAX_ENTRIES = 200

NOTHING_KNOWN = "nothing_known"
KNOWN = "known"

__all__ = [
    "Mechanism",
    "load_library",
    "mount_library",
    "mounted_mechanisms",
    "check_candidate",
    "NOTHING_KNOWN",
    "KNOWN",
]


@dataclass(frozen=True)
class Mechanism:
    """One way a cause shows up, and where that knowledge came from."""

    cause: str
    mechanism: str
    mode: str
    source: str
    by: str
    protocols: tuple[str, ...] = ()
    excluded_when: tuple[str, ...] = ()
    confirm_by: tuple[str, ...] = ()

    def applies_to(self, protocol: str) -> bool:
        """Absence of a constraint is NOT a constraint.

        Reading "no protocols listed" as "applies to no protocol" would silently
        exclude every unconstrained entry — turning the most general knowledge
        into the least usable.
        """
        if not self.protocols:
            return True
        return str(protocol or "").strip().lower() in self.protocols

    def as_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "mechanism": self.mechanism,
            "mode": self.mode,
            "source": self.source,
            "by": self.by,
            "protocols": list(self.protocols),
            "excluded_when": list(self.excluded_when),
            "confirm_by": list(self.confirm_by),
        }


def load_library(path: Path | str) -> dict[str, Any]:
    """Read and shape-check a library file. Raises rather than half-loading."""
    import yaml

    file = Path(path).expanduser()
    if not file.exists():
        raise FileNotFoundError(f"No mechanism library at {file}.")
    raw = yaml.safe_load(file.read_text("utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("mechanisms"), list):
        raise ValueError(
            f"{file} is not a mechanism library: it needs a top-level 'mechanisms' list."
        )
    return raw


def mount_library(
    path: Path | str, by: str, site: str = "default", base_dir: Path | None = None
) -> dict[str, Any]:
    """Validate a library and store its entries as ``declared`` facts.

    All or nothing: one bad entry refuses the whole file, because a half-mounted
    library is one nobody can reason about.
    """
    from iaiops.core.brain.rca import KNOWN_CAUSES

    who = s(str(by or "").strip(), MAX_TEXT)
    if not who:
        raise ValueError("Say who is mounting this (`--by`): a source without an owner is a guess.")

    raw = load_library(path)
    source = s(str(raw.get("source", "")).strip(), MAX_TEXT)
    if not source:
        raise ValueError(
            "The library needs a 'source' — which manual, standard or bulletin this "
            "came from. A mechanism with no source is indistinguishable from a guess."
        )

    entries = list(raw["mechanisms"])[: MAX_ENTRIES + 1]
    if len(entries) > MAX_ENTRIES:
        raise ValueError(f"A mounted library is capped at {MAX_ENTRIES} entries.")

    parsed = [_entry(item, source, who, KNOWN_CAUSES) for item in entries]

    kb = load(site, base_dir)
    kept = tuple(f for f in kb.facts if f.kind != KIND)
    save(
        KnowledgeBase(site=kb.site, facts=kept).with_facts(
            *(
                Fact(
                    kind=KIND,
                    key=f"{KIND}.{m.cause}.{m.mechanism}",
                    value=m.as_dict(),
                    source=DECLARED,
                    note=f"{m.cause}: {m.mechanism} — from {source}, mounted by {who}",
                )
                for m in parsed
            )
        ),
        base_dir,
    )
    return {"mounted": len(parsed), "source": source, "by": who, "site": kb.site}


def mounted_mechanisms(
    site: str = "default", base_dir: Path | None = None
) -> tuple[Mechanism, ...]:
    """Everything mounted for this site."""
    return tuple(
        Mechanism(
            cause=str(f.value.get("cause", "")),
            mechanism=str(f.value.get("mechanism", "")),
            mode=str(f.value.get("mode", "")),
            source=str(f.value.get("source", "")),
            by=str(f.value.get("by", "")),
            protocols=tuple(f.value.get("protocols") or ()),
            excluded_when=tuple(f.value.get("excluded_when") or ()),
            confirm_by=tuple(f.value.get("confirm_by") or ()),
        )
        for f in load(site, base_dir).facts
        if f.kind == KIND and isinstance(f.value, dict)
    )


def check_candidate(
    cause: str, protocol: str = "", site: str = "default", base_dir: Path | None = None
) -> dict[str, Any]:
    """What the mounted library has to say about one candidate cause.

    Three outcomes, and the difference between the first two is the whole point:

    ``nothing_known``
        The library has no entry for this cause. **Not** "no objection" — a
        knowledge base that has never heard of something has not cleared it.
    ``known`` with ``excluded=False``
        There are mechanisms for it here, and what would confirm each.
    ``known`` with ``excluded=True``
        Every mechanism for this cause is inapplicable to this equipment, so the
        candidate can be ruled out — the strong move (D28) a ranker cannot make.

    It never returns ``confirmed`` (D29): a library entry is inside the ranking,
    and confirmation has to come from outside it.
    """
    key = str(cause or "").strip()
    entries = [m for m in mounted_mechanisms(site, base_dir) if m.cause == key]
    if not entries:
        return {
            "cause": key,
            "status": NOTHING_KNOWN,
            "excluded": False,
            "supports": [],
            "confirm_by": [],
            "reason": (
                "the mounted library has no entry for this cause — nothing is known "
                "about it here, which is not the same as nothing being wrong with it"
            ),
        }

    applicable = [m for m in entries if m.applies_to(protocol)]
    if not applicable:
        allowed = sorted({p for m in entries for p in m.protocols})
        return {
            "cause": key,
            "status": KNOWN,
            "excluded": True,
            "supports": [],
            "confirm_by": [],
            "reason": (
                f"every mounted mechanism for {key!r} applies only to "
                f"{', '.join(allowed)} — not to {protocol or 'this endpoint'}"
            ),
        }
    return {
        "cause": key,
        "status": KNOWN,
        "excluded": False,
        "supports": [
            {"mechanism": m.mechanism, "mode": m.mode, "source": m.source} for m in applicable
        ],
        "confirm_by": sorted({step for m in applicable for step in m.confirm_by}),
        "reason": f"{len(applicable)} mounted mechanism(s) apply here",
    }


def _entry(item: Any, source: str, by: str, known_causes: Any) -> Mechanism:
    if not isinstance(item, dict):
        raise ValueError(f"Each mechanism must be a mapping; got {type(item).__name__}.")
    cause = s(str(item.get("cause", "")).strip(), MAX_TEXT)
    if cause not in known_causes:
        raise ValueError(
            f"Unknown cause {cause or '(missing)'!r}. A library attaches to the "
            f"taxonomy the learner already speaks: {', '.join(sorted(known_causes))}."
        )
    mechanism = s(str(item.get("mechanism", "")).strip(), MAX_TEXT)
    mode = s(str(item.get("mode", "")).strip(), MAX_TEXT)
    if not mechanism or not mode:
        raise ValueError(
            f"{cause!r} needs both 'mechanism' (the physical process to go and check) "
            "and 'mode' (the effect you observed) — ISO 14224 keeps them apart because "
            "they answer different questions."
        )
    applies = item.get("applies_to") or {}
    protocols = tuple(
        str(p).strip().lower() for p in (applies.get("protocols") or ()) if str(p).strip()
    )
    return Mechanism(
        cause=cause,
        mechanism=mechanism,
        mode=mode,
        source=source,
        by=by,
        protocols=protocols,
        excluded_when=tuple(s(str(x), MAX_TEXT) for x in (item.get("excluded_when") or ())),
        confirm_by=tuple(s(str(x), MAX_TEXT) for x in (item.get("confirm_by") or ())),
    )
