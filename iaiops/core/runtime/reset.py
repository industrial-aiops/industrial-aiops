"""Remove all local data and settings — ``iaiops reset`` (CRA Annex I Part I(2)(b)(m)).

The CRA asks that users can reset a product to its original state and securely
and easily remove all data and settings. iaiops keeps its state under up to three
roots (they coincide unless relocated): the harness home (``IAIOPS_HOME``), the
config directory, and the secret-store directory — plus the config file itself
when ``IAIOPS_CONFIG`` points elsewhere. ``plan_reset`` lists everything there;
``apply_reset`` removes it.

What it does NOT do, and says so: it does not reach external stores (TDengine,
IoTDB, a SQLite file configured outside the roots, a SIEM that received
forwarded audit rows), and it unlinks files rather than shredding them — the
encrypted secret store is unreadable without its master password, but the audit
trail and collected history are plaintext SQLite, and on flash storage only
full-disk encryption or a device wipe sanitises the medium.

Symlinks inside a root are removed, never followed. A root that is the
filesystem root, the user's home directory or one of its ancestors is refused.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

NOT_COVERED: tuple[str, ...] = (
    "external historians the site configured (TDengine, IoTDB) and any SQLite store "
    "configured at a path outside these roots",
    "audit rows already forwarded to a SIEM or syslog collector",
    "evidence zips and reports written with --out to a path of your choice",
    "container volumes or images (remove the volume with your container runtime)",
)

ERASE_NOTE = (
    "Files are unlinked, not shredded. The encrypted secret store cannot be read "
    "without its master password; the audit trail and collected history are "
    "plaintext SQLite. On SSD/flash only full-disk encryption or a device wipe "
    "sanitises the medium."
)


def _roots() -> list[Path]:
    """Every directory iaiops writes state into, deduplicated, in a stable order."""
    from iaiops.core.governance.paths import ops_home
    from iaiops.core.runtime import config, secretstore

    roots: list[Path] = []
    for root in (ops_home(), Path(config.CONFIG_DIR), Path(secretstore.CONFIG_DIR)):
        resolved = Path(os.path.abspath(root.expanduser()))
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _refuse_unsafe_root(root: Path) -> None:
    home = Path(os.path.abspath(Path.home()))
    if root == Path(root.anchor) or root == home or root in home.parents:
        raise ValueError(
            f"Refusing to reset {root}: it is not an iaiops state directory (it is "
            "the filesystem root, your home directory, or one of its parents). Check "
            "IAIOPS_HOME."
        )


def _entry(path: Path) -> dict[str, Any]:
    kind = "symlink" if path.is_symlink() else "dir" if path.is_dir() else "file"
    return {"path": str(path), "kind": kind}


def _config_override() -> Path | None:
    raw = os.environ.get("IAIOPS_CONFIG")
    return Path(os.path.abspath(Path(raw).expanduser())) if raw else None


def plan_reset() -> dict[str, Any]:
    """List what a reset would remove. Changes nothing.

    Raises:
        ValueError: when a root is not an iaiops state directory.
    """
    roots = _roots()
    for root in roots:
        _refuse_unsafe_root(root)
    entries = [
        _entry(child)
        for root in roots
        if root.is_dir() and not root.is_symlink()
        for child in sorted(root.iterdir())
    ]
    override = _config_override()
    if override and override.exists() and not any(r in override.parents for r in roots):
        entries.append(_entry(override))
    return {
        "roots": [str(r) for r in roots],
        "entries": entries,
        "entry_count": len(entries),
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
    return {
        "removed": removed,
        "removed_count": len(removed),
        "errors": errors,
        "audit_trail": _fresh_audit_trail(),
        "not_covered": plan["not_covered"],
        "erase_note": plan["erase_note"],
    }


__all__ = ["ERASE_NOTE", "NOT_COVERED", "apply_reset", "plan_reset"]
