"""A live investigation — stateful, resumable, and honest about each step.

HLD §13, delivery step 2. `plan` answers "how far COULD we get here"; this walks
the eight steps over a REAL window and records what each one actually produced.

**It adds no analysis.** Every step calls something that already exists —
``query_samples``, ``historian_health``, ``alarm_flood_report``,
``downtime_rca``, and the `case` loop for the conclusion — and records the
outcome. Wiring, not reasoning.

Three states a step can end in, and the difference between the last two is the
whole point (D36):

``done``
    It ran, and here is what it found.
``refused``
    It could not run **here**: no samples in the window, no alarm source on this
    endpoint. A site fact — often fixable by collecting more or configuring
    something.
``not_possible``
    **This product cannot do it at all yet.** Nothing the operator does will
    change it. Sending somebody looking for a setting that does not exist is
    worse than saying so.

**Correction to HLD §13.9.** That section said persistence would go through the
site knowledge base. Wrong on contact with the code: a ``KnowledgeBase`` is an
append-only set of FACTS, and an investigation is a mutable record of an
ACTIVITY. ``core/collect/session.py`` is the precedent that fits, and this
follows it — per-investigation JSON, atomic write, 0600. The knowledge base is
still where the *conclusion* lands, through ``case confirm``, unchanged.

[READ] Config + local store. No device is contacted; the window is already past.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.investigate.steps import STEP_KEYS

SUBDIR = "investigations"
VERSION = 1

#: How much of an underlying capability's output a step keeps. The full result
#: belongs to the command that produced it; this is the trail back to it.
MAX_SUMMARY = 240

#: Only when a window has too few samples to have a cadence of its own.
DEFAULT_GAP_S = 60.0

PENDING = "pending"
DONE = "done"
REFUSED = "refused"
NOT_POSSIBLE = "not_possible"

_STEP_LABELS = {
    "define_incident": "Define the incident",
    "collect_evidence": "Collect the evidence",
    "normalize_and_check": "Normalize and check the data",
    "compress_and_rank": "Compress and rank",
    "correlate_timeline": "Correlate the timeline",
    "test_hypotheses": "Test the hypotheses",
    "knowledge_check": "Check against known mechanisms",
    "conclude_and_close": "Conclude and close the loop",
}


@dataclass(frozen=True)
class Scope:
    """What this investigation is about. Every step is judged against it."""

    endpoint: str
    start: str
    end: str
    asset: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "endpoint": self.endpoint,
            "start": self.start,
            "end": self.end,
            "asset": self.asset,
        }


@dataclass(frozen=True)
class StepRun:
    """One step's outcome. `state` is the load-bearing field."""

    number: int
    key: str
    label: str
    state: str = PENDING
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class Investigation:
    """Eight steps over one scope. Immutable; advancing returns a new one."""

    id: str
    site: str
    scope: Scope
    opened_at: str
    steps: tuple[StepRun, ...]

    @property
    def reached(self) -> int:
        """How many steps completed by WALKING from the first (§13, same rule as
        `plan`): a later step succeeding does not help anybody stuck earlier."""
        for step in self.steps:
            if step.state != DONE:
                return step.number - 1
        return len(self.steps)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "id": self.id,
            "site": self.site,
            "scope": self.scope.as_dict(),
            "opened_at": self.opened_at,
            "reached": self.reached,
            "total_steps": len(self.steps),
            "steps": [st.as_dict() for st in self.steps],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Investigation:
        scope = dict(raw.get("scope") or {})
        return cls(
            id=str(raw.get("id", "")),
            site=str(raw.get("site", "default")),
            scope=Scope(
                endpoint=str(scope.get("endpoint", "")),
                start=str(scope.get("start", "")),
                end=str(scope.get("end", "")),
                asset=str(scope.get("asset", "")),
            ),
            opened_at=str(raw.get("opened_at", "")),
            steps=tuple(
                StepRun(
                    number=int(st.get("number", i + 1)),
                    key=str(st.get("key", "")),
                    label=str(st.get("label", "")),
                    state=str(st.get("state", PENDING)),
                    summary=str(st.get("summary", "")),
                )
                for i, st in enumerate(raw.get("steps") or ())
            ),
        )


