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
``write_command`` (a write → ``_cli_apply_param``; effect-based risk — the real
``--apply`` write is ``high`` and approver-gated, the dry-run preview is ``low``,
both audited), ``audit_sensitive`` (``_cli_sensitive`` — param names redacted from
the audit row) and ``no_audit`` (``_cli_skip_govern`` — a launcher such as
``iaiops mcp``, whose spawned tools are governed individually).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import typer

from iaiops.cli._common import console
from iaiops.core.governance import governed_tool
from iaiops.core.governance.budget import BudgetExceeded
from iaiops.core.governance.decorators import PolicyDenied


def _with_denial_handling(callback: Callable, governed: Callable) -> Callable:
    """Wrap a governed callable so a policy denial / budget stop becomes a clean
    one-line CLI error (``typer.Exit(1)``) instead of a traceback — the same shape
    ``cli_errors`` gives other failures. Signature-preserving for Typer."""

    @functools.wraps(callback)
    def cli_governed(*args: Any, **kwargs: Any) -> Any:
        try:
            return governed(*args, **kwargs)
        except (PolicyDenied, BudgetExceeded) as exc:
            console.print(f"[red]Denied: {exc}[/]")
            raise typer.Exit(1) from exc

    # ``functools.wraps`` copies the ORIGINAL callback's ``__dict__``, so the
    # governance metadata the inner wrapper carries would be invisible from the
    # outside. Redaction still happens (it is the inner ``governed`` that audits),
    # but an auditor — or the credential-redaction contract test — reading
    # ``_sensitive_params`` off the registered command would see nothing and
    # conclude the command declares no credentials. Re-expose it.
    cli_governed._sensitive_params = list(getattr(governed, "_sensitive_params", []))
    # Same reasoning for the advisory ceiling: a command that declares a longer
    # one would otherwise read, from outside, as still carrying the 300s default.
    cli_governed._timeout_seconds = getattr(governed, "_timeout_seconds", None)
    return cli_governed


def _wrap_write(callback: Callable, apply_param: str, sensitive: Any) -> Callable:
    """Govern a write command with **effect-based** risk.

    A dry-run preview (``apply`` falsey) audits at ``low`` — it changes nothing, so
    it needs no approver. The real write (``apply`` truthy) is ``high`` — audited
    and approver-gated (MOC). The per-call selection is done by ``governed_tool``'s
    preview support (a preview is ``apply == False``), the same mechanism the MCP
    write tools use via ``preview_param="dry_run"``.
    """
    governed = governed_tool(
        risk_level="high",
        sensitive_params=sensitive,
        preview_param=apply_param,
        preview_truthy=False,
    )(callback)
    wrapped = _with_denial_handling(callback, governed)
    wrapped._cli_apply_param = apply_param
    wrapped._risk_level = "high"  # declared max risk, for command classification
    return wrapped


def _wrap(callback: Any) -> Any:
    """Return a governed callback: audit + policy + budget, denials rendered clean.

    Write commands (``_cli_apply_param``) get effect-based risk; everything else is
    audited at ``low`` (``_cli_risk_level`` may override).
    """
    sensitive = getattr(callback, "_cli_sensitive", None)
    apply_param = getattr(callback, "_cli_apply_param", None)
    if apply_param is not None:
        governed = _wrap_write(callback, apply_param, sensitive)
        governed._is_governed_tool = True
        return governed

    risk = getattr(callback, "_cli_risk_level", "low")
    # A command whose RUNTIME is the thing the operator asked for declares its own
    # advisory ceiling. The 300s default is a hang detector, and on `collect run
    # --duration 7d` it fired on every successful assessment — the tool warning
    # about the thing it was told to do reads as a fault to the person reading it.
    extra: dict[str, Any] = {}
    timeout_seconds = getattr(callback, "_cli_timeout_seconds", None)
    if timeout_seconds is not None:
        extra["timeout_seconds"] = int(timeout_seconds)
    governed = _with_denial_handling(
        callback,
        governed_tool(risk_level=risk, sensitive_params=sensitive, **extra)(callback),
    )
    governed._is_governed_tool = True
    governed._risk_level = risk
    return governed


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
