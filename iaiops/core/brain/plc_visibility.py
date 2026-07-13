"""Legacy-PLC visibility profile — a maintainability/risk read over a parsed program.

Sits one level above :mod:`iaiops.core.brain.plc_program`: that package extracts
a cited structural ``ProgramOutline`` from an EXPORTED program (SCL/AWL/L5X);
this module folds that outline into the question an engineer inheriting a legacy
line actually asks — *what am I taking on, and what's risky in it?*

It derives, purely from the outline and always citing file+line/rung:

  * **documentation** — comment coverage + the least-commented blocks.
  * **unreferenced blocks** — blocks no ``call_edge`` targets (dead code, an
    entry OB/task routine, or a call the parser couldn't resolve — flagged
    honestly, never asserted as "dead").
  * **complexity hotspots** — blocks with the most branches/calls/timers.
  * **risky constructs** — unconditional jumps (JMP), retentive timers (RTO),
    and loops (FOR/WHILE/REPEAT) — the constructs that make legacy ladder/ST
    hard to reason about and unsafe to change blindly.
  * **risk** — a transparent additive score/band with a cited reason per point.

Structural only — it anchors an engineer's review, it does not "understand" the
program. Read-only and advisory.
"""

from __future__ import annotations

from iaiops.core.brain.plc_program.model import Block, ProgramOutline

MAX_ROWS = 25
TOP_HOTSPORTS = 10

# Comment-coverage bands (comments / line). Coarse, cited heuristics.
_WELL_COMMENTED = 0.15
_SPARSE_COMMENTED = 0.05

# Block kinds that are legitimate entry points (never flagged as unreferenced).
_ENTRY_KINDS = frozenset({"ORGANIZATION_BLOCK", "PROGRAM"})

# Risk-band thresholds over the additive score (0..100).
_HIGH_RISK = 50
_MEDIUM_RISK = 25


def plc_visibility(outline: ProgramOutline) -> dict:
    """[READ] Fold a parsed ProgramOutline into a cited maintainability/risk profile."""
    blocks = list(outline.blocks)
    called = {e.callee for e in outline.call_edges if e.callee}

    documentation = _documentation(outline, blocks)
    unreferenced = _unreferenced_blocks(blocks, called)
    hotspots = _complexity_hotspots(blocks)
    risky = _risky_constructs(blocks)
    risk = _risk(documentation, unreferenced, risky, hotspots, outline)

    return {
        "source_file": outline.source_file,
        "fmt": outline.fmt,
        "stats": _stats(outline, blocks),
        "documentation": documentation,
        "entry_points": [
            {"name": b.name, "kind": b.kind} for b in blocks if b.kind in _ENTRY_KINDS
        ][:MAX_ROWS],
        "unreferenced_blocks": unreferenced[:MAX_ROWS],
        "complexity_hotspots": hotspots[:TOP_HOTSPORTS],
        "risky_constructs": risky,
        "risk": risk,
        "parse_errors": list(outline.parse_errors)[:MAX_ROWS],
        "note": (
            "Structural extraction only (cite-first): findings anchor a human "
            "review of an exported program, not a semantic understanding. "
            "'unreferenced' may be an entry/task routine or an unresolved call."
        ),
    }


def _stats(outline: ProgramOutline, blocks: list[Block]) -> dict:
    lines = outline.line_count or 0
    comments = outline.comment_count or 0
    return {
        "blocks": len(blocks),
        "call_edges": len(outline.call_edges),
        "line_count": lines,
        "comment_count": comments,
        "comment_ratio": round(comments / lines, 3) if lines else 0.0,
        "variables": sum(len(b.variables) for b in blocks),
        "branches": sum(len(b.branches) for b in blocks),
        "timers_counters": sum(len(b.timers_counters) for b in blocks),
    }


def _documentation(outline: ProgramOutline, blocks: list[Block]) -> dict:
    lines = outline.line_count or 0
    ratio = round((outline.comment_count or 0) / lines, 3) if lines else 0.0
    if not lines:
        band = "unknown"  # nothing to document — never a risk signal
    elif ratio >= _WELL_COMMENTED:
        band = "well_commented"
    elif ratio >= _SPARSE_COMMENTED:
        band = "sparse"
    else:
        band = "undocumented"
    # Blocks carrying no TITLE/description comment — the ones a maintainer lands on blind.
    poorly = [
        {"name": b.name, "kind": b.kind, "source_file": b.source_file, "line": b.line}
        for b in blocks
        if not (b.comment or "").strip()
    ]
    return {
        "comment_ratio": ratio,
        "band": band,
        "uncommented_block_count": len(poorly),
        "uncommented_blocks": poorly[:MAX_ROWS],
    }


