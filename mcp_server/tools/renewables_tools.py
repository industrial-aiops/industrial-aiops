"""Renewables (solar/wind) MCP tools (READ-ONLY) — edition module.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``renewables`` edition is selected, not on a bare protocol and not in the
always-on brain. Pure analysis over injected string/inverter readings. Advisory.
"""

from typing import Any

from iaiops.core.brain import pv
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pv_performance(strings: list[dict[str, Any]], underperf_pct: float = 90.0) -> dict:
    """[READ][risk=low] Flag underperforming PV strings vs expected (or fleet-median) output.

    Which strings / inverters are underperforming, and by how much? A string that
    lags its peers (or its irradiance-expected output) is the signature of soiling,
    shading, a blown fuse, or a failed module. Computes each string's performance
    ratio against its expected output — ``expected_w`` if given, else nameplate ×
    irradiance/1000, else the fleet median — and flags laggards below the threshold.
    Worst-first, each ratio cited by its inputs. Pure analysis over readings you
    pass in (inverter/combiner Modbus or plant SCADA); read-only, advisory.

    Args:
        strings: [{string, power_w, irradiance_w_m2?, capacity_w?, expected_w?}].
        underperf_pct: Ratio (% of expected) below which a string is flagged (default 90).

    Returns dict: {strings_evaluated, underperf_pct, fleetMedianPowerW, summary,
        underperformer_count, underperformers:[{string, power_w, expectedW, method,
        ratioPct, status ('ok'|'underperforming'|'offline'), detail}], worst, note}.

    Example: pv_performance(strings=[{"string":"INV1.S3","power_w":4200,
        "capacity_w":6000,"irradiance_w_m2":850}]).
    """
    return pv.pv_performance(strings, underperf_pct=underperf_pct)
