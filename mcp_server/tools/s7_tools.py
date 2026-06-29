"""S7comm MCP tools — Siemens + 仿西门子 国产 PLCs (pyS7, ISO-on-TCP).

Reads are governed at risk_level='low'. ``s7_write_db`` is risk_level='high'
(MOC): it captures the BEFORE value, records an undo descriptor, and defaults to
dry_run. 未经授权勿对生产控制系统写入.
"""

from typing import Any, Optional

from iaiops.connectors.s7 import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def s7_cpu_info(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] S7 CPU identity + run/stop status (proves the link).

    Args:
        endpoint: Endpoint name from config (protocol must be 's7'); omit for default.

    Returns dict: {endpoint, rack, slot, cpu_status (e.g. 'run'/'stop'),
        cpu_info: {module, serial, version, ...}}.

    Example: s7_cpu_info(endpoint="press1").
    """
    return ops.s7_cpu_info(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def s7_read_area(
    area: str,
    dtype: str,
    start: int,
    endpoint: Optional[str] = None,
    db: int = 0,
    count: int = 1,
    bit: int = 0,
) -> dict:
    """[READ][risk=low] Read ``count`` items of a type from an S7 memory area.

    Args:
        area: Memory area — DB | M (merker/flag) | I (input) | Q (output).
        dtype: S7 data type — BIT|BYTE|WORD|INT|DWORD|DINT|REAL|LREAL|CHAR.
        start: Byte offset within the area/DB (0-based).
        endpoint: Endpoint name from config.
        db: Data block number (required when area=DB).
        count: Number of consecutive items (1..100, capped server-side).
        bit: Bit offset 0..7 (only when dtype=BIT).

    Returns dict: {endpoint, area, db, dtype, start, count,
        items:[{address, value}]}. ``value`` is bool/int/float per dtype.

    Example: s7_read_area(area="DB", dtype="REAL", start=4, db=1, count=2).
    """
    return ops.s7_read_area(_target(endpoint), area, dtype, start, db=db, count=count, bit=bit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def s7_read_db(
    db: int, dtype: str, start: int, endpoint: Optional[str] = None, count: int = 1
) -> dict:
    """[READ][risk=low] Read ``count`` ``dtype`` items from data block ``db``.

    Args:
        db: Data block number (e.g. 1 for DB1).
        dtype: S7 data type — BIT|BYTE|WORD|INT|DWORD|DINT|REAL|LREAL.
        start: Byte offset within the DB (0-based).
        endpoint: Endpoint name from config.
        count: Number of consecutive items (1..100).

    Returns dict: {endpoint, area:'DB', db, dtype, start, count, items:[{address, value}]}.

    Example: s7_read_db(db=1, dtype="INT", start=0, count=10).
    """
    return ops.s7_read_db(_target(endpoint), db, dtype, start, count)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def s7_read_many(addresses: list, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Batch-read raw pyS7 address strings in one request.

    Args:
        addresses: pyS7 addresses, e.g. ["DB1,REAL4", "DB1,X0.0", "MW10", "I0.0"].
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, count, items:[{address, value}]}.

    Example: s7_read_many(addresses=["DB1,REAL4","M0.0"]).
    """
    return ops.s7_read_many(_target(endpoint), addresses)


def _s7_undo(params: dict, result: Any) -> Optional[dict]:
    """Inverse of an applied s7_write_db: restore the captured BEFORE value."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if before is None:
        return None
    return {
        "tool": "s7_write_db",
        "params": {
            "endpoint": params.get("endpoint"),
            "db": params.get("db"),
            "dtype": params.get("dtype"),
            "start": params.get("start"),
            "value": before,
            "dry_run": False,
        },
        "note": "Restore prior S7 DB value (undo of s7_write_db).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_s7_undo)
@tool_errors("dict")
def s7_write_db(
    db: int,
    dtype: str,
    start: int,
    value: Any,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Write ONE value to an S7 data block (off by default).

    OT-DANGEROUS. Defaults to dry_run=True (nothing written). Captures the BEFORE
    value (read-back) and records an undo descriptor so the change is reversible.
    Set dry_run=False AND record an approver (OPCUA_AUDIT_APPROVED_BY) to apply.
    未经授权勿对生产控制系统写入.

    Args:
        db: Data block number.
        dtype: S7 data type — BIT|BYTE|WORD|INT|DWORD|DINT|REAL|LREAL.
        start: Byte offset within the DB.
        value: Value to write (coerced to the dtype's Python type).
        endpoint: Endpoint name from config.
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {address, dry_run:true, before, would_write, note};
        applied → {address, dry_run:false, before, written, applied:true, _undo_id}.

    Example (preview): s7_write_db(db=1, dtype="INT", start=0, value=42).
    """
    return ops.s7_write_db(_target(endpoint), db, dtype, start, value, dry_run=dry_run)
