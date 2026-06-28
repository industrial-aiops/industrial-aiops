"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from ot_aiops.cli.analytics import analytics_app
from ot_aiops.cli.diagnostics import diag_app
from ot_aiops.cli.doctor import doctor_cmd
from ot_aiops.cli.eip import eip_app
from ot_aiops.cli.ethercat import ethercat_app
from ot_aiops.cli.init import init_cmd
from ot_aiops.cli.mc import mc_app
from ot_aiops.cli.modbus import modbus_app
from ot_aiops.cli.mqtt import mqtt_app
from ot_aiops.cli.mtconnect import mtconnect_app
from ot_aiops.cli.opcua import opcua_app
from ot_aiops.cli.s7 import s7_app
from ot_aiops.cli.secret import secret_app

app = typer.Typer(
    name="ot-aiops",
    help="Governed, vendor-neutral OT data tap + intelligent troubleshooting for "
    "AI agents (OPC-UA / Modbus / S7comm / Mitsubishi MC / MTConnect / "
    "MQTT-Sparkplug / EtherNet-IP / EtherCAT) + OEE/asset analytics. Read-first; "
    "writes are MOC-gated.",
    no_args_is_help=True,
)

app.add_typer(opcua_app, name="opcua")
app.add_typer(modbus_app, name="modbus")
app.add_typer(s7_app, name="s7")
app.add_typer(mc_app, name="mc")
app.add_typer(mtconnect_app, name="mtconnect")
app.add_typer(mqtt_app, name="mqtt")
app.add_typer(eip_app, name="eip")
app.add_typer(ethercat_app, name="ethercat")
app.add_typer(diag_app, name="diag")
app.add_typer(analytics_app, name="analytics")
app.add_typer(secret_app, name="secret")
app.command("init")(init_cmd)
app.command("doctor")(doctor_cmd)


@app.command("protocols")
def protocols_cmd() -> None:
    """Print the protocol/capability map (what ot-aiops supports)."""
    import json

    from rich.console import Console

    from ot_aiops.ops.overview import protocols_supported

    Console().print_json(json.dumps(protocols_supported(), default=str))


@app.command("mcp")
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport)."""
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: ot-aiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force ot-aiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
