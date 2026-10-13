"""``iaiops meter`` — a supplier's half-hourly electricity file, read and explained.

``check`` says what the file contains before anything is concluded from it;
``profile`` reports base load, out-of-hours use, peaks and — given the site's
tariff — where the money goes by time of day, optionally as a self-contained HTML
report to forward. Contacts no device: the input is a file.

Pure analysis lives in ``core/brain/meter_analysis``; this reads files and renders.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

meter_app = typer.Typer(help="Half-hourly (HH) electricity data: check a file, profile a site.")

#: The importer enforces its own cap on the text; this stops a huge file being
#: read into memory at all.
_MAX_FILE_BYTES = 50 * 1024 * 1024
_MAX_TARIFF_BYTES = 256 * 1024


def _read_text(path: Path, cap: int) -> str:
    size = path.stat().st_size
    if size > cap:
        raise ValueError(
            f"{path} is {size // (1024 * 1024)} MiB; cap is {cap // (1024 * 1024)} MiB"
        )
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel on a UK Windows PC saves CSV as cp1252 (the £ sign gives it away).
        return raw.decode("cp1252", errors="replace")


def _load_tariff(path: Path | None) -> dict | None:
    if path is None:
        return None
    import yaml

    try:
        spec = yaml.safe_load(_read_text(path, _MAX_TARIFF_BYTES))
    except yaml.YAMLError as exc:
        raise ValueError(f"tariff file {path} is not valid YAML: {exc}") from exc
    if not isinstance(spec, dict):
        raise ValueError(f"tariff file {path} must be a mapping with a 'unit_rates' list")
    return spec


@cli_errors
def meter_check_cmd(
    file: Path = typer.Argument(..., help="Supplier half-hourly CSV (wide or long layout)."),
    unit: str = typer.Option("auto", "--unit", help="auto | kwh | wh | kw (kW = HH average)."),
    marks: str = typer.Option(
        "start", "--timestamp-marks", help="Long layout: a time labels the start or end of its HH."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show what the file contains: layout, meters, span, rejected rows, assumptions."""
    from iaiops.core.brain.meter_analysis import parse_summary

    out = parse_summary(_read_text(file, _MAX_FILE_BYTES), unit=unit, timestamp_marks=marks)
    if as_json:
        _emit(out)
        return
    console.print(f"[bold]{file.name}[/] — {out['layout']} layout, unit {out['unit']}")
    for m in out["meters"]:
        console.print(
            f"  {m['meter']}: {m['intervals']} half hours, {m['first_local']} → {m['last_local']}"
        )
    interesting = {
        k: v for k, v in out["counts"].items() if v and k not in ("intervals", "rows_read")
    }
    if interesting:
        console.print("  [yellow]" + ", ".join(f"{k}={v}" for k, v in interesting.items()) + "[/]")
    for line in out["assumptions"]:
        console.print(f"  [dim]assumed: {line}[/]")
    for line in out["warnings"]:
        console.print(f"  [yellow]{line}[/]")


def _print_profile(name: str, entry: dict) -> None:
    p, cost = entry["profile"], entry["cost"]
    cons, cov = p["consumption"], p["coverage"]
    console.print(
        f"\n[bold]Meter {name}[/]  "
        f"{p['window']['start_local'][:16]} → {p['window']['end_local'][:16]}"
    )
    console.print(
        f"  Measured {cons['measured_kwh']:,.0f} kWh · coverage {cov['coverage_pct']:.1f}%"
    )
    base = p["base_load"]["kw"]
    console.print(
        f"  Peak {p['peak']['kw']:,.1f} kW · base load {'—' if base is None else f'{base:,.1f} kW'}"
    )
    share = p["out_of_hours"]["share_pct"]
    console.print(
        f"  Out-of-hours {p['out_of_hours']['kwh']:,.0f} kWh "
        f"({'—' if share is None else f'{share:.0f}%'})"
    )
    if cost:
        console.print(
            f"  Cost £{cost['total_gbp']:,.2f} (excl. VAT/levies; measured half hours only)"
        )
    for line in p["warnings"]:
        console.print(f"  [yellow]! {line}[/]")
    for line in p["findings"]:
        console.print(f"  • {line}")


@cli_errors
def meter_profile_cmd(
    file: Path = typer.Argument(..., help="Supplier half-hourly CSV (wide or long layout)."),
    meter: str = typer.Option("", "--meter", help="Only this MPAN / meter (default: all)."),
    hours: str = typer.Option(
        "mon-fri 08:00-18:00",
        "--hours",
        help="Operating hours, e.g. 'mon-fri 08:00-18:00; sat 09:00-13:00'.",
    ),
    holiday: list[str] = typer.Option(
        [], "--holiday", help="A closed day (YYYY-MM-DD); repeatable."
    ),
    since: str = typer.Option(None, "--since", help="Window start (ISO-8601; naive = UK local)."),
    until: str = typer.Option(None, "--until", help="Window end (ISO-8601). Use with --since."),
    tariff: Path = typer.Option(
        None, "--tariff", help="Tariff YAML (unit_rates + standing charge)."
    ),
    unit: str = typer.Option("auto", "--unit", help="auto | kwh | wh | kw."),
    marks: str = typer.Option("start", "--timestamp-marks", help="Long layout: start | end."),
    report: Path = typer.Option(None, "--report", help="Also write a self-contained HTML report."),
    site: str = typer.Option("", "--site", help="Site name for the report heading."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Base load, out-of-hours use, peaks and (with --tariff) cost by time band."""
    from iaiops.core.brain.meter_analysis import analyse_hh

    text = _read_text(file, _MAX_FILE_BYTES)
    out = analyse_hh(
        text, meter=meter, operating_hours=hours, holidays=holiday, since=since, until=until,
        tariff=_load_tariff(tariff), unit=unit, timestamp_marks=marks,
    )  # fmt: skip
    if report is not None:
        if len(out["profiles"]) != 1:
            raise ValueError(
                f"the file has {len(out['profiles'])} meters; a report covers one — pass --meter"
            )
        from iaiops.core.brain.meter_report import render_meter_report
        from iaiops.core.governance.evidence import validate_output_path

        path = validate_output_path(report, suffixes=(".html", ".htm"))
        (entry,) = out["profiles"].values()
        path.write_text(
            render_meter_report(
                entry["profile"], entry["cost"], site=site, source=file.name,
                generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                assumptions=out["parse"]["assumptions"],
            ),
            encoding="utf-8",
        )  # fmt: skip
        if not as_json:
            console.print(f"[dim]report written to {path}[/]")
    if as_json:
        _emit(out)
        return
    for name, entry in out["profiles"].items():
        _print_profile(name, entry)


meter_app.command("check")(meter_check_cmd)
meter_app.command("profile")(meter_profile_cmd)
