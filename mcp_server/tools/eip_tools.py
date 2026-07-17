"""EtherNet/IP MCP tools — Rockwell/Allen-Bradley (pycomm3, CIP).

Reads are governed at risk_level='low'. ``eip_write_tag`` is risk_level='high'
(MOC): it captures the BEFORE value, records an undo descriptor, and defaults to
dry_run. A ``plctype`` selector (config key or per-call arg) picks the driver:
``logix`` (default, ControlLogix/CompactLogix/GuardLogix symbolic tags),
``slc`` (PLC-5/SLC-500/MicroLogix PCCC data tables — N7:0, B3:0/0, F8:0), or
``micro800`` (Micro820/850/870 symbolic variables). Real PLC-5/SLC/MicroLogix/
Micro800 hardware is 待核实 (mocked-driver paths only).
未经授权勿对生产控制系统写入.
"""

from typing import Any, Optional

from iaiops.connectors.eip import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_controller_info(endpoint: Optional[str] = None, plctype: Optional[str] = None) -> dict:
    """[READ][risk=low] Controller identity (proves the CIP link).

    Args:
        endpoint: Endpoint name from config (protocol 'ethernetip'/'eip'); omit for default.
        plctype: Driver selector override — 'logix' (default), 'slc' (PLC-5/SLC-500/
            MicroLogix, PCCC), or 'micro800'. Omit to use the endpoint's configured plctype.

    Returns dict: {endpoint, host, slot, plctype, controller, info_error}. For
        logix/micro800 controller carries {vendor, product_type, revision, serial,
        product_name, name, ...}; for slc it carries {processor_type}.

    Example: eip_controller_info(endpoint="slc05", plctype="slc").
    """
    return ops.eip_controller_info(_target(endpoint), plctype=plctype)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_list_tags(endpoint: Optional[str] = None, plctype: Optional[str] = None) -> dict:
    """[READ][risk=low] Discover the controller's tags (Logix) or PCCC data files (SLC).

    Logix/Micro800: enumerate the controller's symbol table without prior
    knowledge (program-scoped tags appear as 'Program:<prog>.<tag>'). SLC/PCCC has
    no symbol table, so the data-file directory (N7/B3/F8/... with element counts)
    is returned instead.

    Args:
        endpoint: Endpoint name from config.
        plctype: Driver selector override — 'logix' (default), 'slc', or 'micro800'.

    Returns dict: logix → {endpoint, plctype, tag_count, tags:[{name, data_type,
        tag_type, structure, dimensions}]}; slc → {endpoint, plctype, file_count,
        files:[{file, elements, length}], directory_error, note}.

    Example: eip_list_tags(endpoint="cell5"); eip_list_tags(endpoint="slc05", plctype="slc").
    """
    return ops.eip_list_tags(_target(endpoint), plctype=plctype)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_read_tag(tag: str, endpoint: Optional[str] = None, plctype: Optional[str] = None) -> dict:
    """[READ][risk=low] Read one tag/address with its type.

    Args:
        tag: Logix tag ('Conveyor.Speed', 'Array[3]', 'Program:Main.X') OR an
            SLC/PCCC data-table address ('N7:0' int, 'B3:0/0' bit, 'F8:0' float,
            'T4:0.ACC', 'N7:0{10}' slice).
        endpoint: Endpoint name from config.
        plctype: Driver selector override — 'logix' (default), 'slc' (PCCC), or 'micro800'.

    Returns dict: {endpoint, plctype, tag, value, type, error, good}.

    Example: eip_read_tag(tag="Conveyor.Speed", endpoint="cell5");
        eip_read_tag(tag="N7:0", endpoint="slc05", plctype="slc").
    """
    return ops.eip_read_tag(_target(endpoint), tag, plctype=plctype)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def eip_read_many(
    tags: list[str], endpoint: Optional[str] = None, plctype: Optional[str] = None
) -> dict:
    """[READ][risk=low] Batch-read many tags/addresses in one request.

    Args:
        tags: Logix tag names (["Speed", "Temp", "Array[0]"]) OR SLC/PCCC
            data-table addresses (["N7:0", "F8:0", "B3:0/0"]).
        endpoint: Endpoint name from config.
        plctype: Driver selector override — 'logix' (default), 'slc' (PCCC), or 'micro800'.

    Returns dict: {endpoint, plctype, count, items:[{tag, value, type, error, good}]}.

    Example: eip_read_many(tags=["Speed","Temp"], endpoint="cell5");
        eip_read_many(tags=["N7:0","F8:0"], endpoint="slc05", plctype="slc").
    """
    return ops.eip_read_many(_target(endpoint), tags, plctype=plctype)


def _eip_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
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
            # Carry the driver selector so the restore hits the same PLC family.
            "plctype": params.get("plctype"),
            "dry_run": False,
        },
        "note": "Restore prior tag/data-table value (undo of eip_write_tag).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_eip_undo)
@tool_errors("dict")
def eip_write_tag(
    tag: str,
    value: Any,
    endpoint: Optional[str] = None,
    plctype: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Write ONE value to a tag/data-table address (off by default).

    OT-DANGEROUS. Defaults to dry_run=True (nothing written). Captures the BEFORE
    value (read-back) and records an undo descriptor so the change is reversible.
    Set dry_run=False AND record an approver (OPCUA_AUDIT_APPROVED_BY) to apply.
    未经授权勿对生产控制系统写入.

    Args:
        tag: Logix tag name OR SLC/PCCC data-table address ('N7:0', 'F8:0', 'B3:0/0').
        value: Value to write (pycomm3 coerces to the tag's CIP/PCCC type).
        endpoint: Endpoint name from config.
        plctype: Driver selector override — 'logix' (default), 'slc' (PCCC), or 'micro800'.
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {tag, plctype, dry_run:true, before, would_write, note};
        applied → {tag, plctype, dry_run:false, before, written, applied:true, _undo_id}.

    Example (preview): eip_write_tag(tag="Setpoint", value=42, endpoint="cell5").
    """
    return ops.eip_write_tag(_target(endpoint), tag, value, plctype=plctype, dry_run=dry_run)
