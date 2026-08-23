"""Removing expired raw samples — carefully, and never before their value is out.

Two rules make this safe rather than merely cheap.

**You cannot prune data whose value has not been extracted.** Deleting samples
that were never summarized loses the information permanently and silently, so a
window is prunable only once it has been SEALED — derived facts computed and
stored. ``sealed_before`` is that watermark, and the effective cutoff is the
EARLIER of it and the policy: the policy says what may go, the seal says what has
been finished with, and only their intersection is safe.

**Pruning is a dry run by default.** Deleting history is irreversible and the
default must not do it, which is the same discipline the write path already
follows (``preview_param`` in ``@governed_tool``).

Afterwards, a question about a period whose raw data is gone gets a refusal
rather than an estimate — see :func:`raw_available_from`. Re-deriving from
surviving fragments would produce something that looks like a measurement, is
computed over a fraction of the window, and is quite possibly flattering: prune
the samples covering a stoppage and availability goes UP.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from iaiops.core.retain.policy import RetentionPolicy


def _resolve(db_path: Any) -> Path:
    from iaiops.core.sink.sqlite_local import local_db_path

    return Path(db_path).expanduser() if db_path else local_db_path()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _cutoff(policy: RetentionPolicy, now: datetime, sealed_before: datetime | None) -> datetime:
    """The earlier of "old enough to expire" and "finished with"."""
    by_policy = now - timedelta(days=policy.raw_days)
    if sealed_before is None:
        return by_policy
    return min(by_policy, sealed_before)


def plan_prune(
    db_path: Any,
    policy: RetentionPolicy,
    now: datetime | None = None,
    sealed_before: datetime | None = None,
) -> dict[str, Any]:
    """What a prune WOULD remove. Touches nothing."""
    now = now or datetime.now(UTC)
    path = _resolve(db_path)
    cutoff = _cutoff(policy, now, sealed_before)
    empty = {
        "cutoff": cutoff.isoformat(),
        "raw_days": policy.raw_days,
        "rows_to_remove": 0,
        "rows_to_keep": 0,
        "oldest": "",
        "note": policy.summary,
    }
    if not path.exists():
        return {**empty, "note": "No local store yet — nothing to prune."}

    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(ts) FROM samples WHERE ts < ?", (cutoff.isoformat(),)
        ).fetchone()
        keep = conn.execute(
            "SELECT COUNT(*) FROM samples WHERE ts >= ?", (cutoff.isoformat(),)
        ).fetchone()
    except sqlite3.DatabaseError:
        return empty
    finally:
        conn.close()

    return {
        **empty,
        "rows_to_remove": int(row[0] or 0),
        "rows_to_keep": int(keep[0] or 0),
        "oldest": str(row[1] or ""),
    }


def prune(
    db_path: Any,
    policy: RetentionPolicy,
    now: datetime | None = None,
    sealed_before: datetime | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Remove expired, SEALED raw samples. Dry run unless ``apply`` is true.

    Refuses outright when nothing has been sealed: with no watermark there is no
    evidence that anything was ever summarized, and deleting on that basis would
    destroy the only copy of an unanswered question.
    """
    now = now or datetime.now(UTC)
    planned = plan_prune(db_path, policy, now=now, sealed_before=sealed_before)

    if apply and sealed_before is None:
        return {
            **planned,
            "status": "refused",
            "applied": False,
            "rows_removed": 0,
            "reason": (
                "Nothing has been sealed. Raw samples may only be removed once their "
                "value has been extracted into derived facts — otherwise the deletion "
                "silently destroys the only record of a period nobody has looked at. "
                "Derive first, then prune with the seal watermark."
            ),
        }

    if not apply:
        return {
            **planned,
            "status": "planned",
            "applied": False,
            "rows_removed": 0,
            "reason": "Dry run — pass apply=True to remove. Deleting history is irreversible.",
        }

    path = _resolve(db_path)
    if not path.exists():
        return {**planned, "status": "ok", "applied": True, "rows_removed": 0, "rows_kept": 0}

    conn = _connect(path)
    try:
        cur = conn.execute("DELETE FROM samples WHERE ts < ?", (planned["cutoff"],))
        removed = cur.rowcount
        conn.commit()
        kept = int(conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] or 0)
        conn.execute("VACUUM")
    finally:
        conn.close()

    return {
        **planned,
        "status": "ok",
        "applied": True,
        "rows_removed": int(removed),
        "rows_kept": kept,
    }


def raw_available_from(db_path: Any, when: datetime) -> dict[str, Any]:
    """Whether raw samples still exist back to ``when``.

    The guard against a quietly-wrong answer. Analysis of a period whose samples
    have expired must refuse rather than compute over the remainder — a figure
    derived from fragments looks like a measurement and can only mislead. The
    refusal names the earliest raw data that survives, so the answer is "ask me
    about X onwards" rather than a flat no.
    """
    path = _resolve(db_path)
    if not path.exists():
        return {"available": False, "earliest_raw": "", "reason": "No local store yet."}

    conn = _connect(path)
    try:
        earliest = conn.execute("SELECT MIN(ts) FROM samples").fetchone()[0]
    except sqlite3.DatabaseError:
        earliest = None
    finally:
        conn.close()

    if not earliest:
        return {"available": False, "earliest_raw": "", "reason": "The local store is empty."}

    if str(earliest) <= when.isoformat():
        return {"available": True, "earliest_raw": str(earliest), "reason": ""}

    return {
        "available": False,
        "earliest_raw": str(earliest),
        "reason": (
            f"Raw samples before {earliest} have been pruned under the retention policy. "
            "Analysis of that period is refused rather than computed from what survived — "
            "a figure over a fraction of a window looks like a measurement and is not one. "
            "Derived facts from that period remain and can answer instead."
        ),
    }


__all__ = ["plan_prune", "prune", "raw_available_from"]
