"""Remove all local data and settings — ``iaiops reset`` (CRA Annex I Part I(2)(b)(m)).

The CRA asks that users can reset a product to its original state and securely
and easily remove all data and settings. iaiops keeps its state under up to three
roots (they coincide unless relocated): the harness home (``IAIOPS_HOME``), the
config directory and the secret-store directory — plus the config file itself
when ``IAIOPS_CONFIG`` points elsewhere.

**Only names iaiops itself writes are removed** (``KNOWN_FILES`` / ``KNOWN_DIRS``,
their SQLite sidecars and temp files, audit archives). Anything else found in a
root is listed as *kept* — never deleted, never silently skipped. ``IAIOPS_HOME``
can point anywhere; a reset that deleted "everything in the root" would wipe a
project directory or a shared volume on one mistyped variable.

What it does NOT do, and says so: it does not reach external stores (TDengine,
IoTDB, a SQLite file configured elsewhere, a SIEM that received forwarded audit
rows), and it unlinks files rather than shredding them. A running MCP server or
collector keeps its configuration and unlocked secrets in memory — stop it first.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

KNOWN_FILES = frozenset(
    {
        "config.yaml",
        "secrets.enc",
        ".env",
        "rules.yaml",
        "audit.db",
        "undo.db",
        "data.db",
        "audit_forward.cursor",
        "baselines.json",
        "program_baselines.json",
    }
)
KNOWN_DIRS = frozenset(
    {
        "approvals",
        "auto-remediation-patterns",
        "sessions",
        "investigations",
        "uns_audits",
        "knowledge",
        "aliases",
    }
)
#: What iaiops writes into the config directory whatever IAIOPS_HOME says — the
#: only names shared by every instance on the host. In a root IAIOPS_HOME does
#: not move, nothing else is this instance's: that directory is also the default
#: instance's home, holding ITS audit trail and history.
SHARED_ROOT_NAMES = frozenset(
    {"config.yaml", "secrets.enc", ".env", "sessions", "investigations", "knowledge"}
)
_SIDECARS = ("-wal", "-shm", "-journal", ".tmp")
_AUDIT_ARCHIVE = re.compile(r"^audit\.\d{8}-\d{6}\.db(-wal|-shm|-journal)?$")

NOT_COVERED: tuple[str, ...] = (
    "external historians the site configured (TDengine, IoTDB) and any SQLite store "
    "configured at a path outside these roots",
    "audit rows already forwarded to a SIEM or syslog collector",
    "evidence zips and reports written with --out to a path of your choice",
    "container volumes or images (remove the volume with your container runtime)",
    "anything listed under 'kept' — not recognised as iaiops state, so not touched",
)

ERASE_NOTE = (
    "Files are unlinked, not shredded. The encrypted secret store cannot be read "
    "without its master password; the audit trail and collected history are "
    "plaintext SQLite. On SSD/flash only full-disk encryption or a device wipe "
    "sanitises the medium. Stop any running iaiops MCP server or collector first: "
    "it holds configuration and unlocked secrets in memory and may write files again."
)


def is_known_state(name: str) -> bool:
    """True for a name iaiops itself writes into a state root."""
    if name in KNOWN_FILES or name in KNOWN_DIRS or _AUDIT_ARCHIVE.match(name):
        return True
    return any(name.endswith(s) and name[: -len(s)] in KNOWN_FILES for s in _SIDECARS)


def _refuse_relative_home() -> None:
    raw = os.environ.get("IAIOPS_HOME") or os.environ.get("OT_AIOPS_HOME") or ""
    if raw and not Path(raw).expanduser().is_absolute():
        raise ValueError(
            f"Refusing to reset with a relative IAIOPS_HOME ({raw!r}): it depends on "
            "the directory you happen to run from. Use an absolute path."
        )


def _refuse_unsafe_root(root: Path) -> None:
    home = Path.home().resolve()
    if root == Path(root.anchor) or root == home or root in home.parents:
        raise ValueError(
            f"Refusing to reset {root}: it is the filesystem root, your home "
            "directory, or one of its parents — not an iaiops state directory. "
            "Check IAIOPS_HOME."
        )


def _roots() -> list[Path]:
    """Every directory iaiops writes state into, resolved and deduplicated."""
    from iaiops.core.governance.paths import ops_home
    from iaiops.core.runtime import config, secretstore

    roots: list[Path] = []
    for root in (ops_home(), Path(config.CONFIG_DIR), Path(secretstore.CONFIG_DIR)):
        resolved = root.expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _entry(path: Path) -> dict[str, Any]:
    kind = "symlink" if path.is_symlink() else "dir" if path.is_dir() else "file"
    return {"path": str(path), "kind": kind}


def _is_shared_name(name: str) -> bool:
    if name in SHARED_ROOT_NAMES:
        return True
    return any(name.endswith(s) and name[: -len(s)] in SHARED_ROOT_NAMES for s in _SIDECARS)


def _scan(roots: list[Path], home_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    remove: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        shared = root != home_root
        for child in sorted(root.iterdir()):
            if not is_known_state(child.name):
                kept.append(_entry(child))
            elif shared and not _is_shared_name(child.name):
                kept.append(
                    {
                        **_entry(child),
                        "reason": "belongs to the iaiops instance whose home is this "
                        "directory, not to this IAIOPS_HOME — reset it with IAIOPS_HOME "
                        "unset (or set to this directory)",
                    }
                )
            else:
                remove.append(_entry(child))
    return remove, kept


def _override(roots: list[Path], kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The $IAIOPS_CONFIG file when it lives outside the roots — a file, never a dir."""
    raw = os.environ.get("IAIOPS_CONFIG")
    if not raw:
        return []
    # Resolve the parent only: a symlinked override is removed as the link, never
    # followed to a target that may be a shared file of any name.
    given = Path(raw).expanduser()
    path = given.parent.resolve() / given.name
    if not (path.exists() or path.is_symlink()):
        return []
    if any(r == path or r in path.parents for r in roots):
        return []
    if path.is_symlink():
        return [_entry(path)]
    if path.is_dir():
        kept.append({**_entry(path), "reason": "IAIOPS_CONFIG names a directory"})
        return []
    return [_entry(path)]


