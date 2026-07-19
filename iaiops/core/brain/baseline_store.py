"""Baseline + change-log persistence and the learn/check/status flows.

Storage follows the :mod:`alias_store` conventions: one owner-only JSON file
under the iaiops home (``<home>/baselines.json``, 0600, atomic temp+replace),
never a device write. The pure math lives in :mod:`iaiops.core.brain.baseline`;
this module owns (a) the small validated save/load boundary and (b) the flows
shared by the MCP tools and the ``iaiops baseline`` CLI, which read history from
the LOCAL SQLite store (``~/.iaiops/data.db`` — collected data, no device I/O).

Everything returns fresh dicts; the on-disk store is rewritten whole (it is a
per-site metadata file, not a time series) with sorted keys for diff-friendly
output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops.core.brain import baseline as bl
from iaiops.core.brain._shared import s
from iaiops.core.governance.paths import ops_home
from iaiops.core.runtime.envelope import envelope_fields
from iaiops.core.sink.sqlite_local import SampleFilter, query_samples

STORE_FILENAME = "baselines.json"
_FORMAT_VERSION = 1
MAX_CHANGES_PER_TAG = 50  # change log kept bounded (newest wins)
MAX_STATUS_TAGS = 100  # bounded listing for baseline_status
HISTORY_QUERY_LIMIT = bl.MAX_SAMPLES
MIN_CHECK_WINDOW_S = 60.0
MAX_CHECK_WINDOW_S = 7 * 86_400.0


# ─── persistence boundary ─────────────────────────────────────────────────────


def store_path(base_dir: Path | None = None) -> Path:
    """The baselines/change-log store — ``<home>/baselines.json``."""
    base = Path(base_dir) if base_dir is not None else ops_home()
    return base / STORE_FILENAME


def load_store(base_dir: Path | None = None) -> dict:
    """Load the store; missing file → an empty store (not an error)."""
    path = store_path(base_dir)
    if not path.exists():
        return {"version": _FORMAT_VERSION, "tags": {}}
    try:
        payload = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Baseline store at {path} is not valid JSON ({exc}). Move it aside "
            "and re-learn baselines (history in data.db is untouched)."
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("tags"), dict):
        raise ValueError(
            f"Baseline store at {path} is malformed (missing a 'tags' object). "
            "Move it aside and re-learn baselines."
        )
    return payload


def save_store(store: dict, base_dir: Path | None = None) -> Path:
    """Persist the store atomically with owner-only perms; returns the path."""
    if not isinstance(store, dict) or not isinstance(store.get("tags"), dict):
        raise ValueError("save_store expects a {version, tags:{...}} store dict.")
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


def _record(store: dict, tag: str) -> dict:
    """The stored record for a tag (a fresh copy), or an empty record."""
    raw = store["tags"].get(tag)
    if not isinstance(raw, dict):
        return {"baseline": None, "changes": [], "last_learn": None, "last_check": None}
    return json.loads(json.dumps(raw))  # deep, JSON-safe copy — never hand out live refs


def _with_record(store: dict, tag: str, record: dict) -> dict:
    """A NEW store with ``tag``'s record replaced (inputs never mutated)."""
    tags = {**store["tags"], tag: record}
    return {**store, "version": _FORMAT_VERSION, "tags": tags}


def record_change(
    tag: str,
    ts: str | None,
    note: str,
    base_dir: Path | None = None,
) -> dict:
    """Append an operator change-log entry for ``tag`` (bounded, persisted).

    A recorded change marks a regime boundary: the next ``learn`` only uses
    samples AFTER the latest change. ``ts`` defaults to now (UTC). Returns
    ``{tag, change:{ts, note}, changes_recorded}``.
    """
    label = _require_tag(tag)
    text = s(note, 200).strip()
    if not text:
        raise ValueError(
            "note is required — say WHAT changed (e.g. 'setpoint 60→70C', "
            "'replaced pH probe') so the baseline restart is auditable."
        )
    when = _normalize_ts(ts)
    store = load_store(base_dir)
    record = _record(store, label)
    changes = ([*record["changes"], {"ts": when, "note": text}])[-MAX_CHANGES_PER_TAG:]
    save_store(_with_record(store, label, {**record, "changes": changes}), base_dir)
    return {"tag": label, "change": {"ts": when, "note": text}, "changes_recorded": len(changes)}


def _require_tag(tag: Any) -> str:
    label = s(tag, 128).strip()
    if not label:
        raise ValueError("tag is required, e.g. 'line1.temp'.")
    return label


