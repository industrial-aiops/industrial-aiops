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

from pathlib import Path

import typer

from iaiops.cli._common import (
    _emit,
    cli_errors,
    console,
    humanize_seconds,
    run_state_samples,
)

#: How many audit rows to scan for post-incident actions. The engine returns
#: newest first, so this bounds the lookback rather than truncating the answer
#: at the wrong end.
AUDIT_ROWS_SCANNED = 2000

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
            "Open them from the stoppages already in the collected history: "
            "`iaiops case open <endpoint>`.[/]"
        )
        return

    console.print(f"\n[bold]{len(cases)} case(s)[/] — site {site}\n")
    for case in cases:
        state = case.label or ("dismissed" if case.answered else "awaiting")
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


#: A stoppage shorter than this opens no case. A week of 500ms sampling contains
#: thousands of micro-stops and nobody is going to explain them one by one; the
#: minor ones are what the OEE figure is for, the long ones are what a person can
#: still remember. Overridable, because "long" is a per-line judgement.
DEFAULT_CASE_MIN_STOP_S = 300.0

#: How far after a stoppage to look for the actions someone took. An hour is the
#: window ``case_from_audit`` itself defaults to.
FIX_WINDOW_S = 3600.0


@cli_errors
def case_open_cmd(
    endpoint: str = typer.Argument(..., help="Configured endpoint name."),
    site: str = typer.Option(DEFAULT_SITE, "--site"),
    min_stop_s: float = typer.Option(
        DEFAULT_CASE_MIN_STOP_S, "--min-stop-s", help="Stoppages shorter than this open no case."
    ),
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Open a case for each long stoppage found in the collected history.

    This is the entrance the learning loop was missing. `case list` already said
    "cases are opened from detected stoppages" — and nothing opened one, so the
    empty list read as "you have had no stoppages" rather than "nothing here ever
    creates a case", and the corpus could never grow at a real site.

    Each case carries what someone DID afterwards, taken from the audit trail —
    zero extra typing, because those actions were already recorded. It carries no
    label: what an action implies about the cause is for a person to say.

    Re-running is safe. A case id is derived from the endpoint and the onset, so
    the same stoppage re-opens as the same case rather than a duplicate, and one
    already answered keeps its answer.
    """
    from iaiops.core.brain.oee_measure import measure_availability
    from iaiops.core.governance.audit import get_engine
    from iaiops.core.knowledge.case_store import list_cases, open_case

    tag, samples = run_state_samples(endpoint, db)
    measured = measure_availability(samples, tag, minor_stop_s=min_stop_s)
    if measured["status"] not in ("ok", "insufficient_coverage"):
        console.print(f"\n[yellow]No cases opened ({measured['status']}).[/]")
        console.print(f"[dim]{measured['note']}[/]\n")
        return

    long_stops = [w for w in measured["stop_windows"] if not w["minor"]]
    answered = {c.incident_id for c in list_cases(site) if c.answered}
    audit_rows = get_engine().query(limit=AUDIT_ROWS_SCANNED)

    opened, kept = [], 0
    for window in long_stops:
        case = open_case(
            site,
            endpoint,
            window["onset"],
            ranked=(),
            audit_rows=audit_rows,
            base_dir=None,
        )
        # `open_case` returns an answered case untouched, so this only decides
        # what to PRINT. The protection is in the store, where every caller gets
        # it — this counter reporting "already answered" was true here while the
        # answer had already been overwritten, which is how the defect hid.
        if case.incident_id in answered:
            kept += 1
        else:
            opened.append((case, window))

    if as_json:
        _emit(
            {
                "endpoint": endpoint,
                "site": site,
                "stoppages_found": len(measured["stop_windows"]),
                "long_stoppages": len(long_stops),
                "opened": [c.as_fact().as_dict() for c, _ in opened],
                "already_answered": kept,
                "min_stop_s": min_stop_s,
            }
        )
        return

    console.print(
        f"\n[bold]{len(opened)} case(s) opened[/] — {endpoint} · site {site}"
        + (f" · {kept} already answered" if kept else "")
    )
    for case, window in opened:
        console.print(
            f"  [bold]{case.incident_id}[/]  {window['onset'][:19]}  "
            f"stopped {humanize_seconds(window['duration_s'])}"
            + (f" · {len(case.fix_actions)} action(s) recorded" if case.fix_actions else "")
        )
    minor = len(measured["stop_windows"]) - len(long_stops)
    console.print(
        f"\n[dim]{minor} stoppage(s) under {min_stop_s:g}s opened no case — those are what "
        "the OEE figure is for, not what a person can still remember. "
        "Answer with `iaiops case confirm <id> --cause <cause> --by <you>`.[/]"
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


case_app.command("open")(case_open_cmd)
case_app.command("list")(case_list_cmd)
case_app.command("causes")(case_causes_cmd)
case_app.command("confirm")(case_confirm_cmd)
case_app.command("dismiss")(case_dismiss_cmd)
case_app.command("agreement")(case_agreement_cmd)

__all__ = ["case_app"]
