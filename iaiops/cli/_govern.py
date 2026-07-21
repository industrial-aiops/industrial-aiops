"""Central governance injection for the CLI (see ``docs/HLD.md`` §3.1).

Both front-ends are thin callers of the same ``ops.*`` layer; each must be
governed at its OWN boundary — where the endpoint name still exists — sharing one
audit / policy / budget engine. The MCP wrappers carry ``@governed_tool``
directly; the CLI gets it here, in a single pass over every registered Typer
command, so a command cannot ship ungoverned by omission (new commands are
audited by default).

Why a central pass rather than a decorator on each of ~120 command functions: it
is un-bypassable (a new command is governed automatically) and it keeps the
per-command source small. Typer follows ``__wrapped__`` for signature
introspection, so wrapping the callbacks leaves every option / argument / help
string unchanged — verified by ``tests/test_cli_audit.py``.

Per-command metadata comes from markers in ``iaiops.cli._common``:
``high_risk`` (write command → ``_cli_risk_level="high"``, approver-gated + audited,
parity with the MCP write tool), ``audit_sensitive`` (``_cli_sensitive`` — param
names redacted from the audit row) and ``no_audit`` (``_cli_skip_govern`` — a
launcher such as ``iaiops mcp``, whose spawned tools are governed individually).
"""

from __future__ import annotations

import functools
from typing import Any

import typer

from iaiops.cli._common import console
from iaiops.core.governance import governed_tool
from iaiops.core.governance.budget import BudgetExceeded
from iaiops.core.governance.decorators import PolicyDenied


def _wrap(callback: Any) -> Any:
    """Return a governed callback: audit + policy + budget, with denials rendered
    as a clean one-line CLI error instead of a traceback.

    Signature-preserving (``@functools.wraps``) so Typer still builds the same
    options. ``governed_tool`` runs first (policy pre-check + audit); a denial or
    budget stop is caught here and turned into ``typer.Exit(1)`` — the same shape
    ``cli_errors`` gives other failures.
    """
    risk = getattr(callback, "_cli_risk_level", "low")
    sensitive = getattr(callback, "_cli_sensitive", None)
    governed = governed_tool(risk_level=risk, sensitive_params=sensitive)(callback)

    @functools.wraps(callback)
    def cli_governed(*args: Any, **kwargs: Any) -> Any:
        try:
            return governed(*args, **kwargs)
        except (PolicyDenied, BudgetExceeded) as exc:
            console.print(f"[red]Denied: {exc}[/]")
            raise typer.Exit(1) from exc

    cli_governed._is_governed_tool = True
    cli_governed._risk_level = risk
    return cli_governed


def govern_app(app: Any) -> int:
    """Wrap every registered command of ``app`` (and its sub-apps) with governance.

    Idempotent: skips callbacks already governed and those marked
    ``_cli_skip_govern``. Returns the count governed. Must run after the app is
    assembled and before Typer builds its Click commands.
    """
    count = 0
    for cmd in getattr(app, "registered_commands", []):
        cb = cmd.callback
        if cb is None or getattr(cb, "_is_governed_tool", False):
            continue
        if getattr(cb, "_cli_skip_govern", False):
            continue
        cmd.callback = _wrap(cb)
        count += 1
    for grp in getattr(app, "registered_groups", []):
        count += govern_app(grp.typer_instance)
    return count
