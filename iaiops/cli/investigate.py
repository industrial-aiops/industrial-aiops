"""``iaiops investigate plan`` — how far into an investigation this site could get.

Rendering only. Every judgement comes from :mod:`iaiops.core.investigate`, so
the CLI and a future App page show the same answer computed once (HLD D17,
§13.9) — the engine returns structure and each front-end decides how to draw it.

`plan` follows the convention `scan plan` and `collect plan` set: **it contacts
nothing**. That is what makes it runnable on a site nobody has authorised you to
probe yet, which is the site that most needs the answer.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

investigate_app = typer.Typer(
    help="Investigation readiness — how far the eight evidence steps could get here.",
    no_args_is_help=True,
)

_MARK = {"ready": ("✅", "green"), "degraded": ("⚠️ ", "yellow"), "blocked": ("❌", "red")}


@cli_errors
def plan_cmd(
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable report."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show every prerequisite, met or not."
    ),
) -> None:
    """Report how far an investigation could get here, and what each gap needs.

    Eight steps: define the incident, collect the evidence, normalize and check
    it, compress and rank, correlate the timeline, test the hypotheses, check
    against known mechanisms, conclude and close the loop.

    Contacts nothing — no device, no network, no historian. It answers the
    capability question only; running an actual investigation is a separate
    command over a real incident.
    """
    from iaiops.core.investigate import assess_investigation

    report = assess_investigation(db_path=db, site=site)
    if as_json:
        _emit(report.as_dict())
        return

    total = len(report.steps)
    reached = report.reachable_through
    console.print(
        f"\n[bold]Investigation readiness[/] — site [bold]{report.site}[/]\n"
        f"An investigation here would get through "
        f"[bold]{reached} of {total}[/] steps before it stops.\n"
    )

    for step in report.steps:
        mark, colour = _MARK[step.status]
        console.print(f"{mark} [{colour}]{step.number:02d} · {step.label}[/] — {step.headline}")
        console.print(f"   [dim]{step.value}[/]")
        shown = step.requirements if verbose else (step.missing_required + step.missing_optional)
        for req in shown:
            bullet = "[green]·[/]" if req.met else f"[{colour}]·[/]"
            console.print(f"   {bullet} [dim]{req.label}: {req.detail}[/]")
            if req.met:
                continue
            # NOT nested under `if req.fix`. An inexpressible requirement has no
            # fix by definition — that is the whole point of the flag — so
            # guarding this line on `fix` is how "the product offers no way to
            # supply this" ends up never being printed at all.
            if not req.expressible:
                console.print("     [yellow]→ this product offers no way to supply it yet[/]")
            elif req.fix:
                console.print(f"     [dim]→ {req.fix}[/]")
        console.print()

    if report.blocked_later:
        console.print("[bold]Blocked further along[/] — real gaps, but not why the walk stopped:")
        for step in report.blocked_later:
            console.print(f"  · {step.number:02d} {step.label} — {step.headline}")
        console.print()

    console.print("[dim]Nothing was contacted to produce this.[/]")


investigate_app.command("plan")(plan_cmd)

__all__ = ["investigate_app", "plan_cmd"]
