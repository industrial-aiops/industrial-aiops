"""Input-path confinement for MCP tools that open a file the agent names.

An MCP tool's ``path`` argument is chosen by a model — or by a prompt injected
into something it read — so "read this file" must not mean "read any file on the
host". :func:`agent_readable_path` admits a path only when, after ``~``, ``..``
and every symlink are resolved, it lies under one of :func:`agent_readable_roots`
(``$IAIOPS_HOME``, the config directory, and the directories the operator
lists in ``IAIOPS_AGENT_READ_DIRS``). The check runs BEFORE the file is
touched, so a refusal can say nothing about it: not its content, not even
whether it exists. The CLI does not use this — its path is typed by the operator
in their own shell, and :func:`~iaiops.core.governance.evidence.validate_output_path`
is its output-side counterpart.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

#: Longest slice of the agent's own path string echoed back in a refusal. The
#: roots come first in the message, so a long path cannot push them out of it.
_MAX_ECHOED_PATH = 120

#: Extra read roots, set by the OPERATOR (the MCP server's environment or
#: ``~/.iaiops/.env``) — ``os.pathsep``-separated absolute directories, e.g.
#: ``~/exports:~/advisories``. No tool writes either place, so an agent cannot
#: widen its own reach.
OPERATOR_DIRS_ENV = "IAIOPS_AGENT_READ_DIRS"


def agent_readable_roots() -> tuple[Path, ...]:
    """Resolved directories an agent may name a file under, de-duplicated, in order.

    ``$IAIOPS_HOME`` (harness state), the config directory (``~/.iaiops``), and
    each directory in ``IAIOPS_AGENT_READ_DIRS``. The directory of an
    ``IAIOPS_CONFIG`` override is deliberately NOT a root: a config file can
    sensibly live in ``/etc``, ``/tmp`` or the server's working directory, and
    none of those was chosen as a place the agent may read. An operator entry
    that is relative, missing, ``/``, holds the home directory, is not owned by
    this process's user or is writable by group or others is ignored — each would
    confine nothing, or let somebody else plant (or swap in a symlink to) a file
    the agent then reads. Any root that is world-writable is dropped likewise.
    """
    from iaiops.core.governance.paths import ops_home
    from iaiops.core.runtime import config

    defaults = [ops_home().expanduser(), config.CONFIG_DIR.expanduser()]
    roots: list[Path] = []
    for root in defaults:
        resolved = root.resolve()
        if resolved not in roots and not _too_broad(resolved) and not _world_writable(resolved):
            roots.append(resolved)
    for root in _operator_dirs():
        resolved = root.resolve()
        if resolved not in roots and not _too_broad(resolved) and _private_to_us(resolved):
            roots.append(resolved)
    return tuple(roots)


def _operator_dirs() -> list[Path]:
    raw = os.environ.get(OPERATOR_DIRS_ENV, "")
    dirs = []
    for entry in raw.split(os.pathsep):
        path = Path(entry.strip()).expanduser() if entry.strip() else None
        # Relative entries depend on the server's cwd; missing ones on what
        # appears there later. Neither is a decision the operator made.
        if path is not None and path.is_absolute() and path.is_dir():
            dirs.append(path)
    return dirs


def _too_broad(root: Path) -> bool:
    """A root that is ``/`` or holds the user's home confines nothing.

    ``IAIOPS_HOME=~`` (or ``/``) would admit every file in the home directory (or
    on the host). Such a root is dropped, so the agent reads under the remaining
    ones — or nowhere, and is told why.
    """
    if root == Path(root.anchor):
        return True
    # By file identity, not by string: on a case-insensitive file system
    # ``/USERS/ZW`` IS the home directory, though no string comparison says so.
    home = Path.home().resolve()
    return any(_same(root, candidate) for candidate in (home, *home.parents))


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return a == b


def _world_writable(root: Path) -> bool:
    """Any local user could plant (or swap) a file the agent then reads."""
    try:
        return bool(root.stat().st_mode & stat.S_IWOTH)
    except OSError:
        return False  # not there yet: nothing under it to read


def _private_to_us(root: Path) -> bool:
    """Owned by this process's user and writable by nobody else.

    The guard checks a path and the tool then opens it: whoever can write inside
    a root can swap a checked directory for a symlink in between. Restricting an
    operator-listed root to the server's own user leaves that window only to the
    user the server already runs as.
    """
    try:
        info = root.stat()
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        return False
    return info.st_uid == os.geteuid() and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)


def _shown(path: str) -> str:
    text = path if len(path) <= _MAX_ECHOED_PATH else path[:_MAX_ECHOED_PATH] + "…"
    return repr(text)


def agent_readable_path(path: str, *, suffixes: tuple[str, ...], must_exist: bool = True) -> Path:
    """Resolve an agent-supplied input path, or refuse it without reading it.

    Order matters: confinement is decided on the fully resolved path before the
    file's kind or existence is checked, so the answer for a path outside the
    roots is the same whether or not something is there. Returns the resolved
    path — the caller reads THAT, not the string it was given. ``must_exist=False``
    is for a store override whose absence means "empty": the path is still
    confined, and the caller must not create it.
    """
    candidate = Path(path).expanduser()
    resolved = candidate.resolve()
    roots = agent_readable_roots()
    if not any(resolved.is_relative_to(root) for root in roots):
        names = ", ".join(str(r) for r in roots) or "none usable"
        # The remedy comes before the variable parts: tool errors are capped at
        # 300 characters, and a long root list must not push it out.
        raise ValueError(
            "Not opened: outside where an agent may read — $IAIOPS_HOME, the config "
            f"directory, and the operator's {OPERATOR_DIRS_ENV}. Copy the file there, ask "
            "the operator to list its directory, or run the `iaiops` command from a shell. "
            f"Roots: {names}. Path given: {_shown(path)}."
        )
    if candidate.is_symlink():
        raise ValueError(f"{_shown(path)} is a symbolic link — pass the real file.")
    if resolved.suffix.lower() not in suffixes:
        raise ValueError(f"Expected a {'/'.join(suffixes)} file, got {_shown(path)}.")
    if resolved.exists() or must_exist:
        if not resolved.is_file():
            raise ValueError(f"{_shown(path)} is not a readable file.")
    return resolved


__all__ = ["OPERATOR_DIRS_ENV", "agent_readable_path", "agent_readable_roots"]
