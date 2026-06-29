"""``iaiops analytics ...`` — OEE / downtime / asset-inventory (read-only).

The OEE/downtime analyzers consume a JSON list (``--input file.json``) so the CLI
stays scriptable; ``asset`` actively fingerprints configured endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from iaiops.cli._common import cli_errors, get_manager
from iaiops.core.brain import asset_inventory as asset
from iaiops.core.brain import oee

analytics_app = typer.Typer(help="OEE / downtime / asset-inventory analytics (read-only).",
                            no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


def _load_json(path: Path):
    return json.loads(Path(path).read_text("utf-8"))


@analytics_app.command("oee")
@cli_errors
def oee_cmd(
    planned_time_s: float,
    run_time_s: float,
    ideal_cycle_time_s: float,
    total_count: float,
    good_count: float,
) -> None:
    """Compute OEE = Availability × Performance × Quality from inputs."""
    _emit(oee.oee_compute(planned_time_s, run_time_s, ideal_cycle_time_s,
                          total_count, good_count))


@analytics_app.command("downtime")
@cli_errors
def downtime_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of {timestamp, state}"),
    min_duration_s: float = typer.Option(0.0, "--min-duration-s"),
) -> None:
    """Detect + categorize stoppages from a JSON state series."""
    _emit(oee.downtime_events(_load_json(input), None, min_duration_s))


@analytics_app.command("oee-multidim")
@cli_errors
def oee_multidim_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of labelled records"),
) -> None:
    """Aggregate OEE across dimensions (machine × part × shift) from JSON records."""
    _emit(oee.oee_multidim(_load_json(input)))


@analytics_app.command("asset")
@cli_errors
def asset_cmd(
    endpoint: list[str] = typer.Option(None, "--endpoint", "-e",
                                       help="Endpoint name (repeatable; omit = all)"),
) -> None:
    """Actively fingerprint configured endpoints into an asset register."""
    mgr = get_manager()
    names = list(endpoint) if endpoint else mgr.list_targets()
    targets = [mgr.target(n) for n in names]
    _emit(asset.asset_inventory(targets))
