"""Doctor top-level command: environment and connectivity check."""

from __future__ import annotations

from typing import Annotated

import typer

from iaiops.cli._common import cli_errors


@cli_errors
def doctor_cmd(
    skip_probe: Annotated[
        bool, typer.Option("--skip-probe", help="Skip connectivity probe (faster)")
    ] = False,
) -> None:
    """Check config and OPC-UA / Modbus endpoint reachability."""
    from iaiops.doctor import run_doctor

    raise typer.Exit(run_doctor(skip_probe=skip_probe))
