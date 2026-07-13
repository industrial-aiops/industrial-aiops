"""BAS controller-layer MCP tools (building edition) — vendor supervisory REST.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``building`` edition is selected. These tools sit ABOVE the ``bacnet``
field-protocol connector, talking to the vendor supervisory controller's REST API
(Johnson Controls Metasys/OpenBlue, Tridium Niagara oBIX/REST) which aggregates
many field points, alarms and trends behind one authenticated endpoint.

Reads are governed at risk_level='low'. ``bas_command`` is risk_level='high'
(MOC): it refuses life-safety points outright, captures the BEFORE value, records
an undo descriptor, and defaults to dry_run. 未经授权勿对生产控制系统写入.
"""

from typing import Any, Optional

from iaiops.connectors.bas import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bas_point_list(
    base_url: str,
    vendor: str,
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] List a BAS controller's points/objects (vendor-normalized).

    Talks to the vendor supervisory controller's REST API (above BACnet). The
    bearer token is resolved from the encrypted secret store by key name, never
    passed inline. Token-egress guard: with a secret set, base_url must point at
    an internal host (private IP / single-label / .local-style name) or a host
    the operator allowlisted via IAIOPS_TOKEN_EGRESS_HOSTS — public hosts are
    refused before any request (prevents stored-token exfiltration).

    Args:
        base_url: Controller REST base URL, e.g. 'https://bms-host/api'.
        vendor: Controller dialect — 'metasys' or 'niagara'.
        secret_name: Secret-store key holding the bearer token (omit if none).
        verify_tls: Verify the controller's TLS certificate (default True). Passing
            False is refused unless the operator set IAIOPS_ALLOW_INSECURE_TLS=1.

    Returns dict: {vendor, base_url, point_count, points:[{id, name, value,
        unit, status}]}.

    Example: bas_point_list(base_url="https://bms/api", vendor="metasys").
    """
    return ops.point_list(base_url, vendor, secret_name=secret_name, verify_tls=verify_tls)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bas_point_read(
    base_url: str,
    vendor: str,
    point_ids: list[str],
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Present value(s) for one or more BAS controller points.

    Args:
        base_url: Controller REST base URL.
        vendor: Controller dialect — 'metasys' or 'niagara'.
        point_ids: Point ids/hrefs to read (from bas_point_list).
        secret_name: Secret-store key holding the bearer token (omit if none).
        verify_tls: Verify the controller's TLS certificate (default True). Passing
            False is refused unless the operator set IAIOPS_ALLOW_INSECURE_TLS=1.

    Returns dict: {vendor, base_url, point_count, points:[{id, name, value,
        unit, status}]}.

    Example: bas_point_read(base_url="https://bms/api", vendor="metasys",
        point_ids=["ce820889-..."]).
    """
    return ops.point_read(
        base_url, vendor, point_ids, secret_name=secret_name, verify_tls=verify_tls
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bas_alarm_list(
    base_url: str,
    vendor: str,
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Active alarms/events from a BAS controller (normalized).

    Args:
        base_url: Controller REST base URL.
        vendor: Controller dialect — 'metasys' or 'niagara'.
        secret_name: Secret-store key holding the bearer token (omit if none).
        verify_tls: Verify the controller's TLS certificate (default True). Passing
            False is refused unless the operator set IAIOPS_ALLOW_INSECURE_TLS=1.

    Returns dict: {vendor, base_url, alarm_count, alarms:[{id, name, priority,
        state, message, timestamp}]}.

    Example: bas_alarm_list(base_url="https://bms/api", vendor="niagara").
    """
    return ops.alarm_list(base_url, vendor, secret_name=secret_name, verify_tls=verify_tls)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bas_trend_read(
    base_url: str,
    vendor: str,
    point_id: str,
    count: int = 100,
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Historical trend samples for one BAS point (bounded).

    Args:
        base_url: Controller REST base URL.
        vendor: Controller dialect — 'metasys' or 'niagara'.
        point_id: Point id/href whose trend history to read.
        count: Max samples to return (1..5000, capped server-side).
        secret_name: Secret-store key holding the bearer token (omit if none).
        verify_tls: Verify the controller's TLS certificate (default True). Passing
            False is refused unless the operator set IAIOPS_ALLOW_INSECURE_TLS=1.

    Returns dict: {vendor, base_url, point_id, sample_count,
        samples:[{timestamp, value}]}.

    Example: bas_trend_read(base_url="https://bms/api", vendor="metasys",
        point_id="ce820889-...", count=200).
    """
    return ops.trend_read(
        base_url, vendor, point_id, count, secret_name=secret_name, verify_tls=verify_tls
    )


def _bas_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of an applied bas_command: restore the captured BEFORE value."""
    if not isinstance(result, dict) or not result.get("applied"):
        return None
    before = result.get("before")
    if before is None:
        return None
    return {
        "tool": "bas_command",
        "params": {
            "base_url": params.get("base_url"),
            "vendor": params.get("vendor"),
            "point_id": params.get("point_id"),
            "value": before,
            "secret_name": params.get("secret_name"),
            "verify_tls": params.get("verify_tls", True),
            "dry_run": False,
        },
        "note": "Restore prior BAS point value (undo of bas_command).",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_bas_undo)
@tool_errors("dict")
def bas_command(
    base_url: str,
    vendor: str,
    point_id: str,
    value: Any,
    point_name: str = "",
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
    dry_run: bool = True,
) -> dict:
    """[WRITE][risk=HIGH][MOC] Command ONE BAS controller point (off by default).

    OT-DANGEROUS. REFUSES any life-safety point (fire/smoke/egress/pressurization)
    OUTRIGHT — before any network I/O. Defaults to dry_run=True (nothing written).
    Captures the BEFORE value (read-back) and records an undo descriptor so the
    change is reversible. Set dry_run=False AND record an approver
    (OPCUA_AUDIT_APPROVED_BY) to apply. 未经授权勿对生产控制系统写入.

    Args:
        base_url: Controller REST base URL.
        vendor: Controller dialect — 'metasys' or 'niagara'.
        point_id: Point id/href to command.
        value: Value to write (coerced to the point's type by the controller).
        point_name: Optional point name — also checked against the life-safety
            denylist (belt-and-suspenders with point_id).
        secret_name: Secret-store key holding the bearer token (omit if none).
        verify_tls: Verify the controller's TLS certificate (default True). Passing
            False is refused unless the operator set IAIOPS_ALLOW_INSECURE_TLS=1.
        dry_run: When True (default) returns a preview without writing.

    Returns dict: dry-run → {vendor, point_id, dry_run:true, before, would_write,
        note}; applied → {vendor, point_id, dry_run:false, before, written,
        applied:true, _undo_id}.

    Example (preview): bas_command(base_url="https://bms/api", vendor="metasys",
        point_id="ce82...", value=21.0).
    """
    return ops.command(
        base_url,
        vendor,
        point_id,
        value,
        point_name=point_name,
        secret_name=secret_name,
        verify_tls=verify_tls,
        dry_run=dry_run,
    )
