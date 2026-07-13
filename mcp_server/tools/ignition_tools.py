"""Gateway MES/SCADA read-layer MCP tools (factory edition) — vendor web API.

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads only
when the ``factory`` edition is selected. These tools talk to the vendor SCADA/MES
platform's Gateway HTTP web API — the MES-ish production surface (module health,
tag tree, current tag values, active alarms, tag-history) that the base ``opcua``
connector does NOT cover. The platform ALSO exposes an OPC-UA server, but that is
already handled by the ``opcua`` connector; this module never touches OPC-UA.

Every tool is READ-ONLY at risk_level='low'. There are NO write tools in this
connector — the governed complement to the platform's own official MCP module,
differentiated by the audit/budget harness, not by writing.
"""

from typing import Optional

from iaiops.connectors.ignition import ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ignition_gateway_status(
    base_url: str,
    flavor: str = "webdev",
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Gateway/module health + reachability (the Gateway doctor step).

    Talks to the vendor SCADA/MES platform's Gateway HTTP web API (not OPC-UA —
    that stays on the opcua connector). The API token is resolved from the
    encrypted secret store by key name, never passed inline. Token-egress guard:
    with a secret set, base_url must point at an internal host (private IP /
    single-label / .local-style name) or a host the operator allowlisted via
    IAIOPS_TOKEN_EGRESS_HOSTS — public hosts are refused before any request
    (prevents stored-token exfiltration).

    Args:
        base_url: Gateway HTTP base URL, e.g. 'https://gw-host:8043'.
        flavor: Gateway API deployment dialect — 'webdev' or 'gateway'.
        secret_name: Secret-store key holding the API token (omit if none).
        verify_tls: Verify the Gateway's TLS certificate (default True).

    Returns dict: {flavor, base_url, reachable, gateway:{name, version, state},
        module_count, modules:[{name, state, version}]}.

    Example: ignition_gateway_status(base_url="https://gw:8043", flavor="webdev").
    """
    return ops.gateway_status(base_url, flavor, secret_name=secret_name, verify_tls=verify_tls)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ignition_tag_browse(
    base_url: str,
    provider: str,
    path: str = "",
    flavor: str = "webdev",
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Browse the tag tree under a provider/path.

    Args:
        base_url: Gateway HTTP base URL.
        provider: Tag provider name (e.g. 'default').
        path: Folder path under the provider to browse (blank = root).
        flavor: Gateway API deployment dialect — 'webdev' or 'gateway'.
        secret_name: Secret-store key holding the API token (omit if none).
        verify_tls: Verify the Gateway's TLS certificate (default True).

    Returns dict: {flavor, base_url, provider, path, node_count,
        nodes:[{name, path, type, has_children}]}.

    Example: ignition_tag_browse(base_url="https://gw:8043", provider="default",
        path="Line1").
    """
    return ops.tag_browse(
        base_url, provider, path, flavor, secret_name=secret_name, verify_tls=verify_tls
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ignition_tag_read(
    base_url: str,
    provider: str,
    tag_paths: list[str],
    flavor: str = "webdev",
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Current value(s)/quality/timestamp for tag path(s).

    Args:
        base_url: Gateway HTTP base URL.
        provider: Tag provider name (e.g. 'default').
        tag_paths: Tag paths to read (from ignition_tag_browse).
        flavor: Gateway API deployment dialect — 'webdev' or 'gateway'.
        secret_name: Secret-store key holding the API token (omit if none).
        verify_tls: Verify the Gateway's TLS certificate (default True).

    Returns dict: {flavor, base_url, provider, tag_count,
        tags:[{path, value, quality, timestamp}]}.

    Example: ignition_tag_read(base_url="https://gw:8043", provider="default",
        tag_paths=["Line1/OvenTemp"]).
    """
    return ops.tag_read(
        base_url, provider, tag_paths, flavor, secret_name=secret_name, verify_tls=verify_tls
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ignition_alarm_status(
    base_url: str,
    flavor: str = "webdev",
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Active/acknowledged alarm list (normalized).

    Args:
        base_url: Gateway HTTP base URL.
        flavor: Gateway API deployment dialect — 'webdev' or 'gateway'.
        secret_name: Secret-store key holding the API token (omit if none).
        verify_tls: Verify the Gateway's TLS certificate (default True).

    Returns dict: {flavor, base_url, alarm_count,
        alarms:[{name, source, priority, state, label, timestamp}]}.

    Example: ignition_alarm_status(base_url="https://gw:8043", flavor="webdev").
    """
    return ops.alarm_status(base_url, flavor, secret_name=secret_name, verify_tls=verify_tls)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def ignition_tag_history(
    base_url: str,
    provider: str,
    tag_path: str,
    start: str,
    end: str,
    count: int = 100,
    flavor: str = "webdev",
    secret_name: Optional[str] = None,
    verify_tls: bool = True,
) -> dict:
    """[READ][risk=low] Historian query for one tag over a time window (aggregated).

    Args:
        base_url: Gateway HTTP base URL.
        provider: Tag provider name (e.g. 'default').
        tag_path: Tag path whose history to query.
        start: Window start (ISO-8601 or the gateway's accepted time string).
        end: Window end (ISO-8601 or the gateway's accepted time string).
        count: Max samples to return (1..5000, capped server-side).
        flavor: Gateway API deployment dialect — 'webdev' or 'gateway'.
        secret_name: Secret-store key holding the API token (omit if none).
        verify_tls: Verify the Gateway's TLS certificate (default True).

    Returns dict: {flavor, base_url, provider, tag_path, start, end,
        sample_count, samples:[{timestamp, value, quality}]}.

    Example: ignition_tag_history(base_url="https://gw:8043", provider="default",
        tag_path="Line1/OvenTemp", start="2026-07-13T00:00:00Z",
        end="2026-07-13T06:00:00Z", count=200).
    """
    return ops.tag_history(
        base_url,
        provider,
        tag_path,
        start,
        end,
        count,
        flavor,
        secret_name=secret_name,
        verify_tls=verify_tls,
    )
