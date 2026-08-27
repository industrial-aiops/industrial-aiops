"""``iaiops relations`` — state which asset feeds which, on this line.

HLD §10.3② and D25. Relations are the second axis of root-cause analysis: with
time alone, an upstream stoppage produces a string of equally-confident
downstream false causes, because on a line downstream co-occurrence is
guaranteed whatever the cause.

That same guarantee is why this is a **declaration**, not a detector. A person
saying what order the line runs in needs no inference at all, and is the one
source D25 lets become an edge.

Contacts nothing. Declaring a relation is a statement about the plant, not an
action on it.
"""

from __future__ import annotations

import typer

from iaiops.cli._common import _emit, cli_errors, console

relations_app = typer.Typer(
    help="Declare which asset feeds which — the second axis of root-cause analysis.",
    no_args_is_help=True,
)


@cli_errors
def declare_cmd(
    upstream: str = typer.Argument(..., help="The asset that feeds the other."),
    downstream: str = typer.Argument(..., help="The asset it feeds."),
    by: str = typer.Option(..., "--by", help="Who is stating this. A person is the evidence."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
) -> None:
    """Record that one asset feeds another.

    Stored as a `declared` fact: highest trust, no evidence required beyond the
    person who said it. Re-declaring the same edge replaces it, and the audit
    chain keeps both — that is how a correction is made.
    """
    from iaiops.core.knowledge.relations import declare_relation

    rel = declare_relation(upstream, downstream, by=by, site=site)
    console.print(
        f"\n[green]✓[/] [bold]{rel.upstream}[/] feeds [bold]{rel.downstream}[/]"
        f"  [dim](declared by {rel.by}, site {site})[/]\n"
    )


@cli_errors
def list_cmd(
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable."),
) -> None:
    """Show the declared line order for a site."""
    from iaiops.core.knowledge.relations import line_relations

    found = line_relations(site=site)
    if as_json:
        _emit(
            [
                {"upstream": r.upstream, "downstream": r.downstream, "by": r.by, "source": r.source}
                for r in found
            ]
        )
        return
    if not found:
        console.print(
            "\nNo line relations declared for this site.\n"
            "  [dim]iaiops relations declare <upstream> <downstream> --by <you>[/]\n"
            "[dim]Without them, root-cause analysis has only time to go on — and on a "
            "line, everything downstream of a stoppage correlates with it.[/]\n"
        )
        return
    console.print(f"\n[bold]{len(found)} declared relation(s)[/] — site [bold]{site}[/]\n")
    for rel in found:
        console.print(f"  {rel.upstream} [dim]→[/] {rel.downstream}   [dim]({rel.by})[/]")
    console.print()


@cli_errors
def forget_cmd(
    upstream: str = typer.Argument(..., help="The upstream asset."),
    downstream: str = typer.Argument(..., help="The downstream asset."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
) -> None:
    """Withdraw a declared relation."""
    from iaiops.core.knowledge.relations import forget_relation

    if forget_relation(upstream, downstream, site=site):
        console.print(f"\n[green]✓[/] withdrew {upstream} → {downstream}\n")
        return
    console.print(f"\n[yellow]·[/] no such relation: {upstream} → {downstream}\n")


@cli_errors
def downstream_cmd(
    asset: str = typer.Argument(..., help="The asset to walk down from."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable."),
) -> None:
    """Everything this asset feeds, directly or through others — nearest first."""
    from iaiops.core.knowledge.relations import downstream_of

    found = downstream_of(asset, site=site)
    if as_json:
        _emit({"asset": asset, "downstream": list(found)})
        return
    if not found:
        console.print(f"\n[dim]Nothing is declared downstream of {asset}.[/]\n")
        return
    console.print(f"\n[bold]Downstream of {asset}[/] — nearest first:\n")
    for i, name in enumerate(found, 1):
        console.print(f"  {i}. {name}")
    console.print()


relations_app.command("declare")(declare_cmd)
relations_app.command("list")(list_cmd)
relations_app.command("forget")(forget_cmd)
relations_app.command("downstream")(downstream_cmd)

__all__ = ["relations_app"]
