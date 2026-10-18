"""``iaiops sensor`` — sensor profiles and one-shot reads (HLD §16 / §17).

A profile says how a sensor's raw bytes decode. ``import-iodd`` drafts one from
the vendor's IODD — marked ``verified: 待核实``, with units left as IODD codes
and every item it could not represent listed. ``check`` validates a profile file
and shows its channels. Those two read local files only. ``read`` CONTACTS the
device: it reads one point once and reports reachable / decodable separately,
exiting 1 unless both are true.

Bind a profile in config.yaml: ``sensor_profile: <file>`` on a Modbus endpoint,
``port_profiles: {<port>: <file>}`` on an IO-Link master.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

sensor_app = typer.Typer(
    help=(
        "Sensor profiles: draft from an IODD, check (local files); "
        "read one point (contacts the device)."
    ),
    no_args_is_help=True,
)


@cli_errors
def import_iodd_cmd(
    iodd: Path = typer.Argument(..., help="The device's IODD file (.xml)."),
    out: Path = typer.Option(
        None, "--out", help="Write the draft here (.yaml); default: print it."
    ),
    process_data: str = typer.Option(
        None, "--process-data", help="ProcessData id, when the IODD declares several."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing --out file."),
) -> None:
    """Draft a profile from an IODD. The draft is 待核实 until checked against a live reading."""
    from iaiops.core.governance.evidence import validate_output_path
    from iaiops.core.runtime.sensor.iodd import MAX_IODD_BYTES, import_iodd, render_draft

    if iodd.stat().st_size > MAX_IODD_BYTES:  # before reading it into memory
        raise ValueError(f"{iodd} is larger than {MAX_IODD_BYTES // (1024 * 1024)} MB — refused.")
    draft = import_iodd(iodd.read_text("utf-8"), process_data=process_data)
    text = render_draft(draft, source_name=iodd.name)
    if out is None:
        console.print(text, markup=False, highlight=False)
        return
    path = validate_output_path(out, suffixes=(".yaml", ".yml"))
    if path.is_symlink():
        raise ValueError(f"{path} is a symbolic link — write the draft to a real file path.")
    if path.exists() and not force:
        raise ValueError(f"{path} exists. Pass --force to overwrite it.")
    path.write_text(text, "utf-8")
    console.print(f"[green]Draft written:[/] {path}  (verified: 待核实)")
    for note in draft.notes:
        console.print(f"[yellow]Not imported:[/] {note}", markup=True, highlight=False)
    console.print(
        "Next: replace each IODD unit code with the real unit, compare one live reading "
        "with the device's own display, then bind it under port_profiles in config.yaml."
    )


@cli_errors
def check_cmd(
    profile: Path = typer.Argument(..., help="A sensor profile (.yaml)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Validate a profile and show its channels. Exit 1 with the reason if it is invalid."""
    from iaiops.core.runtime.sensor import load_profile_file, profile_summary

    loaded = load_profile_file(profile)
    summary = profile_summary(loaded)
    rows = summary["channels"]
    if as_json:
        _emit(summary)
        return
    console.print(
        f"[bold]{loaded.id}[/] — {loaded.protocol}, source {loaded.source}, "
        f"verified {loaded.verified}",
        highlight=False,
    )
    # The evidence (or the warning) travels with the verdict, not only in --json.
    details = (
        ("description", loaded.description),
        ("caveat", loaded.caveat),
        ("derived from", loaded.derived_from),
        ("provenance", "; ".join(f"{k}: {v}" for k, v in loaded.provenance)),
    )
    for label, value in details:
        if value:
            console.print(f"  {label}: {value}", markup=False, highlight=False)
    for row in rows:
        console.print(
            f"  {row['channel']}: {row['layout']} → {row['unit']} ({row['signal']})",
            markup=False,
            highlight=False,
        )


