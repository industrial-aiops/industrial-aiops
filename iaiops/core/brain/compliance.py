"""信创 / 工控网络安全合规映射 — how iaiops maps to 《工控系统网络安全防护指南》.

A read-only, self-describing artifact (like ``protocols_supported``) that an agent
— or a sales/onboarding engineer — can read to see how the iaiops governance
posture lines up with the four pillars of China's industrial-control cybersecurity
guidance (分区隔离 / 可审计 / 双向认证 / 最小权限) plus data protection. Every row is
honest about ``status`` — ``addressed`` / ``partial`` / ``待核实`` — and names the
gap, so it is an onboarding checklist, not a marketing claim.

Pure data + a formatter; no external dependencies, fully testable.
"""

from __future__ import annotations

# Each control: the guidance pillar, what it requires, how iaiops addresses it, an
# honest status, and the remaining gap (empty when none).
CONTROLS: tuple[dict, ...] = (
    {
        "pillar": "分区隔离 (zoning / isolation)",
        "requirement": "Segment OT into security zones; restrict cross-zone access; "
        "no uncontrolled bridge between control and IT networks.",
        "iaiops": "Read-first single-purpose tap; per-site, per-protocol MCP exposure "
        "via IAIOPS_MCP (e.g. IAIOPS_MCP=energy exposes only that zone's protocols); "
        "connectors do not bridge or route between endpoints; no OT↔IT proxying.",
        "status": "addressed",
        "gap": "Deployment-time network zoning (firewall/diode placement) is the "
        "operator's responsibility — iaiops does not enforce it.",
    },
    {
        "pillar": "可审计 (auditability)",
        "requirement": "Log security-relevant operations with attribution; retain "
        "and review audit trails; detect anomalous activity.",
        "iaiops": "Every MCP tool runs through the governance harness: append-only "
        "SQLite audit log (~/.iaiops/audit.db), token/call budget with runaway "
        "circuit-breaker, undo-token records for any write, and prompt-injection "
        "sanitization of device-returned text.",
        "status": "addressed",
        "gap": "Audit forwarding to a central SIEM is not built in (export the DB / "
        "tail it externally).",
    },
    {
        "pillar": "双向认证 (mutual authentication)",
        "requirement": "Authenticate both endpoints; protect credentials; encrypt "
        "sensitive channels.",
        "iaiops": "OPC-UA username/password; MQTT TLS + credentials; secrets held in "
        "an encrypted store (Fernet + scrypt master password, ~/.iaiops/secrets.enc), "
        "never in plaintext config.",
        "status": "partial",
        "gap": "Full mutual TLS / certificate-based auth (OPC-UA cert security mode, "
        "MQTT client certs) is 待核实 / roadmap; several OT transports are "
        "natively unauthenticated (Modbus/S7/MC/EtherCAT) — defense is zoning.",
    },
    {
        "pillar": "最小权限 (least privilege)",
        "requirement": "Grant the minimum capability needed; separate read from "
        "control; gate change operations with approval.",
        "iaiops": "Read-first by design (the vast majority of tools are non-"
        "destructive, risk=low); the few write/command tools are HIGH risk_tier, "
        "off by default (dry_run=True), require a CLI double-confirm + a recorded "
        "approver (Management-of-Change), and capture the BEFORE value for undo; "
        "graduated-autonomy risk tiers via the policy engine.",
        "status": "addressed",
        "gap": "Per-user RBAC is delegated to the host/MCP client; iaiops enforces "
        "the risk-tier/MOC gate, not user identity.",
    },
    {
        "pillar": "数据保护 (data protection)",
        "requirement": "Protect stored credentials and sensitive configuration; "
        "fail safe on missing secrets.",
        "iaiops": "Encrypted secret store (secrets.enc); config directory permission "
        "warnings (700); master password via IAIOPS_AIOPS_MASTER_PASSWORD for "
        "non-interactive/MCP use; secrets never logged.",
        "status": "addressed",
        "gap": "Key management / rotation is manual (no HSM/KMS integration).",
    },
    {
        "pillar": "供应链 / 自主可控 (supply-chain / domestic substitutability)",
        "requirement": "Prefer controllable components; be able to run air-gapped; "
        "validate on 国产 OS/芯/PLC.",
        "iaiops": "Pure-Python core; per-protocol optional extras so only needed "
        "libraries are installed; offline/air-gapped wheel-bundle install supported; "
        "国产 PLC (汇川/台达/信捷) reachable over the existing Modbus/Ethernet paths; "
        "national TSDB sinks (TDengine / IoTDB) instead of binding InfluxDB.",
        "status": "待核实",
        "gap": "国产 OS (麒麟/统信) / 芯 (鲲鹏/海光) and 国产 PLC validation are "
        "documented but NOT yet hardware-verified — see docs/CHINA.md.",
    },
)

_STATUS_ORDER = {"addressed": 0, "partial": 1, "待核实": 2}


def compliance_mapping() -> dict:
    """[READ] 《工控系统网络安全防护指南》 ↔ iaiops governance mapping (honest status)."""
    rows = sorted(CONTROLS, key=lambda c: _STATUS_ORDER.get(c["status"], 3))
    summary = {s: sum(1 for c in CONTROLS if c["status"] == s)
               for s in ("addressed", "partial", "待核实")}
    return {
        "framework": "《工控系统网络安全防护指南》(industrial control system "
        "cybersecurity protection guidance)",
        "pillars": ["分区隔离", "可审计", "双向认证", "最小权限", "数据保护", "自主可控"],
        "control_count": len(CONTROLS),
        "status_summary": summary,
        "controls": list(rows),
        "note": "Honest self-assessment for onboarding/sales, not a certification. "
        "'待核实' = documented but not yet validated. See docs/CHINA.md for the "
        "信创 (offline install / 国产 OS·芯·PLC validation) details.",
    }


__all__ = ["compliance_mapping", "CONTROLS"]
