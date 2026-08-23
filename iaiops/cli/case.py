"""``iaiops case`` — the one-choice confirmation that closes the learning loop.

`learn_cause_weights` could always learn from labelled incidents; what it never
had was a way to GROW that corpus at a site. This is that way, and its shape is
the whole point.

**One choice among the causes, never a text box.** Free-text causes are why a
CMMS corpus needs synonym mapping and still arrives full of "Fixed it" — a label
captured here arrives in the vocabulary the learner already speaks.

**A dismissal is a label too, and free.** Saying "that was not an incident" costs
one keystroke and is usually the most plentiful signal on a real line.

And nothing here lets the answerer say how independent their own answer was: the
capture mode is derived from whether the cause was one we had suggested. That is
what keeps the anchoring measurement honest.
"""

from __future__ import annotations

import typer

from iaiops.cli._common import _emit, cli_errors, console

case_app = typer.Typer(help="Incidents awaiting a cause, and the one-choice answer.")

DEFAULT_SITE = "default"


@cli_errors
def case_list_cmd(
    site: str = typer.Option(DEFAULT_SITE, "--site"),
    pending: bool = typer.Option(True, "--pending/--all", help="Only cases awaiting a cause."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show incidents waiting for someone to say what happened."""
    from iaiops.core.knowledge.case_store import list_cases

    cases = list_cases(site, pending_only=pending, base_dir=None)
    if as_json:
        _emit([c.as_fact().as_dict() for c in cases])
        return
    if not cases:
        console.print(
            f"\n[dim]No {'pending ' if pending else ''}cases for site {site!r}. "
            "Cases are opened from detected stoppages.[/]"
        )
        return

    console.print(f"\n[bold]{len(cases)} case(s)[/] — site {site}\n")
    for case in cases:
        state = case.label or ("dismissed" if "dismissed" in case.note.lower() else "awaiting")
        console.print(f"  [bold]{case.incident_id}[/]  {case.when[:19]}  → {state}")
        if case.ranked:
            console.print(f"     [dim]we ranked: {', '.join(case.ranked)}[/]")
        for action in case.fix_actions[:3]:
            console.print(
                f"     [dim]then {action.get('user', '?')} ran {action.get('tool', '?')} "
                f"at {action.get('ts', '')[:19]}[/]"
            )
    console.print(
        "\n[dim]Confirm with `iaiops case confirm <id> --cause <cause> --by <you>`, "
        "or `iaiops case dismiss <id> --by <you>` if it was not an incident.[/]"
    )


@cli_errors
def case_causes_cmd() -> None:
    """List the causes a confirmation may use."""
    from iaiops.core.brain.rca_weights import LEARNABLE_CAUSES

    console.print("\n[bold]Causes[/] — a confirmation picks one of these, never free text:\n")
    for cause in sorted(LEARNABLE_CAUSES):
        console.print(f"  · {cause}")
    console.print(
        "\n[dim]Free text is why an imported CMMS corpus needs synonym mapping and still "
        "arrives full of 'Fixed it'. A label captured here speaks the learner's own "
        "vocabulary.[/]"
    )


@cli_errors
def case_confirm_cmd(
    incident_id: str = typer.Argument(..., help="From `iaiops case list`."),
    cause: str = typer.Option(..., "--cause", help="One of `iaiops case causes`."),
    by: str = typer.Option(..., "--by", help="Who is confirming — recorded with the label."),
    site: str = typer.Option(DEFAULT_SITE, "--site"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Record what actually caused an incident.

    Whether this counts as an ANCHORED answer is decided here, not chosen: if the
    cause was one this tool had ranked, the label is marked anchored. That is
    what makes the agreement rate mean something.
    """
    from iaiops.core.knowledge.case_store import confirm_case

    done = confirm_case(site, incident_id, cause=cause, by=by, base_dir=None)
    if as_json:
        _emit(done.as_fact().as_dict())
        return
    console.print(f"\n[green]Recorded[/] {done.incident_id} → [bold]{done.label}[/]")
    console.print(f"  [dim]{done.note}[/]")
    if done.anchored:
        console.print(
            "  [dim]Anchored labels still train the weights, but a site whose agreement "
            "rate climbs above 90% is more likely being led than being right — check with "
            "`iaiops case agreement`.[/]"
        )


@cli_errors
def case_dismiss_cmd(
    incident_id: str = typer.Argument(...),
    by: str = typer.Option(..., "--by"),
    site: str = typer.Option(DEFAULT_SITE, "--site"),
) -> None:
    """Mark a case as not an incident — a negative label, and free."""
    from iaiops.core.knowledge.case_store import dismiss_case

    done = dismiss_case(site, incident_id, by=by, base_dir=None)
    console.print(f"\n[green]Dismissed[/] {done.incident_id}")
    console.print(f"  [dim]{done.note}[/]")


@cli_errors
def case_agreement_cmd(
    site: str = typer.Option(DEFAULT_SITE, "--site"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """How often a person agreed with us — and how much of that was anchored."""
    from iaiops.core.knowledge.case_store import list_cases
    from iaiops.core.knowledge.cases import agreement_report

    report = agreement_report(list_cases(site, base_dir=None))
    if as_json:
        _emit(report)
        return
    if not report["n_cases"]:
        console.print(f"\n[dim]{report['note']}[/]")
        return
    console.print(f"\n[bold]Agreement[/] — {report['n_cases']} evidence case(s), site {site}\n")
    console.print(f"  agreed with our top hypothesis : {report['agreement_pct']:g}%")
    console.print(f"  labels shaped by our ranking   : {report['anchored_pct']:g}%")
    for mode, count in sorted(report["by_capture"].items()):
        console.print(f"    [dim]{mode}: {count}[/]")
    if report["warning"]:
        console.print(f"\n[yellow]{report['warning']}[/]")


case_app.command("list")(case_list_cmd)
case_app.command("causes")(case_causes_cmd)
case_app.command("confirm")(case_confirm_cmd)
case_app.command("dismiss")(case_dismiss_cmd)
case_app.command("agreement")(case_agreement_cmd)

__all__ = ["case_app"]