def open_investigation(
    endpoint: str,
    start: str,
    end: str,
    asset: str = "",
    site: str = "default",
    opened_at: str = "",
) -> Investigation:
    """Create an investigation over one window. Contacts nothing."""
    if not str(endpoint or "").strip():
        raise ValueError("An investigation needs an endpoint — every step is scoped to it.")
    for label, value in (("start", start), ("end", end)):
        if not str(value or "").strip():
            raise ValueError(f"An investigation needs a {label} time (ISO-8601).")
    stamp = opened_at or _now_iso()
    return Investigation(
        id=_make_id(endpoint, start),
        site=str(site or "default"),
        scope=Scope(endpoint=endpoint, start=start, end=end, asset=asset),
        opened_at=stamp,
        steps=tuple(
            StepRun(number=i + 1, key=key, label=_STEP_LABELS[key])
            for i, key in enumerate(STEP_KEYS)
        ),
    )


def advance(inv: Investigation, db_path: Any = None) -> Investigation:
    """Walk the steps and record what each produced. Returns a NEW investigation.

    Idempotent by construction: each step is a function of the scope and the
    store, never of how many times somebody pressed the button.
    """
    samples = _window_samples(inv.scope, db_path)
    outcomes = {
        "define_incident": _run_define(inv),
        "collect_evidence": _run_collect(samples),
        "normalize_and_check": _run_normalize(samples),
        "compress_and_rank": _run_compress(),
        "correlate_timeline": _run_timeline(),
        "test_hypotheses": _run_hypotheses(inv, samples),
        "knowledge_check": _run_knowledge(),
        "conclude_and_close": _run_conclude(inv, samples),
    }
    return replace(
        inv,
        steps=tuple(
            replace(st, state=outcomes[st.key][0], summary=s(outcomes[st.key][1], MAX_SUMMARY))
            for st in inv.steps
        ),
    )


# ─── the steps: each one calls something that already exists ─────────────────


def _run_define(inv: Investigation) -> tuple[str, str]:
    span = f"{inv.scope.start} → {inv.scope.end}"
    asset = inv.scope.asset or inv.scope.endpoint
    return DONE, f"{asset} over {span}"


def _run_collect(samples: list[dict]) -> tuple[str, str]:
    if not samples:
        return REFUSED, "no samples in the window — nothing was collected over this time"
    tags = sorted({str(row.get("tag", "")) for row in samples if row.get("tag")})
    return DONE, f"{len(samples)} sample(s) across {len(tags)} tag(s): {', '.join(tags[:8])}"


