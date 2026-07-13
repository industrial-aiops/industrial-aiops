"""``iaiops analytics ...`` — OEE / downtime / asset-inventory (read-only).

The OEE/downtime analyzers consume a JSON list (``--input file.json``) so the CLI
stays scriptable; ``asset`` actively fingerprints configured endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, get_manager
from iaiops.core.brain import alias_store as als
from iaiops.core.brain import asset_inventory as asset
from iaiops.core.brain import asset_model as amodel
from iaiops.core.brain import oee

analytics_app = typer.Typer(
    help="OEE / downtime / asset-inventory analytics (read-only).", no_args_is_help=True
)


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
    _emit(oee.oee_compute(planned_time_s, run_time_s, ideal_cycle_time_s, total_count, good_count))


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


@analytics_app.command("asset-model")
@cli_errors
def asset_model_cmd(
    input: Path = typer.Option(
        ..., "--input", help="JSON file: list of {protocol, source, asset?, tags:[...]}"
    ),
    site: str = typer.Option("site", "--site", help="Site prefix for canonical aliases"),
) -> None:
    """Fuse per-protocol tag feeds into ONE cross-protocol asset/tag/alias model."""
    _emit(amodel.cross_protocol_asset_model(_load_json(input), site))


@analytics_app.command("alias-adopt")
@cli_errors
def alias_adopt_cmd(
    input: Path = typer.Option(
        ..., "--input", help="JSON file: list of {protocol, source, asset?, tags:[...]}"
    ),
    site: str = typer.Option("site", "--site", help="Site label (a safe file leaf)"),
) -> None:
    """Adopt + persist the canonical alias map for a site (baseline for alias-diff)."""
    model = amodel.cross_protocol_asset_model(_load_json(input), site)
    adopted = als.extract_alias_map(model)
    path = als.save_alias_map(site, adopted)
    _emit({"site": model["site"], "path": str(path), "tag_count": len(adopted), "adopted": adopted})


@analytics_app.command("alias-diff")
@cli_errors
def alias_diff_cmd(
    input: Path = typer.Option(
        ..., "--input", help="JSON file: list of {protocol, source, asset?, tags:[...]}"
    ),
    site: str = typer.Option("site", "--site", help="Site label whose baseline to diff against"),
) -> None:
    """Diff a fresh discovery run against the adopted baseline for a site."""
    previous = als.load_alias_map(site)
    model = amodel.cross_protocol_asset_model(_load_json(input), site)
    diff = als.diff_alias_map(previous, als.extract_alias_map(model))
    _emit({"site": model["site"], **diff})


@analytics_app.command("alias-sites")
@cli_errors
def alias_sites_cmd() -> None:
    """List sites that have an adopted alias-map baseline."""
    _emit({"sites": als.list_sites()})


@analytics_app.command("asset")
@cli_errors
def asset_cmd(
    endpoint: list[str] = typer.Option(
        None, "--endpoint", "-e", help="Endpoint name (repeatable; omit = all)"
    ),
) -> None:
    """Actively fingerprint configured endpoints into an asset register."""
    mgr = get_manager()
    names = list(endpoint) if endpoint else mgr.list_targets()
    targets = [mgr.target(n) for n in names]
    _emit(asset.asset_inventory(targets))
