"""A collection run that survives being interrupted — and reports the hole.

The assessment run IS the deployment strategy (D21): a week on a laptop, no
resident process, no change-management request. A week-long run that cannot
survive a closed lid is not a week-long run.

Resuming is the easy half. The half that matters is that **the time between
stopping and resuming is a blind window**, exactly like a dropped connection —
the plant kept running, we were not watching. Stitching the halves into one
continuous series would manufacture a measurement over a window nobody observed,
and in the usual direction: a stoppage that happened while we were away simply
disappears, and availability goes up.

So the deadline is the ORIGINAL end time. "Collect for a week" means a week of
the plant's operation, not a week of our uptime; pausing for twelve hours means
six and a half days were covered, and coverage says so. Extending the finish line
until the sample count looks respectable would be measuring until the answer is
convenient.

[PURE] except for the small validated save/load boundary, which follows the
``alias_store`` conventions like every other store here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from iaiops.core.collect.plan import CollectionPlan

SUBDIR = "sessions"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FORMAT_VERSION = 1

RUNNING = "running"
PAUSED = "paused"
COMPLETED = "completed"


def _parse(ts: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Session:
    """One assessment run, across however many interruptions it takes."""

    run_id: str
    plan: CollectionPlan
    started_at: str
    status: str = RUNNING
    #: Set while paused; cleared on resume. The pair becomes a gap.
    paused_since: str = ""
    #: Blind windows caused by INTERRUPTIONS. Read failures during a run are
    #: tracked separately by the runner; both are blind, for different reasons.
    gaps: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def deadline(self) -> str:
        """When this run ends — fixed at its start, never extended by a pause."""
        start = _parse(self.started_at)
        if start is None:
            return ""
        return (start + timedelta(seconds=self.plan.duration_s)).isoformat()

    def remaining_s(self, now: datetime | None = None) -> float:
        now = now or datetime.now(UTC)
        end = _parse(self.deadline)
        if end is None:
            return 0.0
        return max(0.0, (end - now).total_seconds())

    def is_finished(self, now: datetime | None = None) -> bool:
        return self.status == COMPLETED or self.remaining_s(now) <= 0.0

    @property
    def blind_s(self) -> float:
        """Total time lost to interruptions."""
        return round(sum(float(g.get("seconds", 0.0)) for g in self.gaps), 3)

    def paused_at(self, when: str) -> Session:
        return replace(self, status=PAUSED, paused_since=when)

    def resumed_at(self, when: str) -> Session:
        """Resume, recording the time away as a blind window.

        A resume with no recorded pause adds nothing — there is no evidence of an
        interval anyone was absent for, and inventing one would be as wrong in
        the other direction.
        """
        if not self.paused_since:
            return replace(self, status=RUNNING)
        start, end = _parse(self.paused_since), _parse(when)
        seconds = (end - start).total_seconds() if (start and end) else 0.0
        gap = {
            "from_ts": self.paused_since,
            "to_ts": when,
            "seconds": round(max(0.0, seconds), 3),
            "reason": (
                "collection was interrupted — the line kept running and was not "
                "observed; this is blind time, NOT downtime"
            ),
        }
        return replace(self, status=RUNNING, paused_since="", gaps=self.gaps + (gap,))

    def completed(self) -> Session:
        return replace(self, status=COMPLETED, paused_since="")

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": _FORMAT_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "deadline": self.deadline,
            "paused_since": self.paused_since,
            "blind_s": self.blind_s,
            "gaps": [dict(g) for g in self.gaps],
            "plan": {
                "endpoint": self.plan.endpoint,
                "tags": list(self.plan.tags),
                "duration_s": self.plan.duration_s,
                "interval_ms": self.plan.interval_ms,
            },
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Session:
        if not isinstance(raw, dict):
            raise ValueError(f"A session must be an object, got {type(raw).__name__}.")
        p = raw.get("plan") or {}
        return cls(
            run_id=str(raw.get("run_id", "")),
            plan=CollectionPlan(
                endpoint=str(p.get("endpoint", "")),
                tags=tuple(p.get("tags") or ()),
                duration_s=int(p.get("duration_s", 0)),
                interval_ms=int(p.get("interval_ms", 1000)),
            ),
            started_at=str(raw.get("started_at", "")),
            status=str(raw.get("status", RUNNING)),
            paused_since=str(raw.get("paused_since", "")),
            gaps=tuple(dict(g) for g in (raw.get("gaps") or ())),
        )


def _safe_id(run_id: str) -> str:
    name = str(run_id or "").strip()
    if not _SAFE_ID.match(name):
        raise ValueError(
            f"Run id {run_id!r} must be 1-64 chars of letters, digits, dot, dash or "
            "underscore — it becomes a filename."
        )
    return name


def session_path(run_id: str, base_dir: Path | None = None) -> Path:
    from iaiops.core.runtime.config import CONFIG_DIR

    root = Path(base_dir) if base_dir else CONFIG_DIR
    return root / SUBDIR / f"{_safe_id(run_id)}.json"


def save_session(session: Session, base_dir: Path | None = None) -> Path:
    path = session_path(session.run_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session.as_dict(), indent=2, sort_keys=True), "utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    return path


def load_session(run_id: str, base_dir: Path | None = None) -> Session:
    path = session_path(run_id, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"No collection session {run_id!r} at {path}.")
    return Session.from_dict(json.loads(path.read_text("utf-8")))


def find_resumable(
    endpoint: str, now: datetime | None = None, base_dir: Path | None = None
) -> Session | None:
    """The newest session for ``endpoint`` that still has time left.

    A finished or completed session is never offered: resuming past the deadline
    would extend a run that already answered its question, and the extra samples
    would belong to a window the report does not cover.
    """
    from iaiops.core.runtime.config import CONFIG_DIR

    root = (Path(base_dir) if base_dir else CONFIG_DIR) / SUBDIR
    if not root.exists():
        return None
    now = now or datetime.now(UTC)

    best: Session | None = None
    for path in root.glob("*.json"):
        try:
            candidate = Session.from_dict(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if candidate.plan.endpoint != endpoint or candidate.is_finished(now):
            continue
        if best is None or candidate.started_at > best.started_at:
            best = candidate
    return best


__all__ = [
    "Session",
    "save_session",
    "load_session",
    "find_resumable",
    "session_path",
    "RUNNING",
    "PAUSED",
    "COMPLETED",
]
