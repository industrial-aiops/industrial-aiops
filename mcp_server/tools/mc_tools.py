"""Mitsubishi MC MCP tools — 三菱 Q/L/iQ-R/iQ-L (pymcprotocol, 3E binary).

Reads are governed at risk_level='low'. ``mc_write_words`` is risk_level='high'
(MOC): captures BEFORE values, records an undo descriptor, defaults to dry_run.
未经授权勿对生产控制系统写入.
"""

from typing import Any, Optional

from iaiops.connectors.mc import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mc_cpu_status(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] MELSEC CPU type/code (proves the MC link is alive).

    Args:
        endpoint: Endpoint name from config (protocol must be 'mc'); omit for default.

    Returns dict: {endpoint, plctype, cpu_type, cpu_code}.

    Example: mc_cpu_status(endpoint="cell3").
    """
    return ops.mc_cpu_status(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mc_read_words(headdevice: str, endpoint: Optional[str] = None, count: int = 1) -> dict:
    """[READ][risk=low] Batch-read 16-bit word devices from a head device.

    Args:
        headdevice: MELSEC word device, e.g. "D100", "W10", "R0".
        endpoint: Endpoint name from config.
        count: Number of consecutive words (1..256, capped server-side).

    Returns dict: {endpoint, headdevice, count, words:[int,...]} (signed 16-bit).

    Example: mc_read_words(headdevice="D100", count=8).
    """
    return ops.mc_read_words(_target(endpoint), headdevice, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mc_read_bits(headdevice: str, endpoint: Optional[str] = None, count: int = 1) -> dict:
    """[READ][risk=low] Batch-read bit devices from a head device.

    Args:
        headdevice: MELSEC bit device, e.g. "M0", "X10", "Y20", "B0".
        endpoint: Endpoint name from config.
        count: Number of consecutive bits (1..256).

    Returns dict: {endpoint, headdevice, count, bits:[bool,...]}.

    Example: mc_read_bits(headdevice="M0", count=16).
    """
    return ops.mc_read_bits(_target(endpoint), headdevice, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def mc_read_many(
    endpoint: Optional[str] = None,
    word_devices: Optional[list] = None,
    dword_devices: Optional[list] = None,
) -> dict:
    """[READ][risk=low] Random-read scattered word + dword devices in one request.

    Args:
        endpoint: Endpoint name from config.
        word_devices: Word device names, e.g. ["D100", "D200", "M0"].
        dword_devices: Double-word device names, e.g. ["D300", "D400"].

    Returns dict: {endpoint, words:[{device, value}], dwords:[{device, value}]}.

    Example: mc_read_many(word_devices=["D100","D101"], dword_devices=["D200"]).
    """
    return ops.mc_read_many(_target(endpoint), word_devices, dword_devices)


def _mc_undo(params: dict, result: Any) -> Optional[dict]:
    """Inverse of an applied mc_write_words: restore captured BEFORE words."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if not before:
        return None
    return {
        "tool": "mc_write_words",
        "params": {
            "endpoint": params.get("endpoint"),
            "headdevice": params.get("headdevice"),
            "values": list(before),
            "dry_run": False,
        },
        "note": "Restore prior MELSEC word values (undo of mc_write_words).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_mc_undo)
@tool_errors("dict")
def mc_write_words(
    headdevice: str,
    values: list,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Write 16-bit words from a head device (off by default).

    OT-DANGEROUS. Defaults to dry_run=True. Captures the BEFORE values (read-back
    of the same range) and records an undo descriptor. Set dry_run=False AND
    record an approver (OPCUA_AUDIT_APPROVED_BY) to apply.
    未经授权勿对生产控制系统写入.

    Args:
        headdevice: MELSEC word device to start at, e.g. "D100".
        values: List of 16-bit word values to write (length 1..256).
        endpoint: Endpoint name from config.
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {headdevice, dry_run:true, before, would_write, note};
        applied → {headdevice, dry_run:false, before, written, applied:true, _undo_id}.

    Example (preview): mc_write_words(headdevice="D100", values=[1,2,3]).
    """
    return ops.mc_write_words(_target(endpoint), headdevice, values, dry_run=dry_run)
