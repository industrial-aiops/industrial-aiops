"""Who feeds whom on this line — stated by a person, never inferred.

HLD §10.3② and D25. Relations are the **second axis** of root-cause analysis.
`_proximity_scale` weighs evidence by TIME alone (cause before effect), and time
alone cannot tell "caused" from "was caused by": when a press stops, everything
downstream of it stops too, so a purely temporal ranker produces a string of
equally-confident downstream false causes.

**Why this is a declaration and not a detector.** That same correlation is what
makes inference unsafe here — on a line, downstream co-occurrence is guaranteed
whatever the cause. D25 therefore allows timestamp co-occurrence to produce
*candidates a person confirms*, never edges. The one source that needs no
inference at all is somebody stating the order the line runs in, and that is what
this module stores.

Stored in the site knowledge base as ``declared`` facts — the right fit here,
unlike an investigation (an activity record): an edge is a durable fact about
the plant, and a person is its evidence (D23).

[PURE-ish] Reads and writes one site file. No device, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from iaiops.core.brain._shared import s
from iaiops.core.knowledge.model import DECLARED, Fact, KnowledgeBase
from iaiops.core.knowledge.store import load, save

KIND = "relation"
MAX_NAME = 96
#: A line long enough to exceed this is a line nobody declared by hand.
MAX_EDGES = 500

__all__ = [
    "Relation",
    "declare_relation",
    "forget_relation",
    "line_relations",
    "downstream_of",
]


@dataclass(frozen=True)
class Relation:
    """One declared edge: ``upstream`` feeds ``downstream``."""

    upstream: str
    downstream: str
    by: str
    source: str = DECLARED

    @property
    def key(self) -> str:
        return _key(self.upstream, self.downstream)


def _key(upstream: str, downstream: str) -> str:
    return f"{KIND}.{upstream}->{downstream}"


def _clean(name: str, what: str) -> str:
    text = s(str(name or "").strip(), MAX_NAME)
    if not text:
        raise ValueError(f"An {what} asset name is required — a relation needs both ends.")
    return text


def line_relations(site: str = "default", base_dir: Path | None = None) -> tuple[Relation, ...]:
    """Every declared edge for this site, in declaration order."""
    return tuple(
        Relation(
            upstream=str(fact.value.get("upstream", "")),
            downstream=str(fact.value.get("downstream", "")),
            by=str(fact.value.get("by", "")),
            source=fact.source,
        )
        for fact in load(site, base_dir).facts
        if fact.kind == KIND and isinstance(fact.value, dict)
    )


def declare_relation(
    upstream: str,
    downstream: str,
    by: str,
    site: str = "default",
    base_dir: Path | None = None,
) -> Relation:
    """Record that ``upstream`` feeds ``downstream``. Refuses shapes that mislead."""
    up = _clean(upstream, "upstream")
    down = _clean(downstream, "downstream")
    who = s(str(by or "").strip(), MAX_NAME)
    if not who:
        # The trust model rests entirely on a person having said it. An edge with
        # no author is indistinguishable from an inferred one a year later, which
        # is exactly the confusion D25 exists to prevent.
        raise ValueError("Say who declared this relation (`--by`): a person is the evidence.")
    if up == down:
        raise ValueError(f"{up!r} cannot feed itself.")

    existing = line_relations(site, base_dir)
    if any(r.upstream == down and r.downstream == up for r in existing) or _reaches(
        existing, down, up
    ):
        raise ValueError(
            f"{up!r} → {down!r} would close a cycle: {down!r} already reaches {up!r} "
            "downstream. A line that feeds itself makes 'downstream' meaningless."
        )
    if len(existing) >= MAX_EDGES and not _has_edge(existing, up, down):
        raise ValueError(f"This site already has {MAX_EDGES} declared relations.")

    kb = load(site, base_dir)
    # Re-declaring is how a correction is made: drop the old edge, keep the new
    # author. The audit chain holds both, so the change is not lost.
    kept = tuple(f for f in kb.facts if not (f.kind == KIND and f.key == _key(up, down)))
    relation = Relation(upstream=up, downstream=down, by=who)
    save(
        KnowledgeBase(site=kb.site, facts=kept).with_facts(
            Fact(
                kind=KIND,
                key=relation.key,
                value={"upstream": up, "downstream": down, "by": who},
                source=DECLARED,
                note=f"{up} feeds {down}; declared by {who}",
            )
        ),
        base_dir,
    )
    return relation


def forget_relation(
    upstream: str, downstream: str, site: str = "default", base_dir: Path | None = None
) -> bool:
    """Withdraw an edge. Returns False when there was none — not an error."""
    up, down = _clean(upstream, "upstream"), _clean(downstream, "downstream")
    kb = load(site, base_dir)
    kept = tuple(f for f in kb.facts if not (f.kind == KIND and f.key == _key(up, down)))
    if len(kept) == len(kb.facts):
        return False
    save(KnowledgeBase(site=kb.site, facts=kept), base_dir)
    return True


def downstream_of(
    asset: str, site: str = "default", base_dir: Path | None = None
) -> tuple[str, ...]:
    """Everything ``asset`` feeds, directly or through others — NEAREST FIRST.

    Nearest first because that is the order somebody walks the line in. Never
    upward: the direction is the entire content of the fact, and a symmetric
    answer would place a cause downstream of its own effect.
    """
    start = s(str(asset or "").strip(), MAX_NAME)
    if not start:
        return ()
    return _walk(line_relations(site, base_dir), start)


def _has_edge(relations: tuple[Relation, ...], up: str, down: str) -> bool:
    return any(r.upstream == up and r.downstream == down for r in relations)


def _reaches(relations: tuple[Relation, ...], start: str, target: str) -> bool:
    return target in _walk(relations, start)


def _walk(relations: tuple[Relation, ...], start: str) -> tuple[str, ...]:
    """Breadth-first so the result is ordered by distance, with a seen-set.

    The seen-set is belt and braces: `declare_relation` refuses cycles, but this
    also runs over a file a person may have hand-edited, and an unterminated walk
    inside an incident tool is the worst possible place to find that out.
    """
    edges: dict[str, list[str]] = {}
    for relation in relations:
        edges.setdefault(relation.upstream, []).append(relation.downstream)
    seen, order, frontier = {start}, [], [start]
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            for child in edges.get(node, ()):
                if child in seen:
                    continue
                seen.add(child)
                order.append(child)
                nxt.append(child)
        frontier = nxt
    return tuple(order)
