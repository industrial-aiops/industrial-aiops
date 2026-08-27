"""``iaiops readiness`` — what this site can run today, and what each gap needs.

Rendering only. Every judgement comes from :mod:`iaiops.core.readiness`, so the
CLI and a future App page show the same answer computed once (HLD D17) — the
engine returns structure and each front-end decides how to draw it.

Contacts nothing. It is derived from ``config.yaml`` and the local store, which
is what makes it runnable on a site you have not been authorised to probe — the
site that most needs the answer.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

_MARK = {"ready": ("✅", "green"), "degraded": ("⚠️ ", "yellow"), "blocked": ("❌", "red")}


@cli_errors
def readiness_cmd(
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable report."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show every prerequisite, met or not."
    ),
) -> None:
    """Report which scenarios this installation can run, and what is blocking the rest.

    Re-run it after any site change: it doubles as a maturity baseline, and as the
    honest answer to "what would we have to invest to unlock X".

    It never fills a gap in for you. Which tag is the production counter is process
    knowledge, and a wrong guess yields plausible-looking numbers — worse than an error.
    """
    from iaiops.core.readiness import assess

    report = assess(db_path=db)
    if as_json:
        _emit(report.as_dict())
        return

    counts = report.summary
    console.print(
        f"\n[bold]Site readiness[/] — "
        f"[green]{counts['ready']} ready[/] · "
        f"[yellow]{counts['degraded']} degraded[/] · "
        f"[red]{counts['blocked']} blocked[/]\n"
    )

    for capability in report.capabilities:
        mark, colour = _MARK[capability.status]
        console.print(f"{mark} [{colour}]{capability.label}[/] — {capability.headline}")
        console.print(f"   [dim]{capability.value}[/]")
        shown = capability.requirements if verbose else _gaps(capability)
        for req in shown:
            bullet = "[green]·[/]" if req.met else f"[{colour}]·[/]"
            console.print(f"   {bullet} [dim]{req.label}: {req.detail}[/]")
            if req.met:
                continue
            # NOT nested under `if req.fix`. An inexpressible requirement has no
            # fix BY DEFINITION, so guarding on `fix` made this the one line that
            # could never print — the honesty note was unreachable from the day
            # it was written. Found 2026-08-26 while adding the first producer of
            # `expressible=False` (iaiops/core/investigate/steps.py).
            if not req.expressible:
                console.print("     [yellow]→ this product offers no way to supply it yet[/]")
            elif req.fix:
                console.print(f"     [dim]→ {req.fix}[/]")
        console.print()

    if report.blocked_on:
        console.print("[bold]Supply these first[/] — ranked by how much each unlocks:")
        for entry in report.blocked_on:
            console.print(f"  · {entry}")
        console.print()

    for note in report.notes:
        console.print(f"[dim]{note}[/]")


def _gaps(capability):
    return capability.missing_required + capability.missing_optional


__all__ = ["readiness_cmd"]
