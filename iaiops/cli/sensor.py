"""``iaiops sensor`` — sensor profiles: draft one from an IODD, check one (HLD §16).

A profile says how a sensor's raw bytes decode. ``import-iodd`` drafts one from
the vendor's IODD — marked ``verified: 待核实``, with units left as IODD codes
and every item it could not represent listed. ``check`` validates a profile file
and shows its channels. Both read local files only; neither contacts a device.

Bind a profile in config.yaml: ``sensor_profile: <file>`` on a Modbus endpoint,
``port_profiles: {<port>: <file>}`` on an IO-Link master.
"""

from __future__ import annotations

from pathlib import Path

import typer

from iaiops.cli._common import _emit, cli_errors, console

sensor_app = typer.Typer(
    help="Sensor profiles — draft one from an IODD, check one. Contacts nothing.",
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
    from iaiops.core.runtime.sensor import BitLayout, load_profile_file

    loaded = load_profile_file(profile)
    rows = []
    for channel in loaded.channels:
        layout = channel.layout
        where = (
            f"bits {layout.bit_offset}+{layout.bit_length} {layout.value_type}"
            if isinstance(layout, BitLayout)
            else f"{layout.table}[{layout.address}] {layout.value_type} {layout.order}"
        )
        rows.append(
            {
                "channel": channel.name,
                "layout": where,
                "unit": channel.unit,
                "signal": channel.signal,
                "range": list(channel.range) if channel.range else None,
                "sentinels": len(channel.invalid),
                "band": channel.accuracy.band if channel.accuracy else None,
            }
        )
    summary = {
        "id": loaded.id,
        "protocol": loaded.protocol,
        "source": loaded.source,
        "verified": loaded.verified,
        "match": (
            {"vendor_id": loaded.vendor_id, "device_id": loaded.device_id}
            if loaded.vendor_id is not None
            else None
        ),
        "channels": rows,
    }
    if as_json:
        _emit(summary)
        return
    console.print(
        f"[bold]{loaded.id}[/] — {loaded.protocol}, source {loaded.source}, "
        f"verified {loaded.verified}",
        highlight=False,
    )
    for row in rows:
        console.print(
            f"  {row['channel']}: {row['layout']} → {row['unit']} ({row['signal']})",
            markup=False,
            highlight=False,
        )


sensor_app.command("import-iodd")(import_iodd_cmd)
sensor_app.command("check")(check_cmd)
