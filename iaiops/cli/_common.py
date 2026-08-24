"""Shared helpers for iaiops CLI sub-modules."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from iaiops.core.report.fmt import humanize_seconds as _humanize_seconds

console = Console()


def _emit(data: object) -> None:
    """Print a value as pretty JSON, str-coercing anything not natively serializable.

    The single shared implementation for every CLI sub-command (previously copy
    -pasted verbatim into ~19 modules, each re-instantiating its own Console).
    """
    console.print_json(json.dumps(data, default=str))


# Re-exported so every existing caller keeps working. The implementation moved
# to core/report/fmt.py so the HTML reports can share it — core must not import
# from cli, and two copies would be two places for "0.0h" to come back.
humanize_seconds = _humanize_seconds

EndpointOption = Annotated[
    str | None, typer.Option("--endpoint", "-e", help="Endpoint name from config")
]


def _cli_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions translated to a one-line teaching error instead of a traceback.

    ``LookupError`` rather than ``KeyError``: ``KeyError`` is already a
    ``LookupError``, so this is the same family widened by one step, and it is
    the family a "you asked for something that is not here" error naturally
    lands in. ``ScanNotFound`` was raising with a carefully written teaching
    message that the user never saw — it escaped as a traceback instead.

    ``SinkError`` is the historian family's equivalent: it exists to carry a
    teaching message, and every one of them escaped as a traceback too.
    """
    from iaiops.core.runtime.connection import OTConnectionError
    from iaiops.core.sink.base import SinkError

    return (OTConnectionError, LookupError, OSError, SinkError, ValueError)


def cli_errors(fn: Callable) -> Callable:
    """Translate known exceptions into one red line + exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except _cli_error_types() as e:
            message = str(e)
            if isinstance(e, KeyError):
                message = f"Missing required key: {message}"
            console.print(f"[red]Error: {message}[/]")
            raise typer.Exit(1) from e

    return wrapper


#: Upper bound on samples pulled from the local store for one measurement. A
#: week at 200ms is ~3M rows per tag; the analyses here work on a window, not on
#: everything ever collected.
MAX_STORE_SAMPLES = 200_000


def run_state_samples(endpoint: str, db: Path | None = None):
    """The endpoint's declared run-state tag and its collected samples.

    Shared by `oee measure` and `case open` so both agree on which tag decides
    what running means. A second copy of this would be a second place for the
    status-word rule to drift.
    """
    from iaiops.core.runtime.config import TagRole, load_config
    from iaiops.core.sink.sqlite_local import SampleFilter, query_samples

    target = load_config().get_target(endpoint)
    run_tags = [t for t in (getattr(target, "tags", ()) or ()) if t.role == TagRole.RUN_STATE]
    if not run_tags:
        raise ValueError(
            f"Endpoint {endpoint!r} declares no run_state tag. Add `role: run_state` and "
            "`running_when:` to the tag that reports whether the line is producing — "
            "run `iaiops readiness` to see what else is missing."
        )
    tag = run_tags[0]
    return tag, query_samples(SampleFilter(tag=tag.ref, limit=MAX_STORE_SAMPLES), db_path=db)


def get_manager(config_path: Path | None = None):
    """Return a ConnectionManager built from config."""
    from iaiops.core.runtime.config import load_config
    from iaiops.core.runtime.connection import ConnectionManager

    return ConnectionManager(load_config(config_path))


def resolve_target(endpoint: str | None):
    """Resolve an endpoint target by name (or the default endpoint)."""
    return get_manager().target(endpoint)


# ── governance markers ───────────────────────────────────────────────────────
# The CLI is governed centrally (see iaiops.cli._govern) so every command leaves
# an audit row and no command ships ungoverned by omission. These markers let a
# command declare the per-command metadata the central pass reads; they only set
# an attribute, so they are inert unless govern_app() runs.


def write_command(fn: Callable) -> Callable:
    """Mark a CLI **write** command — audited on EVERY call, with effect-based risk.

    A dry-run preview (``--apply`` omitted) audits at ``low``: it changes nothing,
    so it needs no approver — a human previewing a write should not have to mint a
    token first. The real write (``--apply``) is ``high``: approver-gated (MOC) and
    audited. ``iaiops.cli._govern`` reads ``_cli_apply_param`` to pick the per-call
    risk from the command's ``apply`` flag.
    """
    fn._cli_apply_param = "apply"
    return fn


def audit_sensitive(*names: str) -> Callable:
    """Mark param names to redact from this command's audit row (credentials).

    ``@audit_sensitive("value")`` above the command → the value never lands in
    ``~/.iaiops/audit.db`` in the clear.
    """

    def deco(fn: Callable) -> Callable:
        fn._cli_sensitive = list(names)
        return fn

    return deco


def no_audit(fn: Callable) -> Callable:
    """Exclude a command from governance — a process launcher (``iaiops mcp``)
    whose spawned operations are each governed on their own."""
    fn._cli_skip_govern = True
    return fn
