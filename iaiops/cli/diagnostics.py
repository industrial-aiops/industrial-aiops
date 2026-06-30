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
from iaiops.core.brain import dataquality as dq
from iaiops.core.brain import diagnostics as diag
from iaiops.core.brain import rca as rca_brain
from iaiops.core.brain import rca_collect, rca_weights

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


@diag_app.command("dataquality")
@cli_errors
def dataquality_cmd(
    input: Path = typer.Option(..., "--input",
                               help="JSON file: list of {endpoint, tags:[{ref, samples}]}"),
    staleness_s: float = typer.Option(300.0, "--staleness-s"),
    now: str = typer.Option(None, "--now", help="ISO-8601 staleness reference (deterministic)"),
) -> None:
    """Fleet data-trust scorecard (staleness / heartbeat / quality) across feeds."""
    _emit(dq.data_quality_scorecard(_load_json(input), staleness_s, now))


@diag_app.command("dataquality-fleet")
@cli_errors
def dataquality_fleet_cmd(
    input: Path = typer.Option(..., "--input",
                               help="JSON file: list of {endpoint, tags:[{ref, samples}]}"),
    staleness_s: float = typer.Option(300.0, "--staleness-s"),
    now: str = typer.Option(None, "--now", help="ISO-8601 staleness reference (deterministic)"),
    top_n: int = typer.Option(10, "--top-n", help="How many endpoints / bad-quality rows"),
) -> None:
    """Cross-endpoint fleet rollup: worst tags + bad-quality counts across endpoints."""
    _emit(dq.data_quality_fleet_rollup(_load_json(input), staleness_s, now, top_n))


@diag_app.command("heartbeat")
@cli_errors
def heartbeat_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of heartbeat samples"),
    max_interval_s: float = typer.Option(None, "--max-interval-s"),
) -> None:
    """Heartbeat/watchdog liveness check over a JSON sample series."""
    _emit(dq.heartbeat_health(_load_json(input), max_interval_s))


@diag_app.command("historian")
@cli_errors
def historian_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of samples"),
    gap_s: float = typer.Option(60.0, "--gap-s"),
) -> None:
    """Bad-tag / flatline / gap detection over a JSON sample series."""
    _emit(diag.historian_health(_load_json(input), gap_s))


@diag_app.command("rca")
@cli_errors
def rca_cmd(
    input: Path = typer.Option(
        ..., "--input",
        help="JSON evidence bundle: {window, alarms?, tags?, dataflow?, state_series?}",
    ),
    lead_window_s: float = typer.Option(300.0, "--lead-window-s"),
    weights: Path = typer.Option(
        None, "--weights",
        help="JSON file: per-site {cause: weight} override (e.g. from 'diag learn-weights')",
    ),
) -> None:
    """AI downtime root-cause copilot — cited, advisory-only verdict over evidence.

    The bundle JSON carries the incident ``window`` ({start, end?, asset?, category?})
    plus any of ``alarms`` / ``tags`` / ``dataflow`` / ``state_series`` (and an
    optional inline ``cause_weights``). ``--weights`` points at a learned per-site
    ``{cause: weight}`` profile that overrides the inline one. Nothing is executed;
    the output ranks causes, cites the real signals, and proposes a human-approved,
    undoable action.
    """
    bundle = _load_json(input)
    if not isinstance(bundle, dict) or "window" not in bundle:
        raise ValueError("Bundle must be an object with at least a 'window' key.")
    cause_weights = _load_json(weights) if weights else bundle.get("cause_weights")
    _emit(rca_brain.downtime_rca(
        window=bundle.get("window"),
        alarms=bundle.get("alarms"),
        tags=bundle.get("tags"),
        dataflow=bundle.get("dataflow"),
        state_series=bundle.get("state_series"),
        lead_window_s=lead_window_s,
        cause_weights=cause_weights,
    ))


@diag_app.command("learn-weights")
@cli_errors
def learn_weights_cmd(
    input: Path = typer.Option(
        ..., "--input",
        help="JSON file: list of confirmed incidents [{cause, signals:[...]}]",
    ),
    min_samples: int = typer.Option(8, "--min-samples"),
    smoothing: float = typer.Option(1.0, "--smoothing"),
) -> None:
    """Learn a per-site {cause: weight} RCA profile from a labeled incident history.

    Reads a corpus of confirmed incidents (each ``{cause, signals}``) and derives a
    per-site cause-weight profile to feed ``diag rca --weights``. Explainable
    (smoothed signal→cause precision) with smoothing + a min-sample fall-back to
    the shipped defaults; advisory only — it tunes ranking, executes nothing.
    """
    _emit(rca_weights.learn_cause_weights(_load_json(input), min_samples, smoothing))


@diag_app.command("rca-live")
@cli_errors
def rca_live_cmd(
    endpoint: EndpointOption = None,
    start: str = typer.Option(..., "--start", help="Incident onset (ISO-8601)"),
    end: str = typer.Option(None, "--end", help="Incident end (ISO-8601)"),
    asset: str = typer.Option(None, "--asset", help="Machine/line label"),
    ref: list[str] = typer.Option(None, "--ref", help="Tag/node/address to sample (repeatable)"),
    sample_count: int = typer.Option(8, "--samples"),
    interval_ms: int = typer.Option(200, "--interval-ms"),
    no_alarms: bool = typer.Option(False, "--no-alarms", help="Skip OPC-UA alarm surfacing"),
    lead_window_s: float = typer.Option(300.0, "--lead-window-s"),
) -> None:
    """AI downtime RCA copilot that gathers its own live evidence from an endpoint.

    Pulls a diagnose_dataflow probe + a sampled series per --ref + active OPC-UA
    conditions, then runs the copilot. Read-only and advisory — nothing is executed.
    """
    window = {"start": start, "end": end, "asset": asset}
    _emit(rca_collect.downtime_rca_live(
        resolve_target(endpoint),
        window={k: v for k, v in window.items() if v is not None},
        refs=list(ref) if ref else None,
        sample_count=sample_count,
        interval_ms=interval_ms,
        include_alarms=not no_alarms,
        lead_window_s=lead_window_s,
    ))
