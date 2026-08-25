"""``iaiops diag ...`` — cross-protocol intelligent troubleshooting (read-only).

The flood/tag/historian analyzers consume a JSON list of events/samples; pass a
path to a JSON file (``--input events.json``) so the CLI stays scriptable.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from iaiops.cli._common import EndpointOption, _emit, cli_errors, console, resolve_target
from iaiops.core.brain import dataquality as dq
from iaiops.core.brain import diagnostics as diag
from iaiops.core.brain import rca as rca_brain
from iaiops.core.brain import rca_collect, rca_weights

diag_app = typer.Typer(
    help="Cross-protocol intelligent troubleshooting (read-only).", no_args_is_help=True
)


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


@diag_app.command("alarm-flood")
@cli_errors
def alarm_flood_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of alarm events"),
    window_s: float = typer.Option(600.0, "--window-s", help="ISA-18.2 flood window (s)"),
    threshold: int = typer.Option(10, "--threshold", help="Annunciations/window starting a flood"),
    stale_after_s: float = typer.Option(86400.0, "--stale-after-s"),
    max_episodes: int = typer.Option(20, "--max-episodes"),
    max_rows: int = typer.Option(50, "--max-rows"),
    load_bucket_s: float = typer.Option(600.0, "--load-bucket-s", help="ISA-18.2 load bucket (s)"),
) -> None:
    """ISA-18.2 deep flood report: episodes + chattering + stale + load profile + advice."""
    from iaiops.core.brain import alarm_flood as flood

    _emit(
        flood.alarm_flood_report(
            _load_json(input),
            window_s,
            threshold,
            stale_after_s=stale_after_s,
            max_episodes=max_episodes,
            max_rows=max_rows,
            load_bucket_s=load_bucket_s,
        )
    )


@diag_app.command("alarm-worksheet")
@cli_errors
def alarm_worksheet_cmd(
    input: Path = typer.Option(..., "--input", help="JSON file: list of alarm events"),
    window_s: float = typer.Option(600.0, "--window-s", help="ISA-18.2 flood window (s)"),
    threshold: int = typer.Option(10, "--threshold", help="Annunciations/window starting a flood"),
    out: Path = typer.Option(None, "--out", help="Write the worksheet as CSV to this path"),
) -> None:
    """ISA-18.2 alarm-rationalization worksheet (JSON, or CSV via --out)."""
    import csv

    from iaiops.core.brain import alarm_flood as flood

    rows = flood.rationalization_worksheet(_load_json(input), window_s, threshold)
    dicts = flood.worksheet_rows_as_dicts(rows)
    if out is not None:
        with Path(out).expanduser().open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(flood.WORKSHEET_COLUMNS))
            writer.writeheader()
            writer.writerows(dicts)
        console.print(f"Wrote {len(dicts)} worksheet rows to {out}")
        return
    _emit({"row_count": len(dicts), "columns": list(flood.WORKSHEET_COLUMNS), "rows": dicts})


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
    input: Path = typer.Option(
        ..., "--input", help="JSON file: list of {endpoint, tags:[{ref, samples}]}"
    ),
    staleness_s: float = typer.Option(300.0, "--staleness-s"),
    now: str = typer.Option(None, "--now", help="ISO-8601 staleness reference (deterministic)"),
) -> None:
    """Fleet data-trust scorecard (staleness / heartbeat / quality) across feeds."""
    _emit(dq.data_quality_scorecard(_load_json(input), staleness_s, now))


@diag_app.command("dataquality-fleet")
@cli_errors
def dataquality_fleet_cmd(
    input: Path = typer.Option(
        ..., "--input", help="JSON file: list of {endpoint, tags:[{ref, samples}]}"
    ),
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


def _confirmation_from(from_case: str, cause: str, basis: str, by: str, site: str) -> dict | None:
    """Build the one input that can grade a conclusion `confirmed` (D29).

    Two routes, and `--from-case` is the one that matters: the loop that captures
    a human's cause already exists (`iaiops case confirm`, #180/#191), and until
    now the verdict could not see it. Making the operator retype the cause here
    would be a second place for it to drift.
    """
    if from_case:
        if cause or basis:
            raise ValueError(
                "Give either --from-case (read a cause a person already confirmed) "
                "or --confirmed-cause/--confirmed-basis (a measurement or a "
                "reproduction), not both."
            )
        from iaiops.core.knowledge.case_store import list_cases

        found = [c for c in list_cases(site, base_dir=None) if c.incident_id == from_case]
        if not found:
            raise LookupError(
                f"No case {from_case!r} for site {site!r}. List them with `iaiops case list`."
            )
        case = found[0]
        if not case.label:
            raise ValueError(
                f"Case {from_case!r} has no confirmed cause yet. Answer it first: "
                f"`iaiops case confirm {from_case} --cause <cause> --by <you>`."
            )
        return {"cause": case.label, "basis": "human", "by": by or "case"}
    if cause or basis:
        # Deliberately not defaulted. Which of the three bases applies is the whole
        # content of the claim — a default would let 'somebody eyeballed it' be
        # recorded as a measurement.
        if not (cause and basis):
            raise ValueError(
                "--confirmed-cause and --confirmed-basis go together. "
                "basis is one of: measurement, reproduction, human."
            )
        return {"cause": cause, "basis": basis, "by": by}
    return None


@diag_app.command("rca")
@cli_errors
def rca_cmd(
    input: Path = typer.Option(
        ...,
        "--input",
        help="JSON evidence bundle: {window, alarms?, tags?, dataflow?, state_series?}",
    ),
    lead_window_s: float = typer.Option(300.0, "--lead-window-s"),
    weights: Path = typer.Option(
        None,
        "--weights",
        help="JSON file: per-site {cause: weight} override (e.g. from 'diag learn-weights')",
    ),
    from_case: str = typer.Option(
        "", "--from-case", help="Incident id whose confirmed cause a person already recorded."
    ),
    confirmed_cause: str = typer.Option("", "--confirmed-cause"),
    confirmed_basis: str = typer.Option(
        "", "--confirmed-basis", help="measurement | reproduction | human."
    ),
    confirmed_by: str = typer.Option("", "--confirmed-by"),
    site: str = typer.Option("default", "--site", help="Site whose cases --from-case reads."),
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
    _emit(
        rca_brain.downtime_rca(
            window=bundle.get("window"),
            alarms=bundle.get("alarms"),
            tags=bundle.get("tags"),
            dataflow=bundle.get("dataflow"),
            state_series=bundle.get("state_series"),
            lead_window_s=lead_window_s,
            cause_weights=cause_weights,
            confirmation=_confirmation_from(
                from_case, confirmed_cause, confirmed_basis, confirmed_by, site
            ),
        )
    )


@diag_app.command("learn-weights")
@cli_errors
def learn_weights_cmd(
    input: Path = typer.Option(
        None,
        "--input",
        help="JSON file: list of confirmed incidents [{cause, signals:[...]}]",
    ),
    site: str = typer.Option(
        None, "--site", help="Learn from this site's own confirmed cases instead of a file."
    ),
    include_anchored: bool = typer.Option(
        True,
        "--include-anchored/--independent-only",
        help="--independent-only trains on labels this tool did not suggest.",
    ),
    min_samples: int = typer.Option(8, "--min-samples"),
    smoothing: float = typer.Option(1.0, "--smoothing"),
) -> None:
    """Learn a per-site {cause: weight} RCA profile from a labeled incident history.

    Derives a per-site cause-weight profile to feed ``diag rca --weights``.
    Explainable (smoothed signal→cause precision) with smoothing + a min-sample
    fall-back to the shipped defaults; advisory only — it tunes ranking, executes
    nothing.

    ``--site`` reads the cases confirmed through ``iaiops case confirm``. Without
    it this command could only be fed a hand-written JSON file — so the corpus the
    product spends years accumulating had no way to reach the learner, and the
    "loop" was open at both ends.

    ``--independent-only`` excludes labels chosen from a list this tool ranked. A
    site whose weights change a lot between the two views is being led by its own
    suggestions, and that is worth seeing before trusting the profile.
    """
    from iaiops.core.knowledge.case_store import list_cases
    from iaiops.core.knowledge.cases import to_corpus

    if bool(input) == bool(site):
        raise ValueError(
            "Give exactly one of --input (a JSON corpus) or --site (this site's own "
            "confirmed cases). Learning from two different histories at once would "
            "produce a profile neither of them supports."
        )
    if site:
        cases = list_cases(site, pending_only=False, base_dir=None)
        corpus = to_corpus(cases, include_anchored=include_anchored)
        if not corpus:
            raise ValueError(
                f"Site {site!r} has no confirmed cases to learn from"
                + (" that were not anchored." if not include_anchored else ".")
                + " Open cases with `iaiops case open <endpoint>` and answer them "
                "with `iaiops case confirm`."
            )
    else:
        corpus = _load_json(input)
    _emit(rca_weights.learn_cause_weights(corpus, min_samples, smoothing))


@diag_app.command("corpus")
@cli_errors
def corpus_cmd(
    input: Path = typer.Option(
        ...,
        "--input",
        help="CMMS/work-order export: .csv (one row per closed order) or .json (list of dicts)",
    ),
    synonyms: Path = typer.Option(
        None,
        "--synonyms",
        help="JSON file: extra site vocabulary {term: taxonomy_cause}",
    ),
    learn: bool = typer.Option(True, "--learn/--no-learn"),
    min_samples: int = typer.Option(8, "--min-samples"),
    smoothing: float = typer.Option(1.0, "--smoothing"),
) -> None:
    """Build the RCA incident corpus (and weights) from a maintenance-log export.

    Normalizes closed work orders into the ``[{cause, signals}]`` history that
    ``diag learn-weights`` consumes — explicit taxonomy causes win, then the
    built-in EN/中文 synonym table (extendable via ``--synonyms``), then
    unambiguous keyword inference; unmappable rows are reported, never guessed.
    With ``--learn`` (default) the learned ``cause_weights`` are included, ready
    for ``diag rca --weights``.
    """
    from iaiops.core.brain import maintenance_log

    if input.suffix.lower() == ".csv":
        import csv

        with Path(input).open(encoding="utf-8-sig", newline="") as fh:
            rows: list = list(csv.DictReader(fh))
    else:
        rows = _load_json(input)
    extra = _load_json(synonyms) if synonyms else None
    _emit(maintenance_log.corpus_from_maintenance_log(rows, extra, learn, min_samples, smoothing))


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
    _emit(
        rca_collect.downtime_rca_live(
            resolve_target(endpoint),
            window={k: v for k, v in window.items() if v is not None},
            refs=list(ref) if ref else None,
            sample_count=sample_count,
            interval_ms=interval_ms,
            include_alarms=not no_alarms,
            lead_window_s=lead_window_s,
        )
    )
