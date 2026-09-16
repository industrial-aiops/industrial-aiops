"""``iaiops onboard`` — one path from a network to an answer.

Rendering only. Both judgements come from :mod:`iaiops.core.onboard`, so a CLI
and a future App page show the same answer computed once (HLD D17).

``status`` is the command this product was missing outright: seven commands in a
fixed order, and nothing told anyone which one they were on. It is derived from
the store and ``config.yaml`` every time — there is no onboarding state file to
go stale, so editing config.yaml by hand still gives a true answer.

``draft`` carries the scan's findings into a config draft instead of making a
site retype forty devices. It writes nothing into ``config.yaml``: like
``iaiops tags apply``, it emits the edit and a person merges it. Every drafted
value names the observation that justifies it, and every field the scan could
not settle goes out commented, with what it is waiting for.

Contacts nothing.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich import markup

from iaiops.cli._common import _emit, cli_errors, console

onboard_app = typer.Typer(
    help="The path from scan to answer — where this site stands, and what is next.",
    no_args_is_help=True,
)

_MARK = {
    "done": ("[green]✓[/]", "green"),
    "next": ("[bold yellow]▶[/]", "bold yellow"),
    "waiting": ("[dim]·[/]", "dim"),
}


@cli_errors
def status_cmd(
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable path."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show why each step exists."),
    track: str = typer.Option(
        "auto",
        "--track",
        help="Which journey: auto (derive from config.yaml), devices, or uns.",
    ),
) -> None:
    """Show which journey this site is on, where it stands, and the next move.

    Two journeys: `devices` (no UNS yet — survey, then read PLCs directly) and
    `uns` (the data already flows through an MQTT/UNS broker — connect, audit
    the namespace, then subscribe). The journey is derived from config.yaml;
    when nothing is configured, or both kinds of endpoint are, it asks.

    Reads nothing but the local store and config.yaml, so it answers on a site
    you have not been authorised to probe — which is the site that most needs it.
    """
    from iaiops.core.onboard.path import assess_path

    path = assess_path(db_path=db, track=track)
    if as_json:
        _emit(path.as_dict())
        return

    # Step text quotes REFS and commands — `group/edge[/device]:metric`, a topic
    # with a `[` in it. Rich reads `[/device]` as a closing tag and either raises
    # or silently eats the text, so every field that can carry site data or a
    # printed command is escaped before it reaches the console.
    esc = markup.escape
    total = len(path.steps)
    nxt = path.next_step
    if nxt is None:
        console.print(f"\n[bold]Onboarding[/] — all {total} steps done\n")
    else:
        # The cursor's own position, not a count. `done + 1` is a different
        # number the moment a later step is already done, and it read as
        # "you are on step 6" on a site that had finished step 6.
        console.print(
            f"\n[bold]Onboarding[/] — step {path.steps.index(nxt) + 1} of {total} "
            f"([green]{path.done_count} done[/])\n"
        )
    if path.track:
        console.print(f"[dim]journey: {path.track} — {esc(path.track_detail)}[/]\n")
    for note in path.notes:
        console.print(f"[yellow]![/] {esc(note)}\n")

    for index, step in enumerate(path.steps, start=1):
        mark, colour = _MARK.get(step.state, ("[dim]?[/]", "dim"))
        console.print(f"{mark} [{colour}]{index}. {esc(step.label)}[/]")
        console.print(f"   [dim]{esc(step.detail)}[/]")
        if verbose and step.why:
            console.print(f"   [dim italic]{esc(step.why)}[/]")

    if nxt is None:
        console.print(
            "\n[green]Every step is done.[/] "
            "[dim]`iaiops readiness` lists what this site can now run.[/]\n"
        )
    elif nxt.choices:
        # A question the files on disk cannot answer. Both answers, labelled, and
        # neither pre-selected — picking one here would be the tool guessing
        # what kind of site this is.
        # The detail is already printed under the step; repeating it here put the
        # same paragraph on screen twice.
        console.print(f"\n[bold]Next:[/] {esc(nxt.label)}\n")
        for label, command in nxt.choices:
            console.print(f"  [bold]·[/] {esc(label)}\n\n      {esc(command)}\n")
    elif nxt.command:
        console.print(f"\n[bold]Next:[/]\n\n    {esc(nxt.command)}\n")
    else:
        console.print(
            f"\n[bold]Next:[/] {esc(nxt.label)} — [dim]no single command does this "
            f"one; {esc(nxt.detail)}[/]\n"
        )


@cli_errors
def draft_cmd(
    scan_id: str = typer.Argument(None, help="Which stored scan (default: the newest)."),
    db: Path = typer.Option(None, "--db", help="Store file (default: the local iaiops store)."),
    out: Path = typer.Option(None, "--out", help="Write the draft here instead of stdout."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable draft."),
) -> None:
    """Print the config.yaml endpoints a scan can justify — and only those.

    Nothing is written to config.yaml. Merge what you agree with, then run
    `iaiops onboard status` to see what it unlocked.

    Only protocols the scan CONFIRMED become endpoints. An open port means
    something is listening, not that it speaks the protocol, and a config that
    says otherwise would be believed. `tags:` comes out empty: a scan finds
    devices, never what their data means.
    """
    from iaiops.core.governance.evidence import validate_output_path
    from iaiops.core.onboard import draft_from_scan, render_yaml
    from iaiops.core.onboard.config_state import existing_endpoints
    from iaiops.core.sink.scan_store import list_scans, load_scan

    stored = list_scans(db, 1)
    if not stored:
        raise ValueError(
            "No scan has been stored, so there is nothing to draft from. "
            "Run `iaiops scan plan --targets <cidr>` to see what a scan would do, "
            "then `iaiops scan run --targets <cidr> --approved-by <you>`."
        )
    record = load_scan(scan_id or stored[0].scan_id, db)

    existing, addresses, config_error = existing_endpoints()
    if config_error:
        console.print(
            f"\n[yellow]![/] config.yaml did not parse ({config_error}).\n"
            "  [dim]Everything below is drafted as if your config were empty, so an\n"
            "  endpoint you have already tuned may be offered again. Fix the file\n"
            "  and re-run before you merge any of this.[/]\n"
        )

    draft = draft_from_scan(record, existing, addresses)
    if as_json:
        _emit(draft.as_dict())
        return

    text = render_yaml(draft)
    if out is not None:
        path = validate_output_path(out, suffixes=(".yaml", ".yml"))
        path.write_text(text, encoding="utf-8")
        console.print(f"\n[green]✓[/] draft written to [bold]{path}[/]")
    else:
        # soft_wrap: the renderer already wrapped every comment to fit. Letting
        # rich re-wrap would break a comment across two lines, and the second
        # line has no `#` — so the block a person pastes would not parse.
        console.print(text, highlight=False, soft_wrap=True)

    ready = len(draft.pastable)
    open_questions = sum(len(e.open_questions) for e in draft.pastable)
    console.print(
        f"\n[green]✓[/] {ready} endpoint(s) drafted from scan [bold]{draft.scan_id}[/]"
        + (f", {len(draft.skipped)} host(s) skipped" if draft.skipped else "")
        + (f", {open_questions} field(s) the scan could not settle" if open_questions else "")
        + "\n  [dim]Nothing was written to config.yaml. Merge what you agree with,\n"
        "  then `iaiops onboard status` for the next step.[/]\n"
    )


onboard_app.command("status")(status_cmd)
onboard_app.command("draft")(draft_cmd)

__all__ = ["onboard_app", "status_cmd", "draft_cmd"]
