"""``iaiops bacnet ...`` sub-commands (BACnet/IP, read-only facility/HVAC).

BAC0 optional extra: ``pip install iaiops[bacnet]``. Read-only — discovery + reads;
no building-control writes. Preview: not verified against live BACnet gear.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

from iaiops.cli._common import EndpointOption, cli_errors, resolve_target
from iaiops.connectors.bacnet import ops

bacnet_app = typer.Typer(help="BACnet/IP read-only facility/HVAC monitoring (BAC0).",
                         no_args_is_help=True)
console = Console()


def _emit(data) -> None:
    console.print_json(json.dumps(data, default=str))


@bacnet_app.command("discover")
@cli_errors
def discover_cmd(endpoint: EndpointOption = None) -> None:
    """Who-Is broadcast: discover BACnet devices on the local network."""
    _emit(ops.bacnet_discover(resolve_target(endpoint)))


@bacnet_app.command("objects")
@cli_errors
def objects_cmd(address: str, device_id: int, endpoint: EndpointOption = None) -> None:
    """Read a device's object list (its BACnet points/objects)."""
    _emit(ops.bacnet_object_list(resolve_target(endpoint), address, device_id))


@bacnet_app.command("read")
@cli_errors
def read_cmd(
    address: str,
    object_type: str,
    instance: int,
    prop: str = typer.Option("presentValue", "--property", help="Property to read"),
    endpoint: EndpointOption = None,
) -> None:
    """Read one property of one BACnet object (default presentValue)."""
    _emit(ops.bacnet_read_property(resolve_target(endpoint), address, object_type, instance, prop))


@bacnet_app.command("points")
@cli_errors
def points_cmd(address: str, device_id: int, endpoint: EndpointOption = None) -> None:
    """Read presentValue of all monitor-relevant points of a device (HVAC snapshot)."""
    _emit(ops.bacnet_read_points(resolve_target(endpoint), address, device_id))


@bacnet_app.command("cov")
@cli_errors
def cov_cmd(
    address: str,
    object_type: str,
    instance: int,
    max_notifications: int = typer.Option(20, "--max", help="Stop after N notifications"),
    timeout_s: int = typer.Option(30, "--timeout", help="Stop after N seconds"),
    lifetime_s: int = typer.Option(300, "--lifetime", help="COV subscription lifetime"),
    endpoint: EndpointOption = None,
) -> None:
    """Bounded COV capture: collect up to --max changes or --timeout, then unsubscribe."""
    _emit(ops.bacnet_cov_subscribe(
        resolve_target(endpoint), address, object_type, instance,
        max_notifications, timeout_s, lifetime_s,
    ))


@bacnet_app.command("trend")
@cli_errors
def trend_cmd(
    address: str,
    instance: int,
    count: int = typer.Option(100, "--count", help="Max records to read"),
    newest_first: bool = typer.Option(True, "--newest-first/--oldest-first"),
    endpoint: EndpointOption = None,
) -> None:
    """Read buffered records from a device's BACnet TrendLog object (historical trend)."""
    _emit(ops.bacnet_read_trend_log(
        resolve_target(endpoint), address, instance, count, newest_first,
    ))
