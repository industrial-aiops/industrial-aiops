"""Output-path confinement for MCP tools that WRITE a file the agent names.

The write-side twin of :mod:`iaiops.core.governance.input_paths`. Before this, an
MCP ``out_path`` was checked only for ``..``: ``export_data(fmt="sqlite",
out_path="~/.iaiops/audit.db")`` unlinked the audit hash-chain database at
risk=low, and the csv/json/md writers overwrote any host file with their suffix.

:func:`agent_writable_path` admits a path only when, after ``~``, ``..`` and every
symlink are resolved, it lies under one of :func:`agent_writable_roots`:
``$IAIOPS_HOME/exports`` and the directories the OPERATOR lists in
``IAIOPS_AGENT_WRITE_DIRS``. An operator entry is ignored when it would confine
nothing (``/``, the home directory), is not private to this process's user, or
overlaps the product's own state (``$IAIOPS_HOME`` / the config directory, other
than the exports directory) — a write root that holds ``audit.db`` would put it
back in reach. The CLI is the operator's own shell and does not use this.
"""

from __future__ import annotations

import os
from pathlib import Path

from iaiops.core.governance.input_paths import _private_to_us, _shown, _too_broad

#: Extra write roots, set by the OPERATOR (server environment or ``~/.iaiops/.env``).
WRITE_DIRS_ENV = "IAIOPS_AGENT_WRITE_DIRS"


def exports_dir() -> Path:
    """``$IAIOPS_HOME/exports`` — the one write root every install has."""
    from iaiops.core.governance.paths import ops_home

    return ops_home().expanduser() / "exports"


def _state_dirs() -> list[Path]:
    from iaiops.core.governance.paths import ops_home
    from iaiops.core.runtime import config

    return [ops_home().expanduser().resolve(), config.CONFIG_DIR.expanduser().resolve()]


def _overlaps_state(root: Path) -> bool:
    """True when ``root`` contains, or sits inside, product state (not exports)."""
    exports = exports_dir().resolve()
    if root == exports or root.is_relative_to(exports):
        return False
    return any(root.is_relative_to(d) or d.is_relative_to(root) for d in _state_dirs())


def _operator_write_dirs() -> list[Path]:
    dirs = []
    for entry in os.environ.get(WRITE_DIRS_ENV, "").split(os.pathsep):
        path = Path(entry.strip()).expanduser() if entry.strip() else None
        if path is not None and path.is_absolute() and path.is_dir():
            dirs.append(path)
    return dirs


def agent_writable_roots() -> tuple[Path, ...]:
    """Resolved directories an agent may write a file under, in order."""
    exports = exports_dir()
    exports.mkdir(parents=True, exist_ok=True, mode=0o700)
    roots = [exports.resolve()]
    for root in _operator_write_dirs():
        resolved = root.resolve()
        if (
            resolved not in roots
            and not _too_broad(resolved)
            and _private_to_us(resolved)
            and not _overlaps_state(resolved)
        ):
            roots.append(resolved)
    return tuple(roots)


def agent_writable_path(path: str, *, suffixes: tuple[str, ...]) -> Path:
    """Resolve an agent-supplied output path, or refuse it without touching it.

    Confinement is decided on the fully resolved path first; an existing symlink
    at the target is refused even inside a root (writing through it would land
    wherever it points). Creates the parent directory (0700) only under a root.
    Returns the resolved path — the caller writes THAT.
    """
    candidate = Path(path).expanduser()
    resolved = candidate.resolve()
    roots = agent_writable_roots()
    if not any(resolved.is_relative_to(root) for root in roots):
        names = ", ".join(str(r) for r in roots)
        # Remedy first: tool errors are capped, the root list is variable.
        raise ValueError(
            "Not written: outside where an agent may write — $IAIOPS_HOME/exports and the "
            f"operator's {WRITE_DIRS_ENV}. Omit the path to use the default, or run the "
            f"`iaiops` command from a shell. Roots: {names}. Path given: {_shown(path)}."
        )
    if candidate.is_symlink():
        raise ValueError(f"{_shown(path)} is a symbolic link — name a real file.")
    if resolved.suffix.lower() not in suffixes:
        raise ValueError(f"Expected a {'/'.join(suffixes)} file, got {_shown(path)}.")
    if resolved.exists() and not resolved.is_file():
        raise ValueError(f"{_shown(path)} is not a regular file.")
    if not resolved.parent.exists():
        resolved.parent.mkdir(parents=True, mode=0o700)
    return resolved


__all__ = ["WRITE_DIRS_ENV", "agent_writable_path", "agent_writable_roots", "exports_dir"]
