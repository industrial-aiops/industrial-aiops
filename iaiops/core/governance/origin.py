"""Call origin — which front-end started a governed call.

Both front-ends (``iaiops`` CLI, ``iaiops-mcp``) call the same ``@governed_tool``
layer, and that layer cannot see which one called it. So each front-end declares
itself at its OWN boundary by opening an :func:`origin_scope`; the decorator reads
:func:`current` and records it on the audit row.

What an origin does and does not say:

* ``mcp`` — the call arrived as an MCP ``tools/call``: the agent interface.
  ``client`` is the MCP client's **self-reported** ``clientInfo`` (name/version);
  nothing verifies it. ``session`` groups the calls of one client connection.
* ``cli`` — the call arrived through the ``iaiops`` command line. That is a
  front-end, not a person: an agent driving a shell reaches the CLI too.
* no origin (``""`` on the row) — neither front-end opened a scope: a row written
  before this field existed, or library code calling a tool directly. Unknown —
  never to be read as human or agent.

The old ``agent`` column is a separate, weaker thing (an environment-variable
guess) and is left as it was.
"""

from __future__ import annotations

import contextvars
import threading
import uuid
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from iaiops.core.governance.sanitize import sanitize

KIND_MCP = "mcp"
KIND_CLI = "cli"
KINDS = (KIND_MCP, KIND_CLI)

#: Cap for the self-reported client text stored on every row.
CLIENT_MAX = 128

CLI_CLIENT = "iaiops-cli"


@dataclass(frozen=True)
class CallOrigin:
    """The front-end a call came through. Immutable; ``kind`` is validated."""

    kind: str
    client: str = ""
    session: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"call origin kind must be one of {KINDS}, got {self.kind!r}")

    @classmethod
    def for_mcp_client(cls, name: str, version: str, session: str = "") -> CallOrigin:
        """An MCP origin from a client's self-reported ``clientInfo``."""
        label = f"{name or '?'}/{version}" if version else (name or "")
        # One line, no control characters: it lands on every row and in reports.
        one_line = " ".join(sanitize(label, CLIENT_MAX * 4).split())
        return cls(kind=KIND_MCP, client=one_line[:CLIENT_MAX], session=session)


_current: contextvars.ContextVar[CallOrigin | None] = contextvars.ContextVar(
    "iaiops_call_origin", default=None
)


def current() -> CallOrigin | None:
    """The origin of the call in progress, or None when no front-end declared one."""
    return _current.get()


@contextmanager
def origin_scope(call_origin: CallOrigin) -> Iterator[CallOrigin]:
    """Declare the origin for every governed call made inside the block."""
    token = _current.set(call_origin)
    try:
        yield call_origin
    finally:
        _current.reset(token)


def new_session_id(kind: str) -> str:
    """A fresh opaque id for one MCP client connection or one CLI process."""
    return f"{kind}-{uuid.uuid4().hex[:16]}"


_CLI_SESSION = new_session_id(KIND_CLI)

# One opaque id per MCP client connection (a server-session object). Weak keys,
# so a closed session's entry goes with it.
_mcp_session_ids: weakref.WeakKeyDictionary[Any, str] = weakref.WeakKeyDictionary()
_mcp_session_lock = threading.Lock()


def _mcp_session_id(session: Any) -> str:
    with _mcp_session_lock:
        sid = _mcp_session_ids.get(session)
        if sid is None:
            sid = new_session_id(KIND_MCP)
            _mcp_session_ids[session] = sid
        return sid


def mcp_origin(session: Any | None) -> CallOrigin:
    """The origin of an MCP ``tools/call`` served on ``session``.

    ``session`` is the MCP SDK's server session (duck-typed, so this module needs
    no MCP import): its ``client_params.clientInfo`` gives the self-reported client
    name/version, and the object itself keys the per-connection id. ``None`` — a
    call with no request context, such as a test calling the server directly —
    still came through the MCP boundary, it just has no client to name.

    Shared by every MCP server built on iaiops (the edition servers here, and the
    servers of packages that run beside them on the same audit trail).
    """
    if session is None:
        return CallOrigin(kind=KIND_MCP)
    info = getattr(getattr(session, "client_params", None), "clientInfo", None)
    return CallOrigin.for_mcp_client(
        name=getattr(info, "name", "") or "",
        version=getattr(info, "version", "") or "",
        session=_mcp_session_id(session),
    )


def cli_origin() -> CallOrigin:
    """The origin for a CLI command: one session id per ``iaiops`` process."""
    return CallOrigin(kind=KIND_CLI, client=CLI_CLIENT, session=_CLI_SESSION)


__all__ = [
    "CLIENT_MAX",
    "CLI_CLIENT",
    "KINDS",
    "KIND_CLI",
    "KIND_MCP",
    "CallOrigin",
    "cli_origin",
    "current",
    "mcp_origin",
    "new_session_id",
    "origin_scope",
]