def _unreferenced_blocks(blocks: list[Block], called: set[str]) -> list[dict]:
    """Blocks that are not the callee of any edge and are not entry kinds."""
    return [
        {"name": b.name, "kind": b.kind, "source_file": b.source_file, "line": b.line}
        for b in blocks
        if b.name and b.name not in called and b.kind not in _ENTRY_KINDS
    ]


def _block_complexity(b: Block) -> int:
    return len(b.branches) + len(b.calls) + len(b.timers_counters)


def _complexity_hotspots(blocks: list[Block]) -> list[dict]:
    scored = [
        {
            "block": b.name,
            "kind": b.kind,
            "score": _block_complexity(b),
            "branches": len(b.branches),
            "calls": len(b.calls),
            "timers_counters": len(b.timers_counters),
            "source_file": b.source_file,
            "line": b.line,
        }
        for b in blocks
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return [r for r in scored if r["score"] > 0]


def _risky_constructs(blocks: list[Block]) -> dict:
    jumps: list[dict] = []
    loops: list[dict] = []
    retentive: list[dict] = []
    for b in blocks:
        for br in b.branches:
            cite = {"block": b.name, "source_file": br.source_file, "line": br.line}
            if br.kind == "JMP":
                jumps.append(cite)
            elif br.kind in ("FOR", "WHILE", "REPEAT"):
                loops.append({**cite, "kind": br.kind})
        for tc in b.timers_counters:
            if tc.kind == "RTO":
                retentive.append(
                    {
                        "block": b.name,
                        "name": tc.name,
                        "source_file": tc.source_file,
                        "line": tc.line,
                    }
                )
    return {
        "unconditional_jumps": jumps[:MAX_ROWS],
        "unconditional_jump_count": len(jumps),
        "loops": loops[:MAX_ROWS],
        "loop_count": len(loops),
        "retentive_timers": retentive[:MAX_ROWS],
        "retentive_timer_count": len(retentive),
    }


def _risk(
    documentation: dict,
    unreferenced: list[dict],
    risky: dict,
    hotspots: list[dict],
    outline: ProgramOutline,
) -> dict:
    """Transparent additive risk score — every point cites the reason behind it."""
    score = 0
    reasons: list[str] = []

    band = documentation["band"]
    if band == "undocumented":
        score += 30
        reasons.append(f"undocumented (comment ratio {documentation['comment_ratio']})")
    elif band == "sparse":
        score += 15
        reasons.append(f"sparsely commented (comment ratio {documentation['comment_ratio']})")

    if unreferenced:
        pts = min(20, 4 * len(unreferenced))
        score += pts
        reasons.append(f"{len(unreferenced)} unreferenced block(s) (possible dead code)")

    jumps = risky["unconditional_jump_count"]
    if jumps:
        score += min(20, 5 * jumps)
        reasons.append(f"{jumps} unconditional jump(s) (JMP) — non-linear control flow")

    rto = risky["retentive_timer_count"]
    if rto:
        score += min(10, 3 * rto)
        reasons.append(f"{rto} retentive timer(s) (RTO) — state survives power cycle")

    top = hotspots[0]["score"] if hotspots else 0
    if top > 20:
        score += 15
        reasons.append(f"high-complexity block '{hotspots[0]['block']}' (score {top})")
    elif top > 10:
        score += 8
        reasons.append(f"complex block '{hotspots[0]['block']}' (score {top})")

    if outline.parse_errors:
        score += 10
        reasons.append(f"{len(outline.parse_errors)} parse gap(s) — partial visibility")

    score = min(100, score)
    tier = "high" if score >= _HIGH_RISK else "medium" if score >= _MEDIUM_RISK else "low"
    return {"score": score, "band": tier, "reasons": reasons}


__all__ = ["plc_visibility", "MAX_ROWS", "TOP_HOTSPORTS"]