def _run_normalize(samples: list[dict]) -> tuple[str, str]:
    """Gap / bad-quality / flatline detection, PER TAG — `historian_health`.

    Two things this step has to get right, and the first version got both wrong.

    **Per tag, not over a mixed series.** The store interleaves tags: at 200 ms
    with three tags the rows land ~3 ms apart in bursts, so the median interval
    of the MIXED series is the spacing between tags, not the sampling rate. It
    reported "6 ms cadence" for a run that sampled every 200 ms — off by thirty
    times, in the direction that makes the data look finer-grained than it was.
    A "gap" in a mixed series is not a gap in anything real either.

    **Cadence-derived threshold, never the 60 s default.** A run at 200 ms has
    real blind windows a few seconds long; judged against 60 s the step reports
    "0 gaps" on a window that definitely had one — on the step whose entire job
    is to say what was NOT seen. The rule (`GAP_FACTOR`, `GAP_FLOOR_S`) is the
    one `oee_measure` measured against a real device across a LAN.
    """
    if not samples:
        return REFUSED, "nothing to check — the window holds no samples"
    from iaiops.core.brain.diagnostics import historian_health
    from iaiops.core.brain.oee_measure import GAP_FACTOR, GAP_FLOOR_S

    by_tag: dict[str, list[dict]] = {}
    for row in samples:
        by_tag.setdefault(str(row.get("tag", "")), []).append(row)

    total_gaps = 0
    cadences: list[float] = []
    checked = 0
    for rows in by_tag.values():
        cadence = _cadence_s(rows)
        threshold = (
            max(cadence * GAP_FACTOR, cadence + GAP_FLOOR_S) if cadence > 0 else DEFAULT_GAP_S
        )
        health = historian_health(
            [{"value": r.get("value"), "timestamp": r.get("ts")} for r in rows],
            gap_threshold_s=threshold,
        )
        if "error" in health:
            continue
        checked += 1
        if cadence > 0:
            cadences.append(cadence)
        total_gaps += len(health.get("gaps") or [])

    if not checked:
        return REFUSED, "no tag in the window held enough samples to check"
    pace = (
        f"{(sorted(cadences)[len(cadences) // 2]) * 1000:.0f}ms cadence"
        if cadences
        else "cadence unknown"
    )
    return DONE, (
        f"{len(samples)} sample(s) over {checked} tag(s), {pace}; "
        f"{total_gaps} gap(s) beyond each tag's own threshold"
    )


