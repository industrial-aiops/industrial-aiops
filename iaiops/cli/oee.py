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

from iaiops.cli._common import (
    MAX_STORE_SAMPLES,
    _emit,
    cli_errors,
    console,
    humanize_seconds,
    run_state_samples,
)

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
    report: Path = typer.Option(None, "--report", help="Also write a self-contained HTML report."),
    lang: str = typer.Option("en", "--lang", help="Report language: en | zh."),
    site: str = typer.Option("", "--site", help="Site / plant name for the report heading."),
    note: str = typer.Option(
        "", "--note", help="A caveat rendered near the top of the report, before the figure."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Measure availability from collected history; optionally compare it.

    Needs a tag declared `role: run_state` with `running_when:` — which value
    means running is process knowledge, not something to infer from the data.
    """
    from iaiops.core.brain.oee_losses import losses_from_measured
    from iaiops.core.brain.oee_measure import compare_to_reported, measure_availability
    from iaiops.core.brain.oee_production import (
        count_production,
        performance_factor,
        quality_factor,
    )
    from iaiops.core.runtime.config import TagRole, load_config
    from iaiops.core.sink.sqlite_local import SampleFilter, query_samples

    target = load_config().get_target(endpoint)
    tag, rows = run_state_samples(endpoint, db)
    result = measure_availability(rows, tag, minor_stop_s=minor_stop_s)
    comparison = compare_to_reported(result, reported) if reported is not None else None

    # The other two factors, each reported only when its inputs were DECLARED.
    # A partial OEE that says which parts are missing beats a whole one with a
    # guess inside it.
    def _count_for(role: str):
        found = [t for t in (getattr(target, "tags", ()) or ()) if t.role == role]
        if not found:
            return None
        counted = count_production(
            query_samples(SampleFilter(tag=found[0].ref, limit=MAX_STORE_SAMPLES), db_path=db)
        )
        return counted if counted["status"] == "ok" else None

    totals = _count_for(TagRole.TOTAL_COUNT)
    goods = _count_for(TagRole.GOOD_COUNT)
    produced = totals["produced"] if totals else 0.0
    perf = performance_factor(
        produced=produced,
        ideal_cycle_time_s=getattr(target, "ideal_cycle_time_s", None),
        run_time_s=result.get("running_s", 0.0),
    )
    qual = quality_factor(total=produced, good=goods["produced"] if goods else None)

    factors = {
        "availability": result.get("availability"),
        "performance": perf["performance"],
        "quality": qual["quality"],
    }
    known = [v for v in factors.values() if v is not None]
    oee = round(known[0] * known[1] * known[2], 4) if len(known) == 3 else None

    losses = losses_from_measured(
        result, totals, goods, getattr(target, "ideal_cycle_time_s", None)
    )

    payload = {
        "measured": result,
        "comparison": comparison,
        "production": totals,
        "performance": perf,
        "quality": qual,
        "factors": factors,
        "oee": oee,
        "losses": losses,
    }

    if report is not None:
        # Same guard the scan report uses: refuse `..` traversal and a wrong
        # extension before writing anything.
        from datetime import UTC, datetime

        from iaiops.core.brain.oee_report import render_oee_report
        from iaiops.core.governance.evidence import validate_output_path

        path = validate_output_path(report, suffixes=(".html", ".htm"))
        path.write_text(
            render_oee_report(
                payload,
                endpoint=endpoint,
                site=site,
                lang=lang,
                note=note,
                generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            ),
            encoding="utf-8",
        )
        console.print(f"[dim]report written to {path}[/]")

    if as_json:
        _emit(payload)
        return

    console.print(f"\n[bold]Availability[/] — {endpoint} · tag {tag.ref}\n")
    if result["status"] != "ok":
        console.print(f"[yellow]No figure reported ({result['status']}).[/]")
        if result.get("observed_values") is not None:
            # The two values side by side, because the fix is to change one of
            # them and nobody goes and queries the store to find the other.
            declared = ", ".join(result.get("running_when") or []) or "(none declared)"
            console.print(f"  declared running_when : [bold]{declared}[/]")
            console.print(
                f"  values actually seen  : [bold]{', '.join(result['observed_values'])}[/]"
            )
    else:
        pct = 100.0 * result["availability"]
        console.print(f"  [bold]{pct:.2f}%[/] over {result['coverage_pct']:g}% coverage")

    # Only when there is something to show: after a refusal every bucket is zero,
    # and "running 0ms · stopped 0ms · blind 0ms" reads like a measured result.
    if any(result[k] for k in ("running_s", "stopped_s", "unknown_s")):
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

    if totals:
        console.print(
            f"\n[bold]Production[/] — {totals['produced']:,.0f} parts"
            + (
                f" · [yellow]{totals['discontinuities']} counter discontinuity(ies)[/]"
                if totals["discontinuities"]
                else ""
            )
        )
        if totals["discontinuities"]:
            console.print(f"  [dim]{totals['note']}[/]")

    console.print("\n[bold]OEE factors[/]")
    for name, value, note in (
        ("Availability", factors["availability"], result.get("note", "")),
        ("Performance", factors["performance"], perf["note"]),
        ("Quality", factors["quality"], qual["note"]),
    ):
        if value is None:
            console.print(f"  {name:13} [dim]not reported[/] — {note}")
        else:
            console.print(f"  {name:13} [bold]{value:.1%}[/]")
    if perf.get("warning"):
        console.print(f"  [yellow]{perf['warning']}[/]")

    if oee is not None:
        console.print(f"\n  [bold]OEE {oee:.1%}[/]  (A x P x Q)")
    else:
        missing = [n for n, v in factors.items() if v is None]
        console.print(
            f"\n  [dim]No single OEE figure: {', '.join(missing)} not measurable here. "
            "Reporting the factors that ARE measured beats multiplying in a guess.[/]"
        )

    _print_losses(losses)

    if comparison:
        console.print(f"\n[bold]Against the reported figure[/]\n  {comparison['explanation']}")


def _print_losses(losses: dict) -> None:
    """Where the OEE gap went, or which declaration would let us say."""
    console.print("\n[bold]Six Big Losses[/]")
    if losses["status"] != "ok":
        console.print(f"  [dim]{losses['note']}[/]")
        return
    for entry in losses["ranked"]:
        if entry["time_s"] <= 0:
            continue
        console.print(
            f"  {entry['loss']:19} {humanize_seconds(entry['time_s']):>7}"
            f"  {entry['pct_of_planned']:6.1%} of observed time"
            + ("" if entry["classified"] else "  [dim](unclassified — not supplied)[/]")
        )
    biggest = losses.get("largest_loss")
    if biggest and biggest["time_s"] > 0:
        console.print(f"\n  [bold]Largest: {biggest['loss']}[/] — the one worth attacking first")
    if losses.get("optimistic_cycle"):
        console.print(
            "  [yellow]The declared ideal cycle is faster than the line ever ran, so the "
            "speed loss below is an artefact of the declaration, not of the line.[/]"
        )
    console.print(f"  [dim]{losses['note']}[/]")


oee_app.command("measure")(oee_measure_cmd)

__all__ = ["oee_app"]
