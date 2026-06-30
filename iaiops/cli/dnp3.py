"""``iaiops dnp3 ...`` sub-commands (DNP3, read-only outstation telemetry).

pydnp3 optional extra: ``pip install iaiops[dnp3]``. Monitor direction only — no
control. Preview: not verified against a live outstation.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.dnp3 import ops

dnp3_app = typer.Typer(help="DNP3 read-only outstation telemetry (pydnp3).",
                       no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@dnp3_app.command("status")
@cli_errors
def status_cmd(endpoint: EndpointOption = None) -> None:
    """Bring the master online and show link/outstation status."""
    _emit(ops.dnp3_link_status(resolve_target(endpoint)))


@dnp3_app.command("poll")
@cli_errors
def poll_cmd(endpoint: EndpointOption = None) -> None:
    """Class 0/1/2/3 integrity poll → the outstation's measurement database."""
    _emit(ops.dnp3_integrity_poll(resolve_target(endpoint)))
