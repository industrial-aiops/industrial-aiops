"""``iaiops knowledge`` — mount what is known about how this equipment fails.

HLD §13.8. Investigation step 07 asks whether a candidate cause is even possible
on this equipment. Until a library can be mounted, the honest answer is "this
product offers no way to tell you" — which is what it said.

The format follows ISO 14224 in keeping three levels apart: the failure **mode**
(what you observed), the **mechanism** (the physical process to go and check) and
the **cause** (what to fix). Entries attach to the taxonomy the learner already
speaks; they never add to it.

Contacts nothing. Mounting a library is a statement about equipment, not an
action on it.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

knowledge_app = typer.Typer(
    help="Mount and query what is known about how this equipment fails.",
    no_args_is_help=True,
)

_EXAMPLE = """\
version: 1
source: "Pump vendor manual rev C (2024)"   # required — where this came from
mechanisms:
  - cause: sensor_fault            # one of the taxonomy causes; never a new one
    mechanism: transmitter drift   # the physical process — what to go and check
    mode: reading frozen           # the observed effect — what you saw
    applies_to:
      protocols: [modbus]          # optional; absent means "applies anywhere"
    confirm_by:
      - loop check of the transmitter and its wiring
"""


@cli_errors
def mount_cmd(
    library: Path = typer.Argument(..., help="YAML mechanism library."),
    by: str = typer.Option(..., "--by", help="Who is mounting it."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
) -> None:
    """Mount a fault-mechanism library for a site.

    All or nothing: one bad entry refuses the whole file, because a half-mounted
    library is one nobody can reason about. Mounting replaces what was there.
    """
    from iaiops.core.knowledge.mechanisms import mount_library

    result = mount_library(library, by=by, site=site)
    console.print(
        f"\n[green]✓[/] mounted [bold]{result['mounted']}[/] mechanism(s) "
        f"for site [bold]{result['site']}[/]\n  [dim]source: {result['source']} "
        f"· mounted by {result['by']}[/]\n"
    )


@cli_errors
def list_cmd(
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable."),
) -> None:
    """Show what is mounted for a site."""
    from iaiops.core.knowledge.mechanisms import mounted_mechanisms

    found = mounted_mechanisms(site=site)
    if as_json:
        _emit([m.as_dict() for m in found])
        return
    if not found:
        console.print(
            "\nNo fault-mechanism library is mounted for this site.\n"
            "  [dim]iaiops knowledge mount <file.yaml> --by <you>[/]\n\n"
            "[dim]A library format, ISO 14224-shaped:[/]\n"
        )
        console.print(f"[dim]{_EXAMPLE}[/]")
        return
    console.print(f"\n[bold]{len(found)} mechanism(s)[/] — site [bold]{site}[/]\n")
    for m in found:
        where = ", ".join(m.protocols) if m.protocols else "any protocol"
        console.print(f"  [bold]{m.cause}[/] · {m.mechanism}")
        console.print(f"    [dim]mode: {m.mode} · applies to: {where} · from {m.source}[/]")
    console.print()


@cli_errors
def check_cmd(
    cause: str = typer.Argument(..., help="Candidate cause to check."),
    protocol: str = typer.Option("", "--protocol", help="Endpoint protocol, for applicability."),
    site: str = typer.Option("default", "--site", help="Site / plant boundary (D34)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable."),
) -> None:
    """What the mounted library has to say about one candidate cause.

    Three answers, and the difference between the first two is the point:
    NOTHING KNOWN (the library has never heard of it — which is not the same as
    it being cleared), KNOWN, or KNOWN AND EXCLUDED (every mechanism for it is
    inapplicable to this equipment).

    It never confirms. Raising a candidate to `confirmed` comes from outside the
    ranking — a measurement, a reproduction, or a person (D29).
    """
    from iaiops.core.knowledge.mechanisms import check_candidate

    verdict = check_candidate(cause, protocol=protocol, site=site)
    if as_json:
        _emit(verdict)
        return
    if verdict["status"] == "nothing_known":
        console.print(
            f"\n[yellow]?[/] [bold]{cause}[/] — nothing known\n  [dim]{verdict['reason']}[/]\n"
        )
        return
    if verdict["excluded"]:
        console.print(f"\n[red]✗[/] [bold]{cause}[/] — excluded\n  [dim]{verdict['reason']}[/]\n")
        return
    console.print(f"\n[green]•[/] [bold]{cause}[/] — {verdict['reason']}\n")
    for support in verdict["supports"]:
        console.print(f"  · {support['mechanism']}  [dim](mode: {support['mode']})[/]")
        console.print(f"    [dim]from {support['source']}[/]")
    if verdict["confirm_by"]:
        console.print("\n  [bold]To confirm it, go and do one of these:[/]")
        for step in verdict["confirm_by"]:
            console.print(f"    · {step}")
    console.print()


knowledge_app.command("mount")(mount_cmd)
knowledge_app.command("list")(list_cmd)
knowledge_app.command("check")(check_cmd)

__all__ = ["knowledge_app"]
