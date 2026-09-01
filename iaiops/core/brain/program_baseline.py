"""Approved-program snapshots and drift — persistence and the flows around it.

The pure parts live next door: :mod:`iaiops.core.brain.plc_program.fingerprint`
builds a storable structural fingerprint of an exported program, and
:mod:`iaiops.core.brain.plc_program.drift` compares two. This module owns the
small validated save/load boundary and the flows the MCP tools and the
``iaiops program`` CLI share, following the :mod:`alias_store` /
:mod:`baseline_store` conventions: one owner-only JSON file under the iaiops home
(``<home>/program_baselines.json``, 0600, atomic temp+replace).

Two decisions worth stating, because both could reasonably have gone the other
way.

**The key is a name, not a path.** The same program gets exported to a new
directory every time somebody opens the engineering station, and keying on the
path would file each export as a different program and never find any drift.
Absent ``--name`` the file's stem is used and the result says so, because
inferring an identity silently is how a comparison ends up being made against
the wrong program.

**Nothing is pruned.** A change-control history that quietly drops last
quarter's baseline is worse than one that grows; a snapshot stores block names,
hashes and counts — never a declaration, a source line or a comment — so growth
is slow and the store is not a second copy of the program. Removal is offered
(:func:`forget`) and never imposed — the same rule the scan store follows.

No device is ever touched. This reads a file that a person exported.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.brain.plc_program import drift as dr
from iaiops.core.brain.plc_program import fingerprint as fp
from iaiops.core.brain.plc_program.outline import load_program, outline_program
from iaiops.core.governance.paths import ops_home

STORE_FILENAME = "program_baselines.json"
_FORMAT_VERSION = 1

MAX_LABEL = 80
MAX_NOTE = 500
#: Guard against a store that grows without anyone noticing. Not a retention
#: policy — hitting it is an error telling you to `program forget`, not a silent
#: deletion of the oldest evidence.
MAX_SNAPSHOTS_PER_PROGRAM = 500


class ProgramNotTrackedError(LookupError):
    """Raised when no snapshot has ever been taken for a program name."""


class SnapshotNotFoundError(LookupError):
    """Raised when a snapshot id is not in a tracked program's history."""


# ─── persistence boundary ─────────────────────────────────────────────────────


def store_path(base_dir: Path | None = None) -> Path:
    """The program-baseline store — ``<home>/program_baselines.json``."""
    base = Path(base_dir) if base_dir is not None else ops_home()
    return base / STORE_FILENAME


def load_store(base_dir: Path | None = None) -> dict:
    """Load the store; missing file → an empty store (not an error)."""
    path = store_path(base_dir)
    if not path.exists():
        return {"version": _FORMAT_VERSION, "programs": {}}
    try:
        payload = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Program-baseline store at {path} is not valid JSON ({exc}). Move it "
            "aside and re-take the baseline snapshot of the approved version."
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("programs"), dict):
        raise ValueError(
            f"Program-baseline store at {path} is malformed (missing a 'programs' "
            "object). Move it aside and re-take the baseline snapshot."
        )
    return payload


def save_store(store: dict, base_dir: Path | None = None) -> Path:
    """Persist the store atomically with owner-only perms; returns the path."""
    if not isinstance(store, dict) or not isinstance(store.get("programs"), dict):
        raise ValueError("save_store expects a {version, programs:{...}} store dict.")
    path = store_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:  # best effort on exotic filesystems
        pass
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=2, sort_keys=True), "utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    return path


def _copy(value: Any) -> Any:
    """A deep, JSON-safe copy — live store references are never handed out."""
    return json.loads(json.dumps(value))


def _program(store: dict, name: str) -> dict:
    raw = store["programs"].get(name)
    return _copy(raw) if isinstance(raw, dict) else {"snapshots": []}


def _with_program(store: dict, name: str, record: dict) -> dict:
    """A NEW store with ``name``'s record replaced (inputs never mutated)."""
    return {
        **store,
        "version": _FORMAT_VERSION,
        "programs": {**store["programs"], name: record},
    }


# ─── flows ────────────────────────────────────────────────────────────────────


def _default_name(path: Path) -> str:
    return path.stem or path.name


def _now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def fingerprint_file(path: str) -> dict[str, Any]:
    """Parse an exported program and fingerprint it — no store involved."""
    resolved, text, _fmt = load_program(path)
    outline = outline_program(path)
    return {
        "source_file": str(resolved),
        "content_sha256": fp.content_sha256(text),
        "fingerprint": fp.fingerprint_outline(outline),
    }


