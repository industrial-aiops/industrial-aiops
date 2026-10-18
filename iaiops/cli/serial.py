"""``iaiops serial`` — serial ASCII instruments (HLD §17.4).

``sniff`` listens and prints raw lines: it sends nothing and needs no profile —
it is how a profile's pattern is written. Decoded reads: ``iaiops sensor read
<endpoint> ch:<name>``; collection: ``iaiops collect run``.
"""

from __future__ import annotations

import typer

from iaiops.cli._common import _emit, cli_errors, console

serial_app = typer.Typer(
    help="Serial ASCII instruments — sniff raw lines (sends nothing).",
    no_args_is_help=True,
)


@cli_errors
def sniff_cmd(
    endpoint: str = typer.Argument(..., help="Configured serial endpoint."),
    seconds: float = typer.Option(5.0, "--seconds", help="How long to listen (0.1–30)."),
    lines: int = typer.Option(20, "--lines", help="Stop after this many lines (1–200)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Listen and print raw lines. Opens the port exclusively; sends nothing."""
    from iaiops.connectors.serial import ops
    from iaiops.core.runtime.connection import ConnectionManager

    out = ops.sniff(ConnectionManager.from_config().target(endpoint), seconds, lines)
    if as_json:
        _emit(out)
        return
    for line in out["lines"]:
        typer.echo(repr(line))
    console.print(f"[dim]{len(out['lines'])} line(s) in {out['seconds']:g} s. {out['note']}[/]")


serial_app.command("sniff")(sniff_cmd)
