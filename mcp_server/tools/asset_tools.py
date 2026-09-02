"""Active asset-inventory MCP tool (READ-ONLY, IEC 62443-flavored).

Non-destructive (risk_level='low'). Actively connects to each configured (or
named) endpoint and reads its identity to build an asset register. This is ACTIVE
fingerprinting via our clients — NOT passive SPAN/tap discovery (roadmap).
"""

from typing import Any, Optional

from iaiops.core.brain import asset_inventory as ops
from iaiops.core.governance import governed_tool
from mcp_server._shared import _manager, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def asset_inventory(endpoints: Optional[list[str]] = None) -> dict:
    """[READ][risk=low] Actively fingerprint endpoints into an asset register.

    Connects to each target with our own protocol client and reads its identity
    call (S7 CPU info, EtherNet/IP controller info, OPC-UA server build info,
    Modbus device identification FC43, Mitsubishi CPU type, MTConnect device
    model), aggregating vendor/model/firmware/serial per device.

    Honest scope: ACTIVE fingerprinting (we connect to each device), NOT passive
    SPAN/tap discovery. Only finds devices we are configured to reach.

    Args:
        endpoints: Endpoint names to fingerprint; omit to fingerprint ALL
            configured endpoints.

    Returns dict: {asset_count, reachable_count, unreachable_count, method:
        'active_fingerprint', assets:[{endpoint, protocol, address, vendor, model,
        firmware, serial, reachable, last_seen, error}]}.

    Example: asset_inventory(endpoints=["press1","cell5"]).
    """
    mgr = _manager()
    names = endpoints if endpoints else mgr.list_targets()
    targets = [mgr.target(n) for n in names]
    return ops.asset_inventory(targets)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def device_advisory_check(
    devices: list[dict[str, Any]],
    library_path: str,
) -> dict:
    """[READ][risk=low] Which scanned devices fall inside a mounted advisory's stated range.

    `iaiops scan` already reads vendor / model / firmware / serial and then does
    nothing with them. This closes that loop — and deliberately stops short of
    where a vulnerability scanner would go.

    **It reports that a device falls inside an advisory's stated range. Nothing
    more.** Not "vulnerable", not "exploitable", no severity score. Whether a
    published issue is reachable on a particular machine depends on
    configuration, network position and compensating controls that a read-only
    scan cannot see — and in OT most advisories against a protocol stack are not
    findings at all, because the stack is not reachable from anywhere that
    matters. A report full of red text that ignores that gets switched off by the
    site, and then the real one is missed too.

    **No database ships with this.** A bundled CVE feed is a maintenance
    commitment this repo has not made, and a stale one that looks current is
    worse than none — so the library is a file the site controls, which also
    makes it work air-gapped. Every entry must carry a source, and one bad entry
    refuses the whole file rather than half-mounting it.

    Four verdicts, and the middle two are the point: `in_affected_range`,
    `version_unknown` (model matches, no firmware read — neither a hit nor a
    pass), `version_unparsed` (a firmware string it will not invent an ordering
    for), `not_affected`. A device no advisory mentions is **absent** from the
    findings, not reported clean: "nothing known" is not "nothing there".

    Args:
        devices: [{ip?, vendor, model, firmware?}] — e.g. the `hosts` of a scan.
        library_path: Path to the advisory file (YAML or JSON) this site mounted;
            entries are {id, vendor, model, source, affected_below|affected_from|
            affected_versions, title?}.

    Returns dict: {devices_checked, advisories_mounted, devices_with_findings,
        summary:{in_affected_range, version_unparsed, version_unknown,
        not_affected}, findings:[{ip, vendor, model, firmware, advisory_id, title,
        source, status, detail}], truncated, advisory_note, note}.

    Example: device_advisory_check(devices=[{"ip":"10.0.0.5","vendor":"Siemens",
        "model":"S7-1500","firmware":"2.8.1"}], library_path="~/advisories.yaml").
    """
    from iaiops.core.brain.device_advisories import load_advisories, match_devices

    return match_devices(devices, load_advisories(library_path))
