"""``iaiops oee measure`` — the measured figure, next to the hand-kept one.

Reads what ``iaiops collect run`` put in the local store, asks the line's
``run_state`` tag what running means, and reports availability over the time it
could actually see. Contacts no device: the measurement is over collected
history, so it can be re-run and argued with.

The comparison against a site's own number is the point, which is exactly why it
must not be able to manufacture a favourable answer — a measurement above the
reported figure is printed as plainly as one below, and a refused measurement
produces no number at all.

Pure math lives in ``core/brain/oee_measure``; this reads the store and renders,
following the ``baseline`` / ``baseline_store`` split.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console, humanize_seconds

oee_app = typer.Typer(help="OEE measured from collected history.")


@cli_errors
def oee_measure_cmd(
    endpoint: str = typer.Argument(..., help="Configured endpoint name."),
    reported: float = typer.Option(
        None, "--reported", help="The availability %% the site currently believes."
    ),
    minor_stop_s: float = typer.Option(
        300.0, "--minor-stop-s", help="Stops at or under this count as minor."
    ),
    db: Path = typer.Option(None, "--db", help="Local store (default: the iaiops store)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Measure availability from collected history; optionally compare it.

    Needs a tag declared `role: run_state` with `running_when:` — which value
    means running is process knowledge, not something to infer from the data.
    """
    from iaiops.core.brain.oee_measure import compare_to_reported, measure_availability
    from iaiops.core.runtime.config import TagRole, load_config
    from iaiops.core.sink.sqlite_local import SampleFilter, query_samples

    target = load_config().get_target(endpoint)
    run_tags = [t for t in (getattr(target, "tags", ()) or ()) if t.role == TagRole.RUN_STATE]
    if not run_tags:
        raise ValueError(
            f"Endpoint {endpoint!r} declares no run_state tag. Add `role: run_state` and "
            "`running_when:` to the tag that reports whether the line is producing — "
            "run `iaiops readiness` to see what else is missing."
        )
    tag = run_tags[0]

    rows = query_samples(SampleFilter(tag=tag.ref, limit=200_000), db_path=db)
    result = measure_availability(rows, tag, minor_stop_s=minor_stop_s)
    comparison = compare_to_reported(result, reported) if reported is not None else None

    if as_json:
        _emit({"measured": result, "comparison": comparison})
        return

    console.print(f"\n[bold]Availability[/] — {endpoint} · tag {tag.ref}\n")
    if result["status"] != "ok":
        console.print(f"[yellow]No figure reported ({result['status']}).[/]")
        console.print(f"[dim]{result['note']}[/]\n")
    else:
        pct = 100.0 * result["availability"]
        console.print(f"  [bold]{pct:.2f}%[/] over {result['coverage_pct']:g}% coverage")

    console.print(
        f"  running {humanize_seconds(result['running_s'])} · "
        f"stopped {humanize_seconds(result['stopped_s'])} · "
        f"[yellow]blind {humanize_seconds(result['unknown_s'])}[/]"
    )
    if result.get("minor_stops"):
        console.print(
            f"  [cyan]{result['minor_stops']} minor stoppage(s)[/] totalling "
            f"{humanize_seconds(result['minor_stop_s'])} — under {minor_stop_s:g}s each, "
            "the ones a manual tally cannot see"
        )
    console.print(f"\n[dim]{result['note']}[/]")

    if comparison:
        console.print(f"\n[bold]Against the reported figure[/]\n  {comparison['explanation']}")


oee_app.command("measure")(oee_measure_cmd)

__all__ = ["oee_app"]
