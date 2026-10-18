"""Input-path confinement for MCP tools that open a file the agent names.

An MCP tool's ``path`` argument is chosen by a model — or by a prompt injected
into something it read — so "read this file" must not mean "read any file on the
host". :func:`agent_readable_path` admits a path only when, after ``~``, ``..``
and every symlink are resolved, it lies under one of :func:`agent_readable_roots`
(``$IAIOPS_HOME`` and the config directory). The check runs BEFORE the file is
touched, so a refusal can say nothing about it: not its content, not even
whether it exists. The CLI does not use this — its path is typed by the operator
in their own shell, and :func:`~iaiops.core.governance.evidence.validate_output_path`
is its output-side counterpart.
"""

from __future__ import annotations

from pathlib import Path

#: Longest slice of the agent's own path string echoed back in a refusal. The
#: roots come first in the message, so a long path cannot push them out of it.
_MAX_ECHOED_PATH = 120


def agent_readable_roots() -> tuple[Path, ...]:
    """Resolved directories an agent may name a file under, de-duplicated, in order.

    ``$IAIOPS_HOME`` (harness state) and the config directory (``~/.iaiops``).
    The directory of an ``IAIOPS_CONFIG`` override is deliberately NOT a root: a
    config file can sensibly live in ``/etc``, ``/tmp``, ``~/Documents`` or the
    server's working directory, and none of those is a directory the agent should
    be able to read from.
    """
    from iaiops.core.governance.paths import ops_home
    from iaiops.core.runtime import config

    roots: list[Path] = []
    for root in (ops_home(), config.CONFIG_DIR):
        resolved = root.expanduser().resolve()
        if resolved not in roots and not _too_broad(resolved):
            roots.append(resolved)
    return tuple(roots)


def _too_broad(root: Path) -> bool:
    """A root that is ``/`` or holds the user's home confines nothing.

    ``IAIOPS_HOME=~`` (or ``/``) would admit every file in the home directory (or
    on the host). Such a root is dropped, so the agent reads under the remaining
    one — or nowhere, and is told why.
    """
    home = Path.home().resolve()
    return root == Path(root.anchor) or home.is_relative_to(root)


def _shown(path: str) -> str:
    text = path if len(path) <= _MAX_ECHOED_PATH else path[:_MAX_ECHOED_PATH] + "…"
    return repr(text)


def agent_readable_path(path: str, *, suffixes: tuple[str, ...]) -> Path:
    """Resolve an agent-supplied input path, or refuse it without reading it.

    Order matters: confinement is decided on the fully resolved path before the
    file's kind or existence is checked, so the answer for a path outside the
    roots is the same whether or not something is there. Returns the resolved
    path — the caller reads THAT, not the string it was given.
    """
    candidate = Path(path).expanduser()
    resolved = candidate.resolve()
    roots = agent_readable_roots()
    if not any(resolved.is_relative_to(root) for root in roots):
        names = (
            ", ".join(str(r) for r in roots)
            or "none usable — each is / or holds the home directory"
        )
        raise ValueError(
            f"Not opened: the path resolves outside $IAIOPS_HOME and the config directory, "
            f"the only places an agent may read ({names}). Copy the file into one of them, "
            "or run the matching `iaiops` command from a shell, which reads any path you "
            f"type. Path given: {_shown(path)}."
        )
    if candidate.is_symlink():
        raise ValueError(f"{_shown(path)} is a symbolic link — pass the real file.")
    if resolved.suffix.lower() not in suffixes:
        raise ValueError(f"Expected a {'/'.join(suffixes)} file, got {_shown(path)}.")
    if not resolved.is_file():
        raise ValueError(f"{_shown(path)} is not a readable file.")
    return resolved


__all__ = ["agent_readable_path", "agent_readable_roots"]
