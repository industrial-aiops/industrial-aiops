"""``iaiops profinet ...`` sub-commands (PROFINET-DCP discovery, read-only).

DCP IdentifyAll / Identify / Get over layer-2 via pnio-dcp (optional extra:
``pip install iaiops[profinet]``). Needs raw-socket access (root/admin/CAP_NET_RAW)
on the NIC on the PROFINET subnet; ``host`` is THIS machine's IP on that subnet.
Discovery + identify ONLY — no RT cyclic data, no DCP Set (set-name/ip/blink).
"""

from __future__ import annotations

import typer

from iaiops.cli._common import EndpointOption, _emit, cli_errors, resolve_target
from iaiops.connectors.profinet import ops

profinet_app = typer.Typer(
    help="PROFINET-DCP read-only discovery/identify (pnio-dcp; raw-socket/L2).",
    no_args_is_help=True,
)


@profinet_app.command("discover")
@cli_errors
def discover_cmd(endpoint: EndpointOption = None) -> None:
    """DCP IdentifyAll: list every PROFINET station on the local segment."""
    _emit(ops.profinet_discover(resolve_target(endpoint)))


@profinet_app.command("identify")
@cli_errors
def identify_cmd(name_of_station: str, endpoint: EndpointOption = None) -> None:
    """Identify one station by its PROFINET name-of-station."""
    _emit(ops.profinet_identify_station(resolve_target(endpoint), name_of_station))


@profinet_app.command("params")
@cli_errors
def params_cmd(mac: str, endpoint: EndpointOption = None) -> None:
    """Targeted DCP Get for one station (by MAC): name + IP suite."""
    _emit(ops.profinet_station_params(resolve_target(endpoint), mac))


@profinet_app.command("assets")
@cli_errors
def assets_cmd(endpoint: EndpointOption = None) -> None:
    """Build a PROFINET asset register from a DCP IdentifyAll sweep."""
    _emit(ops.profinet_asset_inventory(resolve_target(endpoint)))
