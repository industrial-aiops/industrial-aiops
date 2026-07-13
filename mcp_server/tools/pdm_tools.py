"""Predictive-maintenance MCP tool (always-on brain) — trend + time-to-threshold forecast.

The predictive step above baseline (which flags an already-happened violation): from a value's
recent history, estimate the trend and, if it continues, the time to cross a warn/alarm limit — the
early warning for preventive maintenance (inverter/turbine degradation, bearing drift, clogging, …).
Robust Theil–Sen slope, refuses thin history, cited. Read-only, pure over the provided series.
"""

from typing import Any, Optional

from iaiops.core.brain import pdm
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pdm_forecast(
    series: list[dict[str, Any]],
    warn_high: Optional[float] = None,
    alarm_high: Optional[float] = None,
    warn_low: Optional[float] = None,
    alarm_low: Optional[float] = None,
    imminent_within_s: float = 86400.0,
) -> dict:
    """[READ][risk=low] Forecast a value's trend + time until it crosses a warn/alarm limit.

    The predictive step above baseline_check (which flags a violation that already happened): fits a
    robust Theil-Sen trend to the recent history and, if it continues, estimates the ETA to the
    nearest limit in the direction of travel — the early warning that makes maintenance predictive
    (inverter/turbine degradation, bearing drift, filter clogging). Refuses thin history; read-only,
    pure over the provided series; no device I/O.

    Args:
        series: Time-ordered samples: [{value, timestamp?}] (timestamp ISO-8601; if all present the
            ETA is in seconds, otherwise in samples). >= 30 numeric samples required.
        warn_high/alarm_high/warn_low/alarm_low: Optional limits; the forecast targets the nearest
            one in the trend's direction (rising → highs, falling → lows).
        imminent_within_s: ETA (seconds) at/under which status is 'imminent' (default 86400 = 24h).

    Returns dict: {status (insufficient_data|stable|degrading|imminent), samples, direction,
        slope_per_unit, unit (s|samples), current, limit:{name,value}, eta_to_limit}.

    Example: pdm_forecast(series=[{"value": 62.1, "timestamp": "2026-07-12T00:00:00Z"}, ...],
        warn_high=75, alarm_high=85).
    """
    return pdm.pdm_forecast(
        list(series or []),
        warn_high=warn_high,
        alarm_high=alarm_high,
        warn_low=warn_low,
        alarm_low=alarm_low,
        imminent_within_s=imminent_within_s,
    )
