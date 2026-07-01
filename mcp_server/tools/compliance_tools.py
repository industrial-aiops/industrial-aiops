"""信创 / compliance + national-TSDB MCP tools (always exposed).

``compliance_mapping`` is a read-only self-assessment against 《工控系统网络安全防护
指南》. ``historian_push`` writes already-collected telemetry to a domestic
time-series DB (TDengine / IoTDB) — data egress to the operator's OWN historian
(low-risk, governed), not a control-system write. The TSDB client libraries are
optional extras (``iaiops[tdengine]`` / ``iaiops[iotdb]``) imported lazily.
"""

from iaiops.core.brain.compliance import compliance_frameworks as _compliance_frameworks
from iaiops.core.brain.compliance import compliance_mapping as _compliance_mapping
from iaiops.core.governance import governed_tool
from iaiops.core.sink.push import historian_push as _historian_push
from mcp_server._shared import mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def compliance_mapping() -> dict:
    """[READ][risk=low] 《工控系统网络安全防护指南》 ↔ iaiops governance mapping.

    An honest onboarding/sales self-assessment across the pillars 分区隔离 / 可审计 /
    双向认证 / 最小权限 / 数据保护 / 自主可控. Each control names how iaiops addresses
    it, an honest status (addressed / partial / 待核实), and the remaining gap.

    Returns dict: {framework, frameworks[], pillars[], control_count, status_summary
        {addressed, partial, 待核实}, controls:[{pillar, requirement, iaiops, status,
        gap, crosswalk{dengbao, iec62443}}]}. See compliance_frameworks for the full
        cross-framework 对照.

    Example: compliance_mapping().
    """
    return _compliance_mapping()


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def compliance_frameworks() -> dict:
    """[READ][risk=low] 跨框架对照: 防护指南 ↔ 等保 2.0 (GB/T 22239) ↔ IEC 62443.

    One row per governance pillar, showing the matching 《工控系统网络安全防护指南》
    requirement, 等保 2.0 control class, IEC 62443 foundational requirement, and the
    current iaiops status. Companion to compliance_mapping (which carries the honest
    per-control gap); use this to answer "which 等保 / 62443 clause does this satisfy".

    Returns dict: {frameworks:[{id,name,region,kind}], framework_count, pillar_count,
        crosswalk:[{pillar, gjzn, dengbao, iec62443, iaiops_status}], note}.

    Example: compliance_frameworks().
    """
    return _compliance_frameworks()


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def historian_push(
    points: list,
    sink: str,
    host: str = "localhost",
    port: int = 0,
    user: str = "",
    password: str = "",
    database: str = "",
) -> dict:
    """[WRITE→historian][risk=low] Push collected telemetry to a national TSDB.

    Writes already-collected points to a domestic historian (信创) — TDengine or
    IoTDB — instead of binding InfluxDB. Data egress to the operator's OWN database,
    NOT a control-system write. Non-numeric points are skipped (numeric value column).

    Args:
        points: Collected points — {ref|metric, value|present_value, timestamp?, ...}
            (e.g. the output of interrogate / integrity_poll / read_points / monitor).
        sink: 'tdengine' or 'iotdb'.
        host/port/user/password: TSDB connection params (sensible defaults per sink
            when blank/0).
        database: Target database (TDengine db / IoTDB storage group, e.g. 'root.iaiops').

    Returns dict: {sink, received, written, skipped_non_numeric, database}.

    Example: historian_push(points=[{"ref":"line1.temp","value":21.5}], sink="tdengine",
        host="10.0.0.20", database="iaiops").
    """
    opts: dict = {"host": host}
    if port:
        opts["port"] = port
    if user:
        opts["user"] = user
    if password:
        opts["password"] = password
    if database:
        opts["database"] = database
    return _historian_push(points, sink, **opts)
