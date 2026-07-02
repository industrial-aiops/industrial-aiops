"""Omron FINS MCP tools — CS/CJ/CP/NX-via-FINS (in-repo stdlib client, W227/W342).

Reads are governed at risk_level='low'. ``fins_write_words`` is risk_level='high'
(MOC): captures BEFORE values, records an undo descriptor, defaults to dry_run.
未经授权勿对生产控制系统写入.
"""

from typing import Any, Optional

from iaiops.connectors.fins import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def fins_cpu_info(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Omron CPU model/version via FINS 0501 (proves the link).

    Args:
        endpoint: Endpoint name from config (protocol must be 'fins'); omit for default.

    Returns dict: {endpoint, model, version}.

    Example: fins_cpu_info(endpoint="line2").
    """
    return ops.fins_cpu_info(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def fins_cpu_status(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Omron controller status via FINS 0601 (run/stop, mode, errors).

    Args:
        endpoint: Endpoint name from config (protocol must be 'fins').

    Returns dict: {endpoint, status, mode, fatal_error_data, non_fatal_error_data}.

    Example: fins_cpu_status(endpoint="line2").
    """
    return ops.fins_cpu_status(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def fins_read_words(
    area: str = "DM",
    address: int = 0,
    endpoint: Optional[str] = None,
    count: int = 1,
) -> dict:
    """[READ][risk=low] Read 16-bit words from an Omron memory area (FINS 0101).

    Args:
        area: Memory area: "DM", "CIO", "W", "H", "A", or "EM" (current bank).
        address: Word address to start at, e.g. 100 for DM100.
        endpoint: Endpoint name from config.
        count: Number of consecutive words (1..500, capped server-side).

    Returns dict: {endpoint, area, address, count, words:[int,...]} (unsigned 16-bit).

    Example: fins_read_words(area="DM", address=100, count=8).
    """
    return ops.fins_read_words(_target(endpoint), area, address, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def fins_read_bits(
    area: str = "CIO",
    address: int = 0,
    bit: int = 0,
    endpoint: Optional[str] = None,
    count: int = 1,
) -> dict:
    """[READ][risk=low] Read bits from an Omron memory area (FINS 0101, bit codes).

    Args:
        area: Bit-capable area: "CIO", "W", "H", "A", or "DM".
        address: Word address the first bit lives in, e.g. 0 for CIO 0.00.
        bit: Bit number within the word (0..15).
        endpoint: Endpoint name from config.
        count: Number of consecutive bits (1..256).

    Returns dict: {endpoint, area, address, bit, count, bits:[bool,...]}.

    Example: fins_read_bits(area="CIO", address=0, bit=0, count=16).
    """
    return ops.fins_read_bits(_target(endpoint), area, address, bit, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def fins_read_many(
    endpoint: Optional[str] = None,
    items: Optional[list] = None,
) -> dict:
    """[READ][risk=low] Batched word reads over one FINS session (bounded).

    Args:
        endpoint: Endpoint name from config.
        items: Read specs, each {"area": "DM", "address": 100, "count": 2}
            (max 20 items, count capped at 500 each).

    Returns dict: {endpoint, reads:[{area, address, count, words:[int,...]}]}.

    Example: fins_read_many(items=[{"area":"DM","address":100,"count":2},
        {"area":"CIO","address":0,"count":1}]).
    """
    return ops.fins_read_many(_target(endpoint), items)


def _fins_undo(params: dict, result: Any) -> Optional[dict]:
    """Inverse of an applied fins_write_words: restore captured BEFORE words."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if not before:
        return None
    return {
        "tool": "fins_write_words",
        "params": {
            "endpoint": params.get("endpoint"),
            "area": params.get("area"),
            "address": params.get("address"),
            "values": list(before),
            "dry_run": False,
        },
        "note": "Restore prior Omron word values (undo of fins_write_words).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_fins_undo)
@tool_errors("dict")
def fins_write_words(
    area: str,
    address: int,
    values: list,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Write 16-bit words to an Omron area (off by default).

    OT-DANGEROUS. Defaults to dry_run=True. Captures the BEFORE values (read-back
    of the same range) and records an undo descriptor. Set dry_run=False AND
    record an approver (OPCUA_AUDIT_APPROVED_BY) to apply.
    未经授权勿对生产控制系统写入.

    Args:
        area: Memory area to write: "DM", "CIO", "W", "H", "A", or "EM".
        address: Word address to start at, e.g. 100 for DM100.
        values: List of 16-bit word values to write (length 1..500).
        endpoint: Endpoint name from config.
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {area, address, dry_run:true, before, would_write, note};
        applied → {area, address, dry_run:false, before, written, applied:true, _undo_id}.

    Example (preview): fins_write_words(area="DM", address=100, values=[1,2,3]).
    """
    return ops.fins_write_words(_target(endpoint), area, address, values, dry_run=dry_run)
