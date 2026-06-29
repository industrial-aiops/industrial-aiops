"""EtherNet/IP MCP tools — Rockwell/Allen-Bradley Logix (pycomm3, CIP).

Reads are governed at risk_level='low'. ``eip_write_tag`` is risk_level='high'
(MOC): it captures the BEFORE value, records an undo descriptor, and defaults to
dry_run. ControlLogix / CompactLogix tag access only (PLC-5/SLC PCCC is roadmap).
未经授权勿对生产控制系统写入.
"""

from typing import Any, Optional

from iaiops.connectors.eip import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_controller_info(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Logix controller identity (proves the CIP link).

    Args:
        endpoint: Endpoint name from config (protocol 'ethernetip'/'eip'); omit for default.

    Returns dict: {endpoint, host, slot, controller:{vendor, product_type,
        product_code, revision, serial, product_name, name, ...}, info_error}.

    Example: eip_controller_info(endpoint="cell5").
    """
    return ops.eip_controller_info(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_list_tags(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Discover the controller's tag list (names/types/structures).

    The headline pycomm3 feature: enumerate the controller's symbol table without
    prior knowledge. Program-scoped tags appear as 'Program:<prog>.<tag>'.

    Args:
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, tag_count, tags:[{name, data_type, tag_type,
        structure (bool), dimensions}]}.

    Example: eip_list_tags(endpoint="cell5").
    """
    return ops.eip_list_tags(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_read_tag(tag: str, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Read one Logix tag (or array element) with its type.

    Args:
        tag: Logix tag name, e.g. 'Conveyor.Speed' or 'Array[3]' or 'Program:Main.X'.
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, tag, value, type, error, good}.

    Example: eip_read_tag(tag="Conveyor.Speed", endpoint="cell5").
    """
    return ops.eip_read_tag(_target(endpoint), tag)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_read_many(tags: list, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Batch-read many Logix tags in one request (auto multi-packet).

    Args:
        tags: Tag names, e.g. ["Speed", "Temp", "Array[0]"].
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, count, items:[{tag, value, type, error, good}]}.

    Example: eip_read_many(tags=["Speed","Temp"], endpoint="cell5").
    """
    return ops.eip_read_many(_target(endpoint), tags)


def _eip_undo(params: dict, result: Any) -> Optional[dict]:
    """Inverse of an applied eip_write_tag: restore the captured BEFORE value."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if before is None:
        return None
    return {
        "tool": "eip_write_tag",
        "params": {
            "endpoint": params.get("endpoint"),
            "tag": params.get("tag"),
            "value": before,
            "dry_run": False,
        },
        "note": "Restore prior Logix tag value (undo of eip_write_tag).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_eip_undo)
@tool_errors("dict")
def eip_write_tag(
    tag: str,
    value: Any,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Write ONE value to a Logix tag (off by default).

    OT-DANGEROUS. Defaults to dry_run=True (nothing written). Captures the BEFORE
    value (read-back) and records an undo descriptor so the change is reversible.
    Set dry_run=False AND record an approver (OPCUA_AUDIT_APPROVED_BY) to apply.
    未经授权勿对生产控制系统写入.

    Args:
        tag: Logix tag name to write.
        value: Value to write (pycomm3 coerces to the tag's CIP type).
        endpoint: Endpoint name from config.
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {tag, dry_run:true, before, would_write, note};
        applied → {tag, dry_run:false, before, written, applied:true, _undo_id}.

    Example (preview): eip_write_tag(tag="Setpoint", value=42, endpoint="cell5").
    """
    return ops.eip_write_tag(_target(endpoint), tag, value, dry_run=dry_run)
