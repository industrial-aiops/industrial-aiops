"""``iaiops baseline`` — conservative change-log baseline (NOT anomaly detection).

Learn a per-tag normal band from the LOCAL SQLite history (robust p1/p99 +
median/MAD, no ML), record operator changes that restart learning, and check
recent samples against the band. Silent by default: learning refuses thin
history, and only sustained excursions beyond the band by a conservative MAD
margin are flagged — every flag cites its baseline samples.
"""

from __future__ import annotations

import typer

from iaiops.cli._common import _emit, cli_errors
from iaiops.core.brain import baseline_store as bls

baseline_app = typer.Typer(
    help="Conservative change-log baseline over collected local history "
    "(learn / check / change / status). Local metadata only — no device I/O."
)


@baseline_app.command("learn")
@cli_errors
def learn_cmd(
    tag: str = typer.Argument(..., help="Tag to learn, e.g. line1.temp"),
    endpoint: str | None = typer.Option(
        None, "--endpoint", "-e", help="Only samples from this endpoint label"
    ),
    since: str | None = typer.Option(
        None, "--since", help="Only samples at/after this ISO-8601 time"
    ),
) -> None:
    """Learn a per-tag band from ~/.iaiops/data.db; refuses thin history."""
    _emit(bls.learn_flow(tag, endpoint=endpoint, since=since))


@baseline_app.command("check")
@cli_errors
def check_cmd(
    tag: str = typer.Argument(..., help="Tag to check, e.g. line1.temp"),
    endpoint: str | None = typer.Option(
        None, "--endpoint", "-e", help="Only samples from this endpoint label"
    ),
    window_s: float = typer.Option(
        3600.0, "--window-s", help="Recent window to check, seconds (60..604800)"
    ),
) -> None:
    """Check recent samples against the learned band (sustained-only flags)."""
    _emit(bls.check_flow(tag, endpoint=endpoint, window_s=window_s))


@baseline_app.command("change")
@cli_errors
def change_cmd(
    tag: str = typer.Argument(..., help="Tag whose process changed"),
    note: str = typer.Argument(..., help="What changed, e.g. 'setpoint 60→70C'"),
    ts: str | None = typer.Option(
        None, "--ts", help="ISO-8601 time of the change (default: now UTC)"
    ),
) -> None:
    """Record an operator change; the next learn restarts after it."""
    _emit(bls.record_change(tag, ts, note))


@baseline_app.command("status")
@cli_errors
def status_cmd(
    tag: str | None = typer.Argument(
        None, help="Tag to inspect; omit to list all tracked tags (bounded)"
    ),
) -> None:
    """no_baseline / learning / ok / violation — from the store, never a guess."""
    _emit(bls.status_flow(tag))


__all__ = ["baseline_app"]
