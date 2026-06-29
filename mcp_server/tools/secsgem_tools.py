"""Read-only SECS/GEM MCP tools (semiconductor / display fab equipment).

We are the HOST. SECS/GEM (SEMI E5/E30/E37 over HSMS/TCP) is the fab equipment ↔
MES standard. Every tool is wrapped with ``@governed_tool`` and is READ
(risk_level='low'); audited to ~/.iaiops/audit.db.
"""

from typing import Optional

from iaiops.connectors.secsgem import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def secsgem_equipment_status(endpoint: Optional[str] = None) -> dict:
    """[READ] Establish the GEM host link and report communication state + identity.

    Sends Are-You-There (S1F1) after reaching the communicating state.

    Args:
        endpoint: Endpoint name from config; omit to use the default endpoint.
    """
    return ops.equipment_status(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def secsgem_list_status_variables(endpoint: Optional[str] = None) -> dict:
    """[READ] Status-variable namelist (S1F11/F12): SVID → name / units.

    Args:
        endpoint: Endpoint name from config.
    """
    return ops.list_status_variables(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def secsgem_read_status_variables(svids: list, endpoint: Optional[str] = None) -> dict:
    """[READ] Status-variable values (S1F3/F4) for the given SVIDs.

    Args:
        svids: List of status-variable ids to read.
        endpoint: Endpoint name from config.
    """
    return ops.read_status_variables(_target(endpoint), svids)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def secsgem_list_equipment_constants(endpoint: Optional[str] = None) -> dict:
    """[READ] Equipment-constant namelist (S2F29/F30): ECID → name/min/max/default.

    Args:
        endpoint: Endpoint name from config.
    """
    return ops.list_equipment_constants(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def secsgem_read_equipment_constants(ecids: list, endpoint: Optional[str] = None) -> dict:
    """[READ] Equipment-constant values (S2F13/F14) for the given ECIDs.

    Args:
        ecids: List of equipment-constant ids to read.
        endpoint: Endpoint name from config.
    """
    return ops.read_equipment_constants(_target(endpoint), ecids)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def secsgem_list_alarms(endpoint: Optional[str] = None) -> dict:
    """[READ] Alarm list (S5F5/F6): ALID, ALCD (severity), alarm text.

    Args:
        endpoint: Endpoint name from config.
    """
    return ops.list_alarms(_target(endpoint))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def secsgem_list_process_programs(endpoint: Optional[str] = None) -> dict:
    """[READ] Process-program directory (S7F19/F20): the PPID list.

    Args:
        endpoint: Endpoint name from config.
    """
    return ops.list_process_programs(_target(endpoint))
