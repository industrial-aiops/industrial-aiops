"""EtherCAT MCP tools — REAL fieldbus master via pysoem / SOEM (CoE + PDO + AL-state).

Reads are governed at risk_level='low'. ``ethercat_write_sdo`` and
``ethercat_set_state`` are risk_level='high' (MOC): they capture the BEFORE
value/state, record an undo descriptor, and default to dry_run.

pysoem is an OPTIONAL extra (``pip install iaiops[ethercat]``) imported lazily;
EtherCAT needs Linux + root/CAP_NET_RAW + a dedicated NIC + real slaves (no
simulator, macOS unsupported). When unavailable, every tool returns a teaching
error dict instead of crashing. 未经授权勿对生产控制系统写入.
"""

from typing import Any, Optional

from iaiops.connectors.ethercat import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ethercat_master_state(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Open the master on the configured NIC; report bus state.

    Needs Linux + root/CAP_NET_RAW + a dedicated NIC + real slaves (pysoem extra).
    Degrades to a teaching error dict if pysoem/permission/NIC/bus is missing.

    Args:
        endpoint: Endpoint name from config (protocol 'ethercat'); omit for default.

    Returns dict: {endpoint, nic, master_state (INIT/PREOP/SAFEOP/OP/...),
        expected_working_counter, slaves_found, slaves_expected, slave_count_ok}.

    Example: ethercat_master_state(endpoint="bus1").
    """
    return ops.ethercat_master_state(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ethercat_slaves(endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Bus scan: enumerate every slave on the segment.

    Args:
        endpoint: Endpoint name from config (protocol 'ethercat').

    Returns dict: {endpoint, slave_count, slaves:[{index, name, vendor_id,
        product_code, revision, config_addr, state}]}.

    Example: ethercat_slaves(endpoint="bus1").
    """
    return ops.ethercat_slaves(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ethercat_slave_info(slave: int, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Detail one slave: identity, SM/FMMU config, OD summary.

    Args:
        slave: Zero-based slave index (from ethercat_slaves).
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, index, name, vendor_id, product_code, revision,
        config_addr, state, input_bytes, output_bytes, sync_managers[], fmmus[],
        object_dictionary:[{index, name, entry_count}]}.

    Example: ethercat_slave_info(slave=0, endpoint="bus1").
    """
    return ops.ethercat_slave_info(_target(endpoint), slave)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ethercat_read_sdo(
    slave: int,
    index: int,
    subindex: int = 0,
    size: int = 0,
    endpoint: Optional[str] = None,
) -> dict:
    """[READ][risk=low] CoE SDO upload: read one object-dictionary entry (acyclic).

    Args:
        slave: Zero-based slave index.
        index: CoE object index (decimal, e.g. 0x1018 → 4120).
        subindex: Sub-index (default 0).
        size: Expected byte size (0 = let SOEM size it).
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, slave, index, subindex, byte_length, hex, as_uint}.

    Example: ethercat_read_sdo(slave=0, index=0x1018, subindex=1, endpoint="bus1").
    """
    return ops.ethercat_read_sdo(_target(endpoint), slave, index, subindex, size)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ethercat_read_pdo(slave: int, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] One cyclic snapshot of a slave's input process-data image.

    Does a single send/receive cycle (never loops) and returns the input image.

    Args:
        slave: Zero-based slave index.
        endpoint: Endpoint name from config.

    Returns dict: {endpoint, slave, working_counter, input_byte_length, input_hex,
        output_byte_length}.

    Example: ethercat_read_pdo(slave=0, endpoint="bus1").
    """
    return ops.ethercat_read_pdo(_target(endpoint), slave)


def _sdo_undo(params: dict, result: Any) -> Optional[dict]:
    """Inverse of an applied ethercat_write_sdo: restore the captured BEFORE bytes."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if not before:  # empty hex string → no read-back captured, cannot invert
        return None
    return {
        "tool": "ethercat_write_sdo",
        "params": {
            "endpoint": params.get("endpoint"),
            "slave": params.get("slave"),
            "index": params.get("index"),
            "subindex": params.get("subindex", 0),
            "value": before,
            "dry_run": False,
        },
        "note": "Restore prior CoE SDO value (undo of ethercat_write_sdo).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_sdo_undo)
@tool_errors("dict")
def ethercat_write_sdo(
    slave: int,
    index: int,
    value: str,
    subindex: int = 0,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] CoE SDO download: write one OD entry (off by default).

    OT-DANGEROUS. Defaults to dry_run=True (nothing written). ``value`` is a hex
    string of the raw little-endian bytes (e.g. 'e803' = 1000 as uint16). Captures
    the BEFORE value (SDO read-back) and records an undo descriptor. Set
    dry_run=False AND record an approver to apply. 未经授权勿对生产控制系统写入.

    Args:
        slave: Zero-based slave index.
        index: CoE object index (decimal, e.g. 0x607A → 24698).
        value: Hex string of raw little-endian bytes to write.
        subindex: Sub-index (default 0).
        endpoint: Endpoint name from config.
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {slave, index, dry_run:true, before, would_write, note};
        applied → {slave, index, dry_run:false, before, written, applied:true}.

    Example (preview): ethercat_write_sdo(slave=0, index=0x607A, value="e8030000").
    """
    return ops.ethercat_write_sdo(
        _target(endpoint), slave, index, value, subindex, dry_run=dry_run
    )


def _state_undo(params: dict, result: Any) -> Optional[dict]:
    """Inverse of an applied ethercat_set_state: request the captured BEFORE state."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if not before or "+ERR" in str(before) or str(before) in ("NONE", "BOOT"):
        return None  # not a clean, re-requestable AL-state
    scope = str(result.get("scope", "master"))
    slave = params.get("slave", -1)
    if scope.startswith("slave[") and slave is None:
        return None
    return {
        "tool": "ethercat_set_state",
        "params": {
            "endpoint": params.get("endpoint"),
            "state": before,
            "slave": slave if slave is not None else -1,
            "dry_run": False,
        },
        "note": "Restore prior AL-state (undo of ethercat_set_state).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_state_undo)
@tool_errors("dict")
def ethercat_set_state(
    state: str,
    slave: int = -1,
    endpoint: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Request an AL-state transition (off by default).

    OT-DANGEROUS: moving to/from OP can START or STOP machine motion. Defaults to
    dry_run=True. ``slave`` < 0 applies to the master (all slaves). Captures the
    CURRENT state for undo. Set dry_run=False AND record an approver to apply.
    未经授权勿对生产控制系统写入.

    Args:
        state: Target AL-state: INIT | PREOP | SAFEOP | OP (or a numeric code).
        slave: Zero-based slave index, or -1 (default) for the whole master.
        endpoint: Endpoint name from config.
        dry_run: When True (default) returns a preview without changing state.

    Returns dict: dry-run → {scope, dry_run:true, before, would_request, note};
        applied → {scope, dry_run:false, before, requested, reached, applied:true}.

    Example (preview): ethercat_set_state(state="OP", slave=0, endpoint="bus1").
    """
    return ops.ethercat_set_state(_target(endpoint), state, slave, dry_run=dry_run)
