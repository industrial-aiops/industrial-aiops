"""Undo-token primitive — record the inverse of a write operation.

Reversibility is a 2026 agentic-ops requirement: an operator (or an external orchestrator)
needs to roll a change back to a known-good state. The inverse of an operation
is domain-specific (power-off ↔ power-on, create-snapshot ↔ delete-snapshot,
and some ops — like delete-vm — have NO safe inverse), so a tool *declares* its
undo via ``@governed_tool(undo=...)``.

This module only RECORDS the inverse descriptor (a replayable
``{skill, tool, params}``) into ``~/.iaiops/undo.db`` and hands back an
``undo_id``. It deliberately does NOT execute the inverse — coordinated,
multi-step rollback is an external orchestrator's job. Keeping recording and execution
separate matches the "separate the deterministic parts from the parts where the
LLM reasons" guardrail.

A tool's ``undo`` is a callable ``(params, result) -> dict | None``:

    @governed_tool(risk_level="medium", undo=lambda p, r: {
        "tool": "vm_power_on", "params": {"vm_name": p["vm_name"]}})
    def vm_power_off(vm_name: str, target: str = "") -> dict: ...

Returning ``None`` means "no inverse for this call" (nothing is recorded).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaiops.core.governance.paths import ops_path

_log = logging.getLogger("iaiops.undo")

_BUSY_TIMEOUT_MS = 5000

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS undo_log (
    undo_id     TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    skill       TEXT NOT NULL DEFAULT '',
    tool        TEXT NOT NULL DEFAULT '',
    undo_skill  TEXT NOT NULL DEFAULT '',
    undo_tool   TEXT NOT NULL DEFAULT '',
    undo_params TEXT NOT NULL DEFAULT '{}',
    orig_params TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'recorded',
    workflow_id TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_undo_status ON undo_log(status)"


class UndoStore:
    """Append-and-update store for recorded undo descriptors (SQLite/WAL)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path).expanduser() if db_path else ops_path("undo.db")
        self._ok = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            conn = self._connect()
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()
            conn.close()
            self._harden()
            self._ok = True
        except Exception:
            _log.warning("Cannot initialize undo DB at %s", self._path, exc_info=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        return conn

    def _harden(self) -> None:
        try:
            os.chmod(self._path.parent, 0o700)
        except OSError:
            pass
        for suffix in ("", "-wal", "-shm"):
            candidate = self._path.with_name(self._path.name + suffix)
            try:
                if candidate.exists():
                    os.chmod(candidate, 0o600)
            except OSError:
                pass

    def record(
        self,
        *,
        skill: str,
        tool: str,
        undo_descriptor: dict[str, Any],
        orig_params: dict[str, Any] | None = None,
        workflow_id: str = "",
    ) -> str | None:
        """Persist an inverse descriptor; return its undo_id (or None on failure).

        ``undo_descriptor`` must carry at least ``tool`` (the inverse tool) and
        ``params``; ``skill`` defaults to the original skill. Never raises —
        recording must not break the underlying tool call.
        """
        if not self._ok:
            return None
        if not isinstance(undo_descriptor, dict) or not undo_descriptor.get("tool"):
            _log.debug("undo descriptor for %s.%s missing 'tool' — not recorded", skill, tool)
            return None
        undo_id = uuid.uuid4().hex[:16]
        try:
            conn = self._connect()
            conn.execute(
                "INSERT INTO undo_log (undo_id, ts, skill, tool, undo_skill, undo_tool, "
                "undo_params, orig_params, status, workflow_id, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'recorded', ?, ?)",
                (
                    undo_id,
                    datetime.now(tz=UTC).isoformat(),
                    skill,
                    tool,
                    str(undo_descriptor.get("skill", skill)),
                    str(undo_descriptor["tool"]),
                    _safe_json(undo_descriptor.get("params", {})),
                    _safe_json(orig_params or {}),
                    workflow_id,
                    str(undo_descriptor.get("note", "")),
                ),
            )
            conn.commit()
            conn.close()
            return undo_id
        except Exception:
            _log.warning("Failed to record undo for %s.%s", skill, tool, exc_info=True)
            return None

    def get(self, undo_id: str) -> dict[str, Any] | None:
        if not self._ok:
            return None
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM undo_log WHERE undo_id = ?", (undo_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if not self._ok:
            return []
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM undo_log WHERE status = ? ORDER BY ts DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM undo_log ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark(self, undo_id: str, status: str) -> bool:
        """Update an undo record's status (e.g. 'applied' / 'expired')."""
        if not self._ok:
            return False
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE undo_log SET status = ? WHERE undo_id = ?", (status, undo_id)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"_raw": str(obj)})


# ── Singleton ──────────────────────────────────────────────────────────

_store: UndoStore | None = None
_store_lock = threading.Lock()


def get_undo_store(db_path: Path | str | None = None) -> UndoStore:
    """Return the global UndoStore singleton (lazy, lock-guarded)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = UndoStore(db_path)
    return _store


def reset_undo_store() -> None:
    """Reset the singleton. Tests use this between cases."""
    global _store
    with _store_lock:
        _store = None