def take_snapshot(
    path: str,
    name: str | None = None,
    label: str = "",
    note: str = "",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Record the current state of an exported program as a snapshot.

    Re-snapshotting an unchanged file is not an error and does not add a row —
    the answer to "has it changed" is no, and a history padded with identical
    entries hides the ones that are not.
    """
    resolved = Path(path).expanduser()
    key = s(str(name or _default_name(resolved)).strip(), 96)
    if not key:
        raise ValueError("A program name cannot be empty.")

    taken = fingerprint_file(path)
    store = load_store(base_dir)
    record = _program(store, key)
    snapshots = record.get("snapshots") or []

    if snapshots and snapshots[-1].get("content_sha256") == taken["content_sha256"]:
        return {
            "status": "unchanged",
            "program": key,
            "name_source": "given" if name else "filename stem",
            "matches_snapshot": snapshots[-1]["snapshot_id"],
            "content_sha256": taken["content_sha256"],
            "snapshot_count": len(snapshots),
            "note": "Byte-identical to the latest snapshot — nothing recorded.",
        }
    if len(snapshots) >= MAX_SNAPSHOTS_PER_PROGRAM:
        raise ValueError(
            f"{key!r} already has {len(snapshots)} snapshots (limit "
            f"{MAX_SNAPSHOTS_PER_PROGRAM}). Nothing was deleted — run "
            f"`iaiops program forget --name {key} --keep N` to trim deliberately."
        )

    snapshot = {
        "snapshot_id": f"{key}-{len(snapshots) + 1:04d}",
        "taken_at": _now(),
        "source_file": taken["source_file"],
        "content_sha256": taken["content_sha256"],
        "label": s(str(label or ""), MAX_LABEL),
        "note": s(str(note or ""), MAX_NOTE),
        "fingerprint": taken["fingerprint"],
    }
    new_record = {**record, "snapshots": [*snapshots, snapshot]}
    save_store(_with_program(store, key, new_record), base_dir)
    return {
        "status": "recorded",
        "program": key,
        "name_source": "given" if name else "filename stem",
        "snapshot": {k: v for k, v in snapshot.items() if k != "fingerprint"},
        "block_count": snapshot["fingerprint"]["block_count"],
        "snapshot_count": len(snapshots) + 1,
        "previous_snapshot": snapshots[-1]["snapshot_id"] if snapshots else None,
    }


def _snapshots_or_raise(store: dict, name: str) -> list[dict]:
    record = _program(store, name)
    snapshots = record.get("snapshots") or []
    if not snapshots:
        known = ", ".join(sorted(store["programs"])) or "(none)"
        raise ProgramNotTrackedError(
            f"No snapshots for program {name!r}. Take one from the version you "
            f"consider approved: `iaiops program snapshot <file> --name {name}`. "
            f"Tracked programs: {known}."
        )
    return snapshots


def _pick(snapshots: list[dict], snapshot_id: str | None) -> dict:
    if snapshot_id is None:
        return snapshots[-1]
    for snap in snapshots:
        if snap.get("snapshot_id") == snapshot_id:
            return snap
    known = ", ".join(snap.get("snapshot_id", "") for snap in snapshots)
    raise SnapshotNotFoundError(f"No snapshot {snapshot_id!r}. Known: {known}.")


def check_drift(
    path: str,
    name: str | None = None,
    against: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Compare an exported program against a stored snapshot (default: latest)."""
    resolved = Path(path).expanduser()
    key = s(str(name or _default_name(resolved)).strip(), 96)
    store = load_store(base_dir)
    baseline = _pick(_snapshots_or_raise(store, key), against)
    current = fingerprint_file(path)

    result = dr.compare(
        baseline["fingerprint"],
        current["fingerprint"],
        before_sha256=baseline["content_sha256"],
        after_sha256=current["content_sha256"],
    )
    return {
        "program": key,
        "name_source": "given" if name else "filename stem",
        "baseline": {
            "snapshot_id": baseline["snapshot_id"],
            "taken_at": baseline["taken_at"],
            "label": baseline.get("label", ""),
            "source_file": baseline.get("source_file", ""),
        },
        "current": {"source_file": current["source_file"]},
        **result,
    }


def compare_snapshots(
    name: str,
    before: str,
    after: str,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Compare two stored snapshots of the same program."""
    snapshots = _snapshots_or_raise(load_store(base_dir), name)
    b, a = _pick(snapshots, before), _pick(snapshots, after)
    result = dr.compare(
        b["fingerprint"],
        a["fingerprint"],
        before_sha256=b["content_sha256"],
        after_sha256=a["content_sha256"],
    )
    return {
        "program": name,
        "baseline": {k: b.get(k) for k in ("snapshot_id", "taken_at", "label")},
        "current": {k: a.get(k) for k in ("snapshot_id", "taken_at", "label")},
        **result,
    }


def history(name: str | None = None, base_dir: Path | None = None) -> dict[str, Any]:
    """Every tracked program, or one program's snapshot history."""
    store = load_store(base_dir)
    if name is None:
        return {
            "store": str(store_path(base_dir)),
            "program_count": len(store["programs"]),
            "programs": [
                {
                    "program": key,
                    "snapshot_count": len(rec.get("snapshots") or []),
                    "latest": (rec.get("snapshots") or [{}])[-1].get("snapshot_id"),
                    "latest_taken_at": (rec.get("snapshots") or [{}])[-1].get("taken_at"),
                }
                for key, rec in sorted(store["programs"].items())
            ],
        }
    snapshots = _snapshots_or_raise(store, name)
    return {
        "store": str(store_path(base_dir)),
        "program": name,
        "snapshot_count": len(snapshots),
        "snapshots": [{k: v for k, v in snap.items() if k != "fingerprint"} for snap in snapshots],
    }


def forget(name: str, keep: int = 0, base_dir: Path | None = None) -> dict[str, Any]:
    """Drop a program's history, optionally keeping the ``keep`` most recent."""
    if keep < 0:
        raise ValueError("keep must be >= 0.")
    store = load_store(base_dir)
    snapshots = _snapshots_or_raise(store, name)
    kept = snapshots[-keep:] if keep else []
    programs = {**store["programs"]}
    if kept:
        programs[name] = {**_program(store, name), "snapshots": kept}
    else:
        programs.pop(name, None)
    save_store({**store, "version": _FORMAT_VERSION, "programs": programs}, base_dir)
    return {
        "program": name,
        "removed": len(snapshots) - len(kept),
        "kept": [snap["snapshot_id"] for snap in kept],
        "still_tracked": name in programs,
    }


__all__ = [
    "MAX_SNAPSHOTS_PER_PROGRAM",
    "STORE_FILENAME",
    "ProgramNotTrackedError",
    "SnapshotNotFoundError",
    "check_drift",
    "compare_snapshots",
    "fingerprint_file",
    "forget",
    "history",
    "load_store",
    "save_store",
    "store_path",
    "take_snapshot",
]