@cli_errors
def read_cmd(
    endpoint: str = typer.Argument(..., help="Configured endpoint name."),
    ref: str = typer.Argument(..., help="ch:<name>, port<N>/<channel>, or a typed Modbus point."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Read one point once: reachable / decodable / value + unit + band + verification."""
    from iaiops.core.runtime.connection import ConnectionManager
    from iaiops.core.runtime.sensor import probe

    out = probe.read_channel(ConnectionManager.from_config().target(endpoint), ref)
    if as_json:
        _emit(out)
        return
    levels = out.get("levels", {})
    console.print(
        f"[bold]{endpoint}[/] {ref}: reachable={levels.get('reachable')} "
        f"decodable={levels.get('decodable')}",
        highlight=False,
    )
    if levels.get("decodable"):
        band = f" ±{out['band']}" if out.get("band") is not None else ""
        console.print(
            f"  {out.get('value')} {out.get('unit') or '(no unit)'}{band} — profile "
            f"{out.get('profile') or '(none)'}, verified {out.get('verified') or '-'}",
            markup=False,
            highlight=False,
        )
        if out.get("untyped"):
            console.print(
                "  [yellow]untyped:[/] read as uint16 — give it a type "
                "(ir:/hr:…, di:/co: for switches)."
            )
    else:
        console.print(f"  {out.get('reason', '')}", markup=False, highlight=False)
    if not (levels.get("reachable") and levels.get("decodable")):
        # Scripts and CI must be able to tell a failed probe from a good one.
        raise typer.Exit(1)


@cli_errors
def list_cmd(
    protocol: str = typer.Option(None, "--protocol", help="modbus | iolink"),
    vendor_id: int = typer.Option(None, "--vendor-id", help="IO-Link vendor id."),
    device_id: int = typer.Option(None, "--device-id", help="IO-Link device id."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List the shipped profile library. A match is a suggestion, not a binding."""
    from iaiops.core.runtime.sensor import library

    entries = library.list_profiles(protocol=protocol, vendor_id=vendor_id, device_id=device_id)
    if as_json:
        _emit({"profiles": entries})
        return
    for entry in entries:
        if entry.get("caveat"):
            entry = {**entry, "description": f"{entry['description']} — {entry['caveat']}"}
        console.print(
            f"{entry['id']}  [{entry['category']}, {entry['protocol']}, "
            f"verified {entry['verified']}] {entry['description']}",
            markup=False,
            highlight=False,
        )
    if not entries:
        console.print("No library profile matches.")


@cli_errors
def show_cmd(
    profile_id: str = typer.Argument(..., help="Library profile id (see `iaiops sensor list`)."),
    out: Path = typer.Option(None, "--out", help="Copy it to this file (.yaml) to edit and bind."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing --out file."),
) -> None:
    """Show a library profile, or copy it to a file you then check and bind yourself."""
    from iaiops.core.governance.evidence import validate_output_path
    from iaiops.core.runtime.sensor import library

    try:
        path, _profile = library.get(profile_id)
    except library.ProfileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    text = path.read_text("utf-8")
    if out is None:
        # Raw bytes, not the rich console: it wraps at the terminal width and a
        # wrapped comment line breaks the YAML for `show <id> > file.yaml`.
        typer.echo(text, nl=False)
        return
    target = validate_output_path(out, suffixes=(".yaml", ".yml"))
    if target.is_symlink():
        raise ValueError(f"{target} is a symbolic link — write to a real file path.")
    if target.exists() and not force:
        raise ValueError(f"{target} exists. Pass --force to overwrite it.")
    target.write_text(text, "utf-8")
    console.print(
        f"[green]Copied[/] {profile_id} → {target}  (verified: {_profile.verified}). "
        "Check one reading against the device's display, then bind it in config.yaml."
    )


sensor_app.command("import-iodd")(import_iodd_cmd)
sensor_app.command("check")(check_cmd)
sensor_app.command("read")(read_cmd)
sensor_app.command("list")(list_cmd)
sensor_app.command("show")(show_cmd)
