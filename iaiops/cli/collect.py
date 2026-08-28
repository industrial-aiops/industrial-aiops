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
from dataclasses import replace
from datetime import UTC
from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console, humanize_seconds

# Light enough for module scope: `plan` imports only `re` and `dataclasses`.
from iaiops.core.collect.plan import MAX_DURATION_S

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
    resume: bool = typer.Option(
        False, "--resume", help="Continue an interrupted run instead of starting over."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run a bounded collection, then report what it saw AND what it missed.

    Ctrl-C stops it cleanly and keeps everything collected so far — interrupting
    an assessment must not throw away the days you already have.
    """
    from datetime import datetime

    from iaiops.core.collect.reader import (
        read_point,
        session_builder_for,
        session_read_for,
    )
    from iaiops.core.collect.runner import run_collection
    from iaiops.core.collect.session import (
        Session,
        find_resumable,
        save_session,
    )
    from iaiops.core.runtime.config import load_config

    now = datetime.now(UTC)
    session = find_resumable(endpoint, now=now) if resume else None
    if resume and session is None:
        console.print(
            f"[yellow]No interrupted run for {endpoint!r} with time left — starting a new one.[/]"
        )

    if session is not None:
        # The ORIGINAL terms, not fresh ones: resuming with a different interval
        # would produce a series whose resolution changes half-way through.
        plan = session.plan
        target = load_config().get_target(endpoint)
        session = session.resumed_at(now.isoformat())
        remaining = session.remaining_s(now)
        console.print(
            f"[bold]Resuming[/] {session.run_id} — {humanize_seconds(remaining)} left of "
            f"the original window; {humanize_seconds(session.blind_s)} blind so far."
        )
        plan = replace(plan, duration_s=int(remaining))
    else:
        plan, target = _build_plan(endpoint, tags, duration, interval_ms)
        session = Session(
            run_id=f"{endpoint}-{now.strftime('%Y%m%dT%H%M%S')}",
            plan=plan,
            started_at=now.isoformat(),
        )
    save_session(session)

    stopping = {"flag": False}

    def _handle(_signum, _frame):
        stopping["flag"] = True
        console.print("\n[yellow]Stopping — flushing what has been collected…[/]")

    previous = signal.signal(signal.SIGINT, _handle)
    try:
        # One connection for the run where the protocol allows it. Measured:
        # per-read connecting opens 3.7 TCP connections a second, which is 1.8
        # million across a week — fine for the client, potentially fatal for a
        # PLC that caps connections in the single digits.
        protocol = str(getattr(target, "protocol", ""))
        in_session = session_read_for(protocol)
        result = run_collection(
            plan,
            target=target,
            reader=in_session or read_point,
            db_path=db,
            should_stop=lambda: stopping["flag"],
            session_builder=session_builder_for(protocol) if in_session else None,
        )
    finally:
        signal.signal(signal.SIGINT, previous)

    ended = datetime.now(UTC)
    if result.stopped_because == "duration_reached" and session.remaining_s(ended) <= 1.0:
        save_session(session.completed())
    else:
        # Paused, not finished. The clock keeps running on the plant, so the time
        # from here until a resume is blind — recorded now so it cannot be lost.
        save_session(session.paused_at(ended.isoformat()))

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
    if session.gaps:
        console.print(
            f"\n[yellow]This run was interrupted {len(session.gaps)} time(s), "
            f"{humanize_seconds(session.blind_s)} blind in total.[/] "
            "[dim]The line kept running and was not observed — that time is excluded "
            "from any figure rather than counted as downtime.[/]"
        )
    if not session.is_finished(ended):
        console.print(
            f"[dim]Window not finished — resume with `iaiops collect run {endpoint} --resume`.[/]"
        )


# The governance timeout is a hang detector, and this command is SUPPOSED to run
# for as long as it was asked to — up to MAX_DURATION_S. At the 300s default,
# every real assessment run ended with "exceeded timeout_seconds=300", which
# reads as a fault at the end of a run that did exactly what was asked. The
# ceiling is the longest window the planner will accept, plus room for startup
# and the final write, so a genuine hang is still caught.
collect_run_cmd._cli_timeout_seconds = MAX_DURATION_S + 300

collect_app.command("plan")(collect_plan_cmd)
collect_app.command("run")(collect_run_cmd)
# Governance is applied app-wide by `govern_app` in _root, which wraps each
# COMMAND — so a run that samples for a week produces one audit row, not
# 604,800. That is the honest shape: the governed act is the decision to start
# sampling this scope for this long, and the row carries its result.

__all__ = ["collect_app"]