def _normalize_ts(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return datetime.now(UTC).isoformat()
    text = str(raw).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError as exc:
        raise ValueError(
            f"Invalid ts {text!r}: expected ISO-8601, e.g. 2026-07-02T08:00:00."
        ) from exc


# ─── flows shared by the MCP tools and the CLI ────────────────────────────────


def learn_flow(
    tag: str,
    endpoint: str | None = None,
    since: str | None = None,
    base_dir: Path | None = None,
    db_path: Path | str | None = None,
) -> dict:
    """Learn a baseline for ``tag`` from the LOCAL SQLite history and persist it.

    Reads collected samples (no device I/O), segments at the latest recorded
    change, learns via :func:`iaiops.core.brain.baseline.learn_baseline`, and
    stores the band on success — or the explicit refusal (so status can honestly
    report ``learning``). Returns the learn result plus store metadata.
    """
    label = _require_tag(tag)
    samples = query_samples(
        SampleFilter(since=since, endpoint=endpoint, tag=label, limit=HISTORY_QUERY_LIMIT),
        db_path=db_path,
    )
    store = load_store(base_dir)
    record = _record(store, label)
    result = bl.learn_baseline(samples, label, changes=record["changes"])
    learned_at = datetime.now(UTC).isoformat()
    updated = {
        **record,
        "baseline": result if result["status"] == "ok" else record["baseline"],
        "last_learn": {"ts": learned_at, "status": result["status"]},
        # A fresh band supersedes any check verdict made against the old band.
        "last_check": None if result["status"] == "ok" else record["last_check"],
    }
    path = save_store(_with_record(store, label, updated), base_dir)
    return {**result, "endpoint": s(endpoint, 64) or None, "store_path": str(path)}


def check_flow(
    tag: str,
    endpoint: str | None = None,
    window_s: float = 3600.0,
    base_dir: Path | None = None,
    db_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict:
    """Check the last ``window_s`` of local history against the stored baseline.

    No stored baseline → an explicit ``no_baseline`` answer (never a guess).
    Persists the check verdict so ``status_flow`` can report ``violation``.
    """
    label = _require_tag(tag)
    window = float(window_s)
    if not MIN_CHECK_WINDOW_S <= window <= MAX_CHECK_WINDOW_S:
        raise ValueError(
            f"window_s must be {MIN_CHECK_WINDOW_S:.0f}..{MAX_CHECK_WINDOW_S:.0f} "
            f"seconds (got {window_s})."
        )
    store = load_store(base_dir)
    record = _record(store, label)
    baseline = record["baseline"]
    if not isinstance(baseline, dict) or baseline.get("status") != "ok":
        return {
            "status": bl.STATUS_NO_BASELINE,
            "tag": label,
            "note": "No learned baseline for this tag — nothing to judge against "
            "(and this tool never guesses). Learn one first: "
            f"baseline_learn(tag='{label}').",
        }
    ref = now or datetime.now(UTC)
    since = datetime.fromtimestamp(ref.timestamp() - window, tz=UTC).isoformat()
    samples = query_samples(
        SampleFilter(since=since, endpoint=endpoint, tag=label, limit=HISTORY_QUERY_LIMIT),
        db_path=db_path,
    )
    result = bl.check_against_baseline(samples, baseline)
    checked = {
        "ts": ref.isoformat(),
        "status": result["status"],
        "violations": len(result["violations"]),
    }
    save_store(_with_record(store, label, {**record, "last_check": checked}), base_dir)
    return {**result, "window_s": window, "since": since, "endpoint": s(endpoint, 64) or None}


def status_flow(tag: str | None = None, base_dir: Path | None = None) -> dict:
    """Status for one tag, or a bounded listing across all tracked tags.

    Statuses: ``no_baseline`` / ``learning`` / ``ok`` / ``violation`` — read from
    the store only (no history scan, no guessing).
    """
    store = load_store(base_dir)
    if tag is not None and str(tag).strip():
        label = _require_tag(tag)
        known = label in store["tags"]
        return _tag_status(label, _record(store, label) if known else None)
    tags = sorted(store["tags"])
    return {
        "tracked_tags": len(tags),
        "listed": min(len(tags), MAX_STATUS_TAGS),
        "truncated": len(tags) > MAX_STATUS_TAGS,  # legacy bool — see `is_truncated`
        "tags": [_tag_status(t, _record(store, t)) for t in tags[:MAX_STATUS_TAGS]],
        **envelope_fields(returned=min(len(tags), MAX_STATUS_TAGS), total=len(tags)),
    }


def _tag_status(tag: str, record: dict | None) -> dict:
    status = bl.classify_status(record)
    out: dict[str, Any] = {"tag": tag, "status": status}
    if record is None:
        out["note"] = "Tag not tracked yet — learn a baseline or record a change first."
        return out
    baseline = record.get("baseline")
    if isinstance(baseline, dict) and baseline.get("status") == "ok":
        out["band"] = baseline.get("band")
        out["baseline_window"] = baseline.get("window")
        out["baseline_n_samples"] = baseline.get("n_samples")
    out["changes_recorded"] = len(record.get("changes") or [])
    if record.get("last_learn"):
        out["last_learn"] = record["last_learn"]
    if record.get("last_check"):
        out["last_check"] = record["last_check"]
    return out


__all__ = [
    "STORE_FILENAME",
    "MAX_STATUS_TAGS",
    "store_path",
    "load_store",
    "save_store",
    "record_change",
    "learn_flow",
    "check_flow",
    "status_flow",
]
