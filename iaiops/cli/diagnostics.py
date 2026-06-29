"""``iaiops diag ...`` — cross-protocol intelligent troubleshooting (read-only).

The flood/tag/historian analyzers consume a JSON list of events/samples; pass a
path to a JSON file (``--input events.json``) so the CLI stays scriptable.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.core.brain import diagnostics as diag

diag_app = typer.Typer(help="Cross-protocol intelligent troubleshooting (read-only).",
                       no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


def _load_json(path: Path):
    return json.loads(Path(path).read_text("utf-8"))


@diag_app.command("dataflow")
@cli_errors
def dataflow_cmd(
    endpoint: EndpointOption = None,
    ref: str = typer.Option(None, "--ref", help="Tag/node/address to read"),
    freshness_s: int = typer.Option(60, "--freshness-s"),
) -> None:
    """Localize a 'no data' break across an endpoint's reachable hops."""
    _emit(diag.diagnose_dataflow(resolve_target(endpoint), ref, freshness_s))


@diag_app.command("alarms")
@cli_errors
def alarms_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of alarm events"),
) -> None:
    """ISA-18.2 alarm-flood analysis over a JSON list of events."""
    _emit(diag.alarm_bad_actors(_load_json(input)))


@diag_app.command("tags")
@cli_errors
def tags_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of {ref, samples:[...]}"),
) -> None:
    """Rank tag offenders by quality/flatline/range/anomaly over JSON samples."""
    _emit(diag.tag_health(_load_json(input)))


@diag_app.command("historian")
@cli_errors
def historian_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of samples"),
    gap_s: float = typer.Option(60.0, "--gap-s"),
) -> None:
    """Bad-tag / flatline / gap detection over a JSON sample series."""
    _emit(diag.historian_health(_load_json(input), gap_s))
