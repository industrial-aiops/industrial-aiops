"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from iaiops.cli.analytics import analytics_app
from iaiops.cli.audit import audit_app
from iaiops.cli.bacnet import bacnet_app
from iaiops.cli.compliance import compliance_cmd, historian_app
from iaiops.cli.diagnostics import diag_app
from iaiops.cli.doctor import doctor_cmd
from iaiops.cli.eip import eip_app
from iaiops.cli.ethercat import ethercat_app
from iaiops.cli.hart import hart_app
from iaiops.cli.init import init_cmd
from iaiops.cli.mc import mc_app
from iaiops.cli.modbus import modbus_app
from iaiops.cli.mqtt import mqtt_app
from iaiops.cli.mtconnect import mtconnect_app
from iaiops.cli.opcua import opcua_app
from iaiops.cli.profinet import profinet_app
from iaiops.cli.s7 import s7_app
from iaiops.cli.secret import secret_app

app = typer.Typer(
    name="iaiops",
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
app.add_typer(profinet_app, name="profinet")
app.add_typer(bacnet_app, name="bacnet")
app.add_typer(hart_app, name="hart")
app.add_typer(diag_app, name="diag")
app.add_typer(analytics_app, name="analytics")
app.add_typer(secret_app, name="secret")
app.add_typer(audit_app, name="audit")
app.add_typer(historian_app, name="historian")
app.command("init")(init_cmd)
app.command("doctor")(doctor_cmd)
app.command("compliance")(compliance_cmd)


@app.command("protocols")
def protocols_cmd() -> None:
    """Print the protocol/capability map (what iaiops supports)."""
    import json

    from rich.console import Console

    from iaiops.core.brain.overview import protocols_supported

    Console().print_json(json.dumps(protocols_supported(), default=str))


@app.command("mcp")
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport)."""
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: iaiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force iaiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
