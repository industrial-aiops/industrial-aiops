"""IEC 61850 MMS MCP tools — read-only model browse + read (iec61850 extra).

Governed at risk_level='low'. Control blocks (Oper / select-before-operate) are
intentionally NOT exposed in this preview. The libiec61850 binding is an OPTIONAL
extra (``pip install iaiops[iec61850]``, needs libiec61850 built) imported lazily;
when missing, every tool returns a teaching error dict. Preview — binding/API shape
unverified against a live IED.
"""

from typing import Optional

from iaiops.connectors.iec61850 import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iec61850_device_directory(
    include_children: bool = False, endpoint: Optional[str] = None
) -> dict:
    """[READ][risk=low] List the IED's logical devices (optionally their children).

    Args:
        include_children: Also browse each logical device's immediate model children.
        endpoint: Endpoint name from config (protocol 'iec61850'); omit for default.

    Returns dict: {endpoint, logical_device_count, logical_devices:[{logical_device,
        children[]?, child_count?}]}.

    Example: iec61850_device_directory(include_children=True, endpoint="ied1").
    """
    return ops.iec61850_device_directory(_target(endpoint), include_children)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iec61850_browse(reference: str, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Browse immediate model children under a reference (LD/LN/DO).

    Args:
        reference: Model reference, e.g. 'IED1LD0' or 'IED1LD0/LLN0'.
        endpoint: Endpoint name from config (protocol 'iec61850').

    Returns dict: {endpoint, reference, child_count, children[]}.

    Example: iec61850_browse(reference="IED1LD0/MMXU1", endpoint="ied1").
    """
    return ops.iec61850_browse(_target(endpoint), reference)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def iec61850_read(reference: str, fc: str = "MX", endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Read one data attribute by object-reference + functional constraint.

    Args:
        reference: Data-attribute object reference, e.g. 'IED1MMXU1.TotW.mag.f'.
        fc: Functional constraint — MX (measurands), ST (status), CF (config), …
        endpoint: Endpoint name from config (protocol 'iec61850').

    Returns dict: {endpoint, reference, fc, value, error}.

    Example: iec61850_read(reference="IED1MMXU1.TotW.mag.f", fc="MX", endpoint="ied1").
    """
    return ops.iec61850_read(_target(endpoint), reference, fc)
