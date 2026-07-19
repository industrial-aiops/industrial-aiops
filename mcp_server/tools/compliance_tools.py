"""信创 / compliance + national-TSDB MCP tools (always exposed).

``compliance_mapping`` is a read-only self-assessment against 《工控系统网络安全防护
指南》. ``historian_push`` writes already-collected telemetry to a domestic
time-series DB (TDengine / IoTDB) — data egress to the operator's OWN historian
(low-risk, governed), not a control-system write. The TSDB client libraries are
optional extras (``iaiops[tdengine]`` / ``iaiops[iotdb]``) imported lazily.
"""

from datetime import UTC, datetime
from typing import Any, Optional

from iaiops.core.brain.compliance import compliance_dengbao_levels as _compliance_dengbao_levels
from iaiops.core.brain.compliance import compliance_frameworks as _compliance_frameworks
from iaiops.core.brain.compliance import compliance_mapping as _compliance_mapping
from iaiops.core.brain.compliance_report import render_markdown_report as _render_markdown_report
from iaiops.core.governance import governed_tool
from iaiops.core.governance.evidence import export_evidence_bundle as _export_evidence_bundle
from iaiops.core.governance.evidence import validate_output_path as _validate_output_path
from iaiops.core.runtime.envelope import envelope_fields
from iaiops.core.sink.push import historian_push as _historian_push
from mcp_server._shared import mcp, tool_errors

# Inline-response bound for compliance_report: above this the markdown must be
# written to a file (out_path) instead of flooding the MCP response.
_MAX_INLINE_LINES = 400


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
def compliance_dengbao_levels(level: Optional[str] = None) -> dict:
    """[READ][risk=low] 等保 2.0 二级 vs 三级 per-pillar deltas + honest iaiops posture.

    等保 2.0 (GB/T 22239) is graded — the same control tightens as the level rises.
    Per governance pillar this shows the 二级 baseline, what 三级 additionally requires,
    and how far iaiops moves you toward it (with the honest per-control status/gap).
    An onboarding/self-assessment aid, NOT a certification.

    Args:
        level: Focus on one level — 'l2'/'l3', '二级'/'三级', or '2'/'3'. Omit for both.

    Returns dict: {framework, levels:[{id,name,note}], selected_level, pillar_count,
        deltas:[{pillar, l2_requires?, l3_adds?, iaiops, iaiops_status, gap}], note}.

    Example: compliance_dengbao_levels(level="三级").
    """
    return _compliance_dengbao_levels(level)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def compliance_report(
    level: Optional[str] = None,
    site: str = "",
    out_path: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Render the 等保 2.0 / IEC 62443 compliance report (Markdown).

    Turns the compliance crosswalk into a deliverable document a CISO can read:
    title-page metadata (site / date / iaiops version), per-pillar 等保 L2/L3 status
    table, IEC 62443 FR1–6 crosswalk, honest gap list, and a governance-controls
    appendix (audit hash chain / approval tokens / dry-run+undo / mTLS). An
    onboarding/self-assessment aid, NOT a certification.

    Args:
        level: 等保 2.0 target level — 'l2'/'l3', '二级'/'三级', '2'/'3'. Omit for both.
        site: Site / plant name stamped on the title page.
        out_path: Optional file to write the markdown to (.md). Required when the
            report exceeds the inline bound (~400 lines): without it the inline
            markdown is truncated with a note.

    Returns dict: {format, level, line_count, path?} plus either the full inline
        {markdown} (when within bounds and no out_path) or {markdown (truncated),
        truncated: true} with a hint to pass out_path.

    Example: compliance_report(level="三级", site="示例水厂",
        out_path="/tmp/compliance-report.md").
    """
    markdown = _render_markdown_report(
        site=site, date=datetime.now(tz=UTC).date().isoformat(), level=level
    )
    line_count = markdown.count("\n") + 1
    result: dict = {"format": "markdown", "level": level, "line_count": line_count}
    # "Items" here are markdown LINES; the envelope contract is unchanged —
    # how many came back, how many exist, was anything cut.
    if out_path:
        path = _validate_output_path(out_path, suffixes=(".md", ".markdown"))
        path.write_text(markdown, encoding="utf-8")
        # Full document on disk: nothing was cut.
        return {
            **result,
            "path": str(path),
            **envelope_fields(returned=line_count, total=line_count),
        }
    if line_count > _MAX_INLINE_LINES:
        head = "\n".join(markdown.split("\n")[:_MAX_INLINE_LINES])
        return {
            **result,
            "markdown": head,
            "truncated": True,  # legacy bool — see `is_truncated`
            "hint": f"Report exceeds {_MAX_INLINE_LINES} lines inline — pass "
            "out_path to write the full document to a file.",
            **envelope_fields(returned=_MAX_INLINE_LINES, total=line_count),
        }
    return {
        **result,
        "markdown": markdown,
        **envelope_fields(returned=line_count, total=line_count),
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def compliance_evidence_bundle(
    out_path: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict:
    """[READ][risk=low] Export the audit-evidence bundle (zip) for an auditor.

    Packages the governance evidence trail into one deterministic zip:
    audit_rows.jsonl (secrets already redacted upstream), chain_verification.json
    (SHA-256 hash-chain walk result), rules.yaml (if present), doctor_summary.json
    (non-probing config/secret-store facts), and manifest.json. Path is validated
    (no '..' traversal; parent created 0700).

    Args:
        out_path: Destination zip path (must end in .zip).
        since: Optional ISO-8601 floor on the audit row timestamp (inclusive).
        until: Optional ISO-8601 ceiling on the audit row timestamp (inclusive).

    Returns dict: {path, row_count, chain{ok, checked, unhashed, ...}, files[],
        since, until}.

    Example: compliance_evidence_bundle(out_path="/tmp/evidence.zip",
        since="2026-06-01T00:00:00+00:00").
    """
    return _export_evidence_bundle(out_path, since=since, until=until)


# egress=True: this is THE case that motivates a second gate. It is risk_level
# "low" — it changes no plant state — so IAIOPS_READ_ONLY keeps it, yet it ships
# collected telemetry to a TSDB at a caller-supplied host. The underlying
# ``historian_push`` also accepts the LOCAL 'sqlite' sink, but the gate withholds
# the tool as a whole: policing the ``sink`` argument at call time is precisely
# the call-time refusal this design rejects (a weak model picks the argument).
@mcp.tool()
@governed_tool(risk_level="low", egress=True)
@tool_errors("dict")
def historian_push(
    points: list[dict[str, Any]],
    sink: str,
    host: str = "localhost",
    port: int = 0,
    user: str = "",
    password: str = "",
    database: str = "",
) -> dict:
    """[WRITE][risk=low][→historian] Push collected telemetry to a national TSDB.

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
