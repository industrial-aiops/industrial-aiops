"""``iaiops collect`` — bounded assessment runs that fill the local store.

**One audit row per RUN, not per sample.** A week at 1 Hz is 604,800 reads per
tag; auditing each would bury the log it exists to make readable, and would
misrepresent what happened anyway. The governed act is "start sampling these
tags on this endpoint for this long" — a single decision with a scope and an
end — and that is what gets recorded, with the run's result attached.

``plan`` contacts nothing: it prints what a run would do and what it would cost,
the same posture as ``scan plan``. Evidence before permissions (D21).
"""

from __future__ import annotations

import signal
from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

collect_app = typer.Typer(help="Bounded collection runs — fill the local store for OEE.")


def _build_plan(endpoint: str, tags: str, duration: str, interval_ms: int):
    from iaiops.core.collect.plan import CollectionPlan, parse_duration
    from iaiops.core.runtime.config import load_config

    config = load_config()
    target = config.get_target(endpoint)
    refs = (
        tuple(t.strip() for t in tags.split(",") if t.strip())
        if tags
        else tuple(str(getattr(t, "ref", "")) for t in (getattr(target, "tags", ()) or ()))
    )
    plan = CollectionPlan(
        endpoint=endpoint,
        tags=refs,
        duration_s=parse_duration(duration),
        interval_ms=interval_ms,
    )
    return plan, target


@cli_errors
def collect_plan_cmd(
    endpoint: str = typer.Argument(..., help="Configured endpoint name."),
    duration: str = typer.Option(..., "--duration", help="With a unit: 30m, 8h, 7d."),
    tags: str = typer.Option("", "--tags", help="Comma-separated refs (default: the endpoint's)."),
    interval_ms: int = typer.Option(1000, "--interval-ms"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show what a run would collect and cost. Contacts nothing."""
    from iaiops.core.collect.reader import can_collect, collectable_protocols

    plan, target = _build_plan(endpoint, tags, duration, interval_ms)
    protocol = str(getattr(target, "protocol", ""))
    ok = can_collect(protocol)
    payload = {
        "endpoint": plan.endpoint,
        "protocol": protocol,
        "collectable": ok,
        "tags": list(plan.tags),
        "interval_ms": plan.interval_ms,
        "duration_s": plan.duration_s,
        "estimated_rows": plan.estimated_rows,
        "resolves_stops_shorter_than_s": plan.resolves_stops_shorter_than_s,
        "resolution_note": plan.resolution_note,
        "contacted": [],
    }
    if as_json:
        _emit(payload)
        return
    console.print(f"\n[bold]Collection plan[/] — {plan.summary}\n")
    if not ok:
        console.print(
            f"[red]✗ {protocol} cannot be sampled on a schedule.[/] "
            f"Collectable today: {', '.join(collectable_protocols())}."
        )
    else:
        console.print("[green]✓[/] this endpoint can be sampled on a schedule.")
    console.print("[dim]Nothing was contacted to produce this plan.[/]")


@cli_errors
def collect_run_cmd(
    endpoint: str = typer.Argument(..., help="Configured endpoint name."),
    duration: str = typer.Option(..., "--duration", help="With a unit: 30m, 8h, 7d."),
    tags: str = typer.Option("", "--tags", help="Comma-separated refs (default: the endpoint's)."),
    interval_ms: int = typer.Option(1000, "--interval-ms"),
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run a bounded collection, then report what it saw AND what it missed.

    Ctrl-C stops it cleanly and keeps everything collected so far — interrupting
    an assessment must not throw away the days you already have.
    """
    from iaiops.core.collect.reader import read_point
    from iaiops.core.collect.runner import run_collection

    plan, target = _build_plan(endpoint, tags, duration, interval_ms)
    stopping = {"flag": False}

    def _handle(_signum, _frame):
        stopping["flag"] = True
        console.print("\n[yellow]Stopping — flushing what has been collected…[/]")

    previous = signal.signal(signal.SIGINT, _handle)
    try:
        result = run_collection(
            plan,
            target=target,
            reader=read_point,
            db_path=db,
            should_stop=lambda: stopping["flag"],
        )
    finally:
        signal.signal(signal.SIGINT, previous)

    if as_json:
        _emit(result.as_dict())
        return

    console.print(
        f"\n[bold]Collected[/] {result.samples_written:,} samples "
        f"({result.coverage_pct:g}% of intended) — {result.stopped_because}\n"
    )
    if result.gaps:
        console.print(f"[yellow]Blind for {len(result.gaps)} window(s):[/]")
        for gap in result.gaps[:10]:
            console.print(
                f"  · {gap['from_ts']} → {gap['to_ts']}  "
                f"({gap['samples_missed']} missed) {gap['reason']}"
            )
        console.print(
            "\n[dim]These are windows where collection was blind — NOT downtime. "
            "Treating them as stoppages would overstate losses.[/]"
        )
    console.print(f"[dim]{plan.resolution_note}[/]")


collect_app.command("plan")(collect_plan_cmd)
collect_app.command("run")(collect_run_cmd)
# Governance is applied app-wide by `govern_app` in _root, which wraps each
# COMMAND — so a run that samples for a week produces one audit row, not
# 604,800. That is the honest shape: the governed act is the decision to start
# sampling this scope for this long, and the row carries its result.

__all__ = ["collect_app"]