def _notes(roots: list[Path]) -> list[str]:
    from iaiops.core.governance.paths import ops_home

    notes: list[str] = []
    home_root = ops_home().expanduser().resolve()
    shared = [r for r in roots if r != home_root]
    if shared:
        notes.append(
            f"{', '.join(map(str, shared))} is not moved by IAIOPS_HOME: the config, "
            "secrets, collection sessions, investigations and knowledge there are "
            "shared by every iaiops instance on this host, and this reset removes them "
            "for all of them. Any other iaiops state there belongs to the default "
            "instance and is kept."
        )
    legacy = Path("~/.ot-aiops").expanduser()
    if legacy.is_dir() and legacy.resolve() not in roots:
        notes.append(
            f"A legacy state directory exists at {legacy} and is not covered; reset it "
            "with IAIOPS_HOME set to that path."
        )
    return notes


def plan_reset() -> dict[str, Any]:
    """List what a reset would remove and what it would keep. Changes nothing.

    Raises:
        ValueError: for a relative IAIOPS_HOME, or a root that is the filesystem
            root, the home directory or one of its parents.
    """
    _refuse_relative_home()
    roots = _roots()
    for root in roots:
        _refuse_unsafe_root(root)
    from iaiops.core.governance.paths import ops_home

    entries, kept = _scan(roots, ops_home().expanduser().resolve())
    entries = entries + _override(roots, kept)
    return {
        "roots": [str(r) for r in roots],
        "entries": entries,
        "entry_count": len(entries),
        "kept": kept,
        "notes": _notes(roots),
        "not_covered": list(NOT_COVERED),
        "erase_note": ERASE_NOTE,
    }


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _fresh_audit_trail() -> str:
    """Create an empty audit DB so the reset's own governed row is the first one."""
    from iaiops.core.governance.audit import AuditEngine
    from iaiops.core.governance.paths import ops_path

    path = ops_path("audit.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    AuditEngine(path)
    return str(path)


def apply_reset(plan: dict[str, Any]) -> dict[str, Any]:
    """Remove every entry of ``plan``. Failures are reported, never swallowed."""
    removed: list[str] = []
    errors: list[dict[str, str]] = []
    for entry in plan["entries"]:
        path = Path(entry["path"])
        try:
            _remove(path)
            removed.append(str(path))
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    try:
        trail = _fresh_audit_trail()
    except Exception as exc:  # noqa: BLE001 — reported in the result, never swallowed
        trail = ""
        errors.append({"path": "audit.db", "error": f"fresh audit trail not created: {exc}"})
    return {
        "removed": removed,
        "removed_count": len(removed),
        "errors": errors,
        "kept": plan["kept"],
        "notes": plan["notes"],
        "audit_trail": trail,
        "not_covered": plan["not_covered"],
        "erase_note": plan["erase_note"],
    }


__all__ = [
    "ERASE_NOTE",
    "KNOWN_DIRS",
    "KNOWN_FILES",
    "NOT_COVERED",
    "apply_reset",
    "is_known_state",
    "plan_reset",
]
