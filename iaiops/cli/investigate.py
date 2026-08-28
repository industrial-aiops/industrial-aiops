"""``iaiops investigate plan`` — how far into an investigation this site could get.

Rendering only. Every judgement comes from :mod:`iaiops.core.investigate`, so
the CLI and a future App page show the same answer computed once (HLD D17,
§13.9) — the engine returns structure and each front-end decides how to draw it.

`plan` follows the convention `scan plan` and `collect plan` set: **it contacts
nothing**. That is what makes it runnable on a site nobody has authorised you to
probe yet, which is the site that most needs the answer.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

investigate_app = typer.Typer(
    help="Investigation readiness — how far the eight evidence steps could get here.",
    no_args_is_help=True,
)


def _plan_html(payload: dict, *, lang: str, generated_at: str) -> str:
    from iaiops.core.investigate.report import render_plan_report

    return render_plan_report(payload, lang=lang, generated_at=generated_at)


def _live_html(payload: dict, *, lang: str, generated_at: str) -> str:
    from iaiops.core.investigate.report import render_live_report

    return render_live_report(payload, lang=lang, generated_at=generated_at)


def _write_report(report: Path | None, html_for: Callable[[str, str], str], lang: str) -> None:
    """Write the forwardable file, or nothing at all when it was not asked for.

    Deliberately WITHOUT the guard `oee measure --report` carries. That command
    refuses to write when the measurement was refused, and is right to: an OEE
    report is a number, so a file existing at all asserts one was measured. Here
    the content IS how far this got and what each step still needs, so a blocked
    investigation is the case most worth handing over — an uninstrumented site is
    precisely who this report is for.

    The path guard is the same one `scan` and `oee` use: `..` traversal and a
    wrong extension are refused before a byte is written.
    """
    if report is None:
        return
    from datetime import UTC, datetime

    from iaiops.core.governance.evidence import validate_output_path

    path = validate_output_path(report, suffixes=(".html", ".htm"))
    path.write_text(
        html_for(lang, datetime.now(UTC).isoformat(timespec="seconds")), encoding="utf-8"
    )
    console.print(f"[dim]report written to {path}[/]")


_MARK = {"ready": ("✅", "green"), "degraded": ("⚠️ ", "yellow"), "blocked": ("❌", "red")}


@cli_errors
def plan_cmd(
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable report."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show every prerequisite, met or not."
    ),
    report_path: Path = typer.Option(
        None, "--report", help="Also write a self-contained HTML report here."
    ),
    lang: str = typer.Option("en", "--lang", help="Report language (en, zh)."),
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
    _write_report(
        report_path,
        lambda lg, at: _plan_html(report.as_dict(), lang=lg, generated_at=at),
        lang,
    )
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


_STATE = {
    "done": ("✅", "green"),
    "refused": ("⚠️ ", "yellow"),
    "not_possible": ("🚧", "magenta"),
    "pending": ("·", "dim"),
}


@cli_errors
def open_cmd(
    endpoint: str = typer.Argument(..., help="Endpoint the incident happened on."),
    start: str = typer.Option(..., "--start", help="Incident onset (ISO-8601)."),
    end: str = typer.Option(..., "--end", help="Incident end (ISO-8601)."),
    asset: str = typer.Option("", "--asset", help="Machine / line label."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable report."),
    report_path: Path = typer.Option(
        None, "--report", help="Also write a self-contained HTML report here."
    ),
    lang: str = typer.Option("en", "--lang", help="Report language (en, zh)."),
) -> None:
    """Open an investigation over one window and walk what can be walked.

    Contacts no device — the window is already past, and the evidence for it is
    whatever was collected at the time. Every step records its own outcome, so a
    step that could not run says why, and one this product cannot do at all says
    that instead.

    The investigation is saved, so it can be re-read and advanced later.
    """
    from iaiops.core.investigate.live import (
        advance,
        open_investigation,
        save_investigation,
    )

    inv = advance(
        open_investigation(endpoint=endpoint, start=start, end=end, asset=asset, site=site),
        db_path=db,
    )
    save_investigation(inv)
    _write_report(
        report_path, lambda lg, at: _live_html(inv.as_dict(), lang=lg, generated_at=at), lang
    )
    _render(inv, as_json)


@cli_errors
def show_cmd(
    investigation_id: str = typer.Argument(..., help="Investigation id (see `investigate list`)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable report."),
    report_path: Path = typer.Option(
        None, "--report", help="Also write a self-contained HTML report here."
    ),
    lang: str = typer.Option("en", "--lang", help="Report language (en, zh)."),
) -> None:
    """Re-read a saved investigation — the state it was left in."""
    from iaiops.core.investigate.live import load_investigation

    inv = load_investigation(investigation_id)
    _write_report(
        report_path, lambda lg, at: _live_html(inv.as_dict(), lang=lg, generated_at=at), lang
    )
    _render(inv, as_json)


@cli_errors
def list_cmd(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable report."),
) -> None:
    """List saved investigations, newest first."""
    from iaiops.core.investigate.live import list_investigations

    found = list_investigations()
    if as_json:
        _emit([i.as_dict() for i in found])
        return
    if not found:
        console.print(
            "\nNo investigations yet. Open one over a window you care about:\n"
            "  [dim]iaiops investigate open <endpoint> --start <iso> --end <iso>[/]\n"
        )
        return
    console.print(f"\n[bold]{len(found)} investigation(s)[/]\n")
    for inv in found:
        console.print(
            f"  [bold]{inv.id}[/]  {inv.scope.start} → {inv.scope.end}  "
            f"[dim]reached {inv.reached}/{len(inv.steps)}[/]"
        )
    console.print()


def _render(inv, as_json: bool) -> None:
    if as_json:
        _emit(inv.as_dict())
        return
    console.print(
        f"\n[bold]Investigation {inv.id}[/] — site [bold]{inv.site}[/]\n"
        f"{inv.scope.asset or inv.scope.endpoint}  {inv.scope.start} → {inv.scope.end}\n"
        f"Walked [bold]{inv.reached} of {len(inv.steps)}[/] steps.\n"
    )
    for step in inv.steps:
        mark, colour = _STATE.get(step.state, ("·", "dim"))
        console.print(f"{mark} [{colour}]{step.number:02d} · {step.label}[/]")
        console.print(f"   [dim]{step.summary}[/]")
    console.print("\n[dim]No device was contacted — the window is already past.[/]")


investigate_app.command("plan")(plan_cmd)
investigate_app.command("open")(open_cmd)
investigate_app.command("show")(show_cmd)
investigate_app.command("list")(list_cmd)

__all__ = ["investigate_app", "plan_cmd", "open_cmd", "show_cmd", "list_cmd"]