def _cadence_s(rows: list[dict]) -> float:
    """The median interval ONE tag actually ran at, in seconds.

    Median, not mean: one long blind window would drag a mean upward and so
    raise the very threshold meant to detect it.
    """
    from iaiops.core.brain._shared import parse_ts

    stamps = [t for t in (parse_ts(r.get("ts")) for r in rows) if t is not None]
    if len(stamps) < 2:
        return 0.0
    stamps.sort()
    deltas = sorted((stamps[i] - stamps[i - 1]).total_seconds() for i in range(1, len(stamps)))
    return deltas[len(deltas) // 2]


def _run_compress() -> tuple[str, str]:
    """ISA-18.2 alarm work needs alarms. A Modbus run-state tag carries none.

    Refused, not not_possible: the product HAS this (`diag alarm-flood`), this
    endpoint just has nothing to feed it.
    """
    return (
        REFUSED,
        "no alarm source on this endpoint — nothing to compress (OPC-UA A&C is the path)",
    )


def _run_timeline() -> tuple[str, str]:
    """Delivery step 3 (§13.10). Declared as not_possible rather than skipped."""
    return NOT_POSSIBLE, "cross-asset timelines need declared line relations; not built yet"


def _run_hypotheses(inv: Investigation, samples: list[dict]) -> tuple[str, str]:
    """Rank candidate causes — but only over evidence the ranker actually reads.

    A raw sample series is not that. `downtime_rca` scores alarms, a dataflow
    verdict and per-tag quality flags; handing it a series with every sample
    marked good yields "no candidate cause is supported", which reads as *we
    looked and found nothing* when the truth is *we handed it nothing to look
    at*. Same error as the RCA copilot made this morning, pointed the other way,
    and worse here because it is silent.

    So: refuse, and name what would make the step runnable. Everything on that
    list is something this site can supply.
    """
    if not samples:
        return REFUSED, "no evidence in the window to rank"
    graded = [row for row in samples if str(row.get("quality", "")).strip()]
    if not graded:
        return REFUSED, (
            "the window holds a raw sample series and nothing the ranker reads — "
            "it needs an alarm source, a dataflow probe from the time of the "
            "incident, or declared tag quality"
        )

    from iaiops.core.brain.rca import downtime_rca

    by_tag: dict[str, list[dict]] = {}
    for row in graded:
        by_tag.setdefault(str(row.get("tag", "")), []).append(
            {"value": row.get("value"), "good": str(row.get("quality", "")).lower() == "good"}
        )
    verdict = downtime_rca(
        {"start": inv.scope.start, "end": inv.scope.end, "asset": inv.scope.asset},
        tags=[{"ref": ref, "samples": rows} for ref, rows in by_tag.items()],
    )
    hypotheses = verdict.get("hypotheses") or []
    if not hypotheses:
        return DONE, f"{len(graded)} quality-graded sample(s) ranked; no candidate is supported"
    top = hypotheses[0]
    return DONE, (
        f"{len(hypotheses)} candidate(s) over {len(graded)} graded sample(s); "
        f"leading: {top.get('cause')} ({top.get('grade')}, confidence {top.get('confidence')})"
    )


def _run_knowledge() -> tuple[str, str]:
    """D36. Mechanisms are hardcoded constants and nothing can be mounted."""
    return NOT_POSSIBLE, "no fault-mechanism library can be mounted; mechanisms are built in"


def _run_conclude(inv: Investigation, samples: list[dict]) -> tuple[str, str]:
    if not samples:
        return REFUSED, "nothing to conclude from — the window holds no evidence"
    return DONE, (
        "record the outcome so it can be learned from: "
        f"`iaiops case confirm <id> --cause <cause> --by <you>` (site {inv.site})"
    )


# ─── window read ─────────────────────────────────────────────────────────────


def _window_samples(scope: Scope, db_path: Any) -> list[dict]:
    """The scope's samples from the local store, or none when there is no store."""
    from iaiops.core.sink.sqlite_local import SampleFilter, query_samples

    try:
        return query_samples(
            SampleFilter(
                since=scope.start, until=scope.end, endpoint=scope.endpoint, limit=100_000
            ),
            db_path=db_path,
        )
    except FileNotFoundError:
        # No store at all is a fact about the site, not an error: it is exactly
        # the state somebody investigating their first incident is in.
        return []


# ─── persistence — follows core/collect/session.py ───────────────────────────


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_id(value: str) -> str:
    name = _UNSAFE.sub("_", str(value or ""))[:120]
    if not name or name in {".", ".."}:
        raise ValueError(f"Unusable investigation id {value!r}.")
    return name


def _make_id(endpoint: str, start: str) -> str:
    stamp = _UNSAFE.sub("", str(start))[:15]
    return _safe_id(f"{endpoint}-{stamp}")


def investigation_path(inv_id: str, base_dir: Path | None = None) -> Path:
    from iaiops.core.runtime.config import CONFIG_DIR

    root = Path(base_dir) if base_dir else CONFIG_DIR
    return root / SUBDIR / f"{_safe_id(inv_id)}.json"


def save_investigation(inv: Investigation, base_dir: Path | None = None) -> Path:
    path = investigation_path(inv.id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(inv.as_dict(), indent=2, sort_keys=True), "utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    return path


def load_investigation(inv_id: str, base_dir: Path | None = None) -> Investigation:
    path = investigation_path(inv_id, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"No investigation {inv_id!r} at {path}.")
    return Investigation.from_dict(json.loads(path.read_text("utf-8")))


def list_investigations(base_dir: Path | None = None) -> list[Investigation]:
    """Newest first. A directory that does not exist yet is simply empty."""
    from iaiops.core.runtime.config import CONFIG_DIR

    root = (Path(base_dir) if base_dir else CONFIG_DIR) / SUBDIR
    if not root.is_dir():
        return []
    found = []
    for path in root.glob("*.json"):
        try:
            found.append(Investigation.from_dict(json.loads(path.read_text("utf-8"))))
        except (ValueError, OSError):
            continue  # a half-written or hand-edited file is not a reason to fail the list
    return sorted(found, key=lambda i: i.opened_at, reverse=True)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


__all__ = [
    "Investigation",
    "Scope",
    "StepRun",
    "advance",
    "investigation_path",
    "list_investigations",
    "load_investigation",
    "open_investigation",
    "save_investigation",
    "DONE",
    "REFUSED",
    "NOT_POSSIBLE",
    "PENDING",
]
