"""MTConnect MCP tools — royalty-free CNC machine-tool telemetry (read-only).

All MTConnect tools are READ-ONLY by the standard's specification; every tool is
governed at risk_level='low'.
"""

from typing import Optional

from iaiops.connectors.mtconnect import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_probe(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] The device model: devices → components → data items.

    The MTConnect 'schema' — what the machine can report. Call this first to
    discover dataItem ids/types before reading values.

    Args:
        endpoint: Endpoint name from config (protocol must be 'mtconnect').

    Returns dict: {endpoint, device_count, devices:[{name, uuid, component_count,
        components:[{component, id, name, data_items:[{id, type, category, name, units}]}]}]}.

    Example: mtconnect_probe(endpoint="vmc1").
    """
    return ops.mtconnect_probe(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_current(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Latest value of every data item (a snapshot of the machine now).

    Args:
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, observation_count, next_sequence,
        observations:[{data_item_id, type, name, timestamp, sequence, value}]}.
        Pass next_sequence as from_sequence to mtconnect_sample to stream from 'now'.

    Example: mtconnect_current(endpoint="vmc1").
    """
    return ops.mtconnect_current(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_sample(
    endpoint: Optional[str] = None,
    count: int = 100,
    from_sequence: Optional[int] = None,
    interval_ms: int = 1000,
    max_samples: int = 0,
    duration_s: float = 0.0,
) -> dict:
    """[READ][risk=low] Recent observations — a bounded snapshot OR a bounded
    incremental long-poll stream. Both modes are read-only and can NEVER run
    unbounded.

    Modes:
      - snapshot (default): one /sample page of up to `count` observations. Pass
        `from_sequence` for a single incremental page starting at that sequence.
      - stream: set `max_samples` and/or `duration_s` to poll the agent
        repeatedly, advancing by the header's nextSequence each round, until a
        bound is hit. Feed the returned `next_sequence` back as `from_sequence`
        to resume exactly where you stopped.

    Args:
        endpoint: Endpoint name from config.
        count: Max observations per /sample page (1..500, capped server-side).
        from_sequence: Start sequence for an incremental pull (use next_sequence
            from mtconnect_current or a prior call). None = the most recent `count`.
        interval_ms: Poll spacing between rounds in stream mode (0..10000; 0 =
            back-to-back). Client-side spacing — NOT the agent's server-push interval.
        max_samples: Total observation budget across rounds; >0 selects stream mode
            (capped at 2000). 0 = snapshot.
        duration_s: Wall-clock budget in seconds; >0 selects stream mode (capped 120).

    Returns dict (snapshot): {endpoint, mode:'snapshot', requested_count,
        from_sequence, next_sequence, first_sequence, last_sequence,
        observation_count, observations:[{data_item_id, type, name, timestamp,
        sequence, value}]}.
    Returns dict (stream): {endpoint, mode:'stream', from_sequence, next_sequence,
        observation_count, poll_count, stopped_reason, interval_ms, max_samples,
        observations:[...]}.

    Example (snapshot): mtconnect_sample(endpoint="vmc1", count=200).
    Example (stream):   mtconnect_sample(endpoint="vmc1", from_sequence=1500,
        interval_ms=1000, max_samples=500, duration_s=30).
    """
    target = _target(endpoint)
    if max_samples or duration_s:
        return ops.mtconnect_stream(
            target,
            from_sequence=from_sequence,
            interval_ms=interval_ms,
            count=count,
            max_samples=max_samples or ops.MAX_STREAM_SAMPLES,
            duration_s=duration_s or ops.DEFAULT_STREAM_DURATION_S,
        )
    return ops.mtconnect_sample(target, count, from_sequence)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_assets(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Assets the agent knows (cutting tools, fixtures, programs).

    Args:
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, asset_count, assets:[{asset_type, asset_id, timestamp}]}.

    Example: mtconnect_assets(endpoint="vmc1").
    """
    return ops.mtconnect_assets(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mtconnect_oee_snapshot(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Availability / Execution / mode / program (OEE inputs).

    Surfaces the live data items an availability/performance calc needs. Does NOT
    compute a single OEE % (needs planned-time + ideal-cycle context MTConnect
    doesn't expose).

    Args:
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, availability, execution, controller_mode, program,
        available (bool), running (bool), verdict ('running'|'available_idle'|'down')}.

    Example: mtconnect_oee_snapshot(endpoint="vmc1").
    """
    return ops.mtconnect_oee_snapshot(_target(endpoint))
