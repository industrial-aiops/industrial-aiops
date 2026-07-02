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
        "via IAIOPS_MCP (e.g. IAIOPS_MCP=building exposes only that zone's protocols); "
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
        "sanitization of device-returned text. 'iaiops audit forward' streams new "
        "records as JSON lines to a syslog (UDP) or HTTP SIEM collector, with a "
        "persisted since-cursor so re-runs never duplicate.",
        "status": "addressed",
        "gap": "Forwarding is best-effort/at-least-once: syslog UDP and per-line "
        "HTTP POST have no delivery ACK, and TLS-syslog / Kafka sinks are 待核实 / "
        "roadmap — pair with a collector on a trusted segment.",
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
        "iaiops": "Encrypted secret store (secrets.enc, Fernet + scrypt); config "
        "directory permission warnings (700); master password via "
        "IAIOPS_MASTER_PASSWORD for non-interactive/MCP use; 'iaiops secret rotate' "
        "re-encrypts the whole store under a new master password (decrypt old → "
        "re-encrypt new); secrets never logged or printed.",
        "status": "addressed",
        "gap": "Master-password rotation is operator-driven (no HSM/KMS-backed keys "
        "or automatic scheduled rotation).",
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

# Cross-framework 对照: the 等保 2.0 (GB/T 22239-2019) control class and the IEC
# 62443 foundational requirement that each 防护指南 pillar maps onto. Lets an
# onboarding/audit engineer see the same governance control across all three
# frameworks. Keyed by the exact CONTROLS[].pillar string.
_CROSSWALK: dict[str, dict[str, str]] = {
    "分区隔离 (zoning / isolation)": {
        "dengbao": "安全通信网络·网络架构 / 安全区域边界·边界防护·访问控制",
        "iec62443": "FR5 受限数据流 (RDF) — zones & conduits (IEC 62443-3-2 / -3-3 SR 5.x)",
    },
    "可审计 (auditability)": {
        "dengbao": "安全计算环境·安全审计 + 安全管理中心·集中管控",
        "iec62443": "FR6 事件及时响应 (TRE) — auditable events (SR 2.8–2.12)",
    },
    "双向认证 (mutual authentication)": {
        "dengbao": "安全计算环境·身份鉴别 / 安全通信网络·通信传输(加密)",
        "iec62443": "FR1 标识与鉴别控制 (IAC) — SR 1.1–1.9",
    },
    "最小权限 (least privilege)": {
        "dengbao": "安全计算环境·访问控制 (最小权限·权限分离)",
        "iec62443": "FR2 使用控制 (UC) — 授权强制 / 最小权限 (SR 2.1)",
    },
    "数据保护 (data protection)": {
        "dengbao": "安全计算环境·数据保密性 / 数据完整性",
        "iec62443": "FR4 数据保密性 (DC) — SR 4.1–4.3",
    },
    "供应链 / 自主可控 (supply-chain / domestic substitutability)": {
        "dengbao": "安全建设管理·产品采购和使用 (信创 自主可控)",
        "iec62443": "FR3 系统完整性 (SI) + IEC 62443-4-1 安全开发生命周期 / 组件来源",
    },
}

# 等保 2.0 (GB/T 22239-2019) is a GRADED scheme: the same control class tightens as
# the level rises. Most 工控 critical systems target 三级 (第三级). For each governance
# pillar this records the 二级 baseline, what 三级 ADDITIONALLY requires, and — honestly
# — how far iaiops moves you toward 三级 (the per-control gap/status lives in CONTROLS).
# Keyed by the exact CONTROLS[].pillar string. Onboarding aid, NOT a certification.
DENGBAO_LEVELS: dict[str, dict[str, str]] = {
    "分区隔离 (zoning / isolation)": {
        "l2": "划分安全区域并在区域边界部署访问控制设备 (基于地址/端口的包过滤)。",
        "l3": "关键区域与其他网络之间采用可靠技术隔离 (工控网↔管理网单向隔离/网闸或等效)；"
        "访问控制细化到应用协议/会话级；严格管控无线/拨号等旁路接入。",
        "iaiops": "Read-first 单向数据 tap；按区域最小暴露 (IAIOPS_MCP 只开该区协议)；"
        "connector 不在端点间桥接/路由。物理隔离/网闸部署两级都仍由运维负责。",
    },
    "可审计 (auditability)": {
        "l2": "对重要用户行为与安全事件审计；审计记录含时间/主体/事件/结果并防增删改。",
        "l3": "额外要求安全管理中心·集中管控：审计记录集中收集与分析、留存≥6个月、"
        "审计进程受保护并可对异常实时报警。",
        "iaiops": "Append-only SQLite 审计 + 预算熔断满足留痕/防篡改(基础)；三级的集中管控/"
        "SIEM 转发/≥6个月留存需外部对接 (导出或外部 tail)。",
    },
    "双向认证 (mutual authentication)": {
        "l2": "口令身份鉴别 + 复杂度与登录失败处理。",
        "l3": "额外要求两种及以上组合鉴别 (双因素，且含不可伪造因素)；远程管理/网络设备"
        "采用加密防鉴别信息窃听；通信过程的完整性与保密性 (加密)。",
        "iaiops": "OPC-UA/MQTT 凭据 + 加密 secret store；三级的双因素与全链路双向 TLS/证书"
        "为 待核实/roadmap；多数 OT 传输本身无认证 → 依赖分区隔离补偿。",
    },
    "最小权限 (least privilege)": {
        "l2": "账户按最小权限分配；处置默认账户/口令；及时清理多余账户。",
        "l3": "额外要求基于安全标记的强制访问控制；特权权限分离 (系统/审计/安全三权分立)；"
        "关键操作双人/审批。",
        "iaiops": "Read-first + 写操作 HIGH risk_tier (dry-run+双确认+记录审批 MOC) 覆盖关键"
        "操作审批；三级的强制访问控制/三权分立 (per-user RBAC/角色分离) 委托宿主/MCP 客户端。",
    },
    "数据保护 (data protection)": {
        "l2": "鉴别信息与重要数据的传输/存储保密性；重要数据可备份恢复。",
        "l3": "额外要求以密码技术保证重要数据 (鉴别/业务/审计) 存储与传输的完整性与保密性；"
        "本地+异地备份恢复；剩余信息保护。",
        "iaiops": "加密 secret store (Fernet+scrypt)、secrets 不落日志；业务遥测完整性校验/"
        "异地备份/剩余信息清除为 待核实；密钥管理手动 (无 HSM/KMS)。",
    },
    "供应链 / 自主可控 (supply-chain / domestic substitutability)": {
        "l2": "采购渠道可控；使用正版且受支持的组件。",
        "l3": "额外要求关键设备/安全产品通过国家认证或选用国产可控；具备离线/自主运维能力；"
        "供应链来源与完整性验证。",
        "iaiops": "纯 Python core + 按需 extras + 离线 wheel 安装 + 国产 TSDB (TDengine/IoTDB)；"
        "国产 OS/芯/PLC 验证为 待核实 (见 docs/CHINA.md)。",
    },
}

_DENGBAO_LEVEL_META: tuple[dict, ...] = (
    {"id": "l2", "name": "第二级 (S2A2G2 系统审计保护级)",
     "note": "一般商用/非关键系统的常见目标。"},
    {"id": "l3", "name": "第三级 (S3A3G3 安全标记保护级)",
     "note": "工控关键信息基础设施的常见强制目标。"},
)

# Accepts l2/l3, 二级/三级, 2/3, level2/level3 — normalized to 'l2'/'l3'.
_DENGBAO_LEVEL_ALIASES: dict[str, str] = {
    "l2": "l2", "2": "l2", "二级": "l2", "二": "l2", "level2": "l2", "s2a2g2": "l2",
    "l3": "l3", "3": "l3", "三级": "l3", "三": "l3", "level3": "l3", "s3a3g3": "l3",
}


def _normalize_dengbao_level(level: str | None) -> str | None:
    """Map a user-supplied level string to 'l2'/'l3', or None for 'both'."""
    if level is None:
        return None
    key = str(level).strip().lower()
    if not key:
        return None
    resolved = _DENGBAO_LEVEL_ALIASES.get(key)
    if resolved is None:
        known = "l2/l3, 二级/三级, 2/3"
        raise ValueError(f"Unknown 等保 level {level!r}. Use one of: {known}.")
    return resolved


# The frameworks iaiops maps its governance posture onto.
FRAMEWORKS: tuple[dict, ...] = (
    {"id": "gjzn", "name": "《工控系统网络安全防护指南》",
     "region": "CN · 工信部", "kind": "指南 / guidance"},
    {"id": "dengbao", "name": "网络安全等级保护 2.0 (GB/T 22239-2019)",
     "region": "CN · 强制分级", "kind": "graded scheme"},
    {"id": "iec62443", "name": "IEC 62443 (IACS 工控信息安全)",
     "region": "international", "kind": "标准 / standard"},
)


def compliance_mapping() -> dict:
    """[READ] 《工控系统网络安全防护指南》 ↔ iaiops governance mapping (honest status).

    Each control now also carries a ``crosswalk`` to the matching 等保 2.0 control
    class and IEC 62443 foundational requirement (see ``compliance_frameworks``).
    """
    rows = sorted(CONTROLS, key=lambda c: _STATUS_ORDER.get(c["status"], 3))
    rows = [{**c, "crosswalk": _CROSSWALK.get(c["pillar"], {})} for c in rows]
    summary = {s: sum(1 for c in CONTROLS if c["status"] == s)
               for s in ("addressed", "partial", "待核实")}
    return {
        "framework": "《工控系统网络安全防护指南》(industrial control system "
        "cybersecurity protection guidance)",
        "frameworks": [f["id"] for f in FRAMEWORKS],
        "pillars": ["分区隔离", "可审计", "双向认证", "最小权限", "数据保护", "自主可控"],
        "control_count": len(CONTROLS),
        "status_summary": summary,
        "controls": rows,
        "note": "Honest self-assessment for onboarding/sales, not a certification. "
        "'待核实' = documented but not yet validated. Each control maps across "
        "防护指南 / 等保 2.0 / IEC 62443 (see compliance_frameworks). See docs/CHINA.md "
        "for the 信创 (offline install / 国产 OS·芯·PLC validation) details.",
    }


def compliance_frameworks() -> dict:
    """[READ] 跨框架对照: 防护指南 ↔ 等保 2.0 ↔ IEC 62443, one row per pillar."""
    crosswalk = []
    for c in CONTROLS:
        xw = _CROSSWALK.get(c["pillar"], {})
        crosswalk.append({
            "pillar": c["pillar"],
            "gjzn": c["requirement"],
            "dengbao": xw.get("dengbao", "待核实"),
            "iec62443": xw.get("iec62443", "待核实"),
            "iaiops_status": c["status"],
        })
    return {
        "frameworks": list(FRAMEWORKS),
        "framework_count": len(FRAMEWORKS),
        "pillar_count": len(crosswalk),
        "crosswalk": crosswalk,
        "note": "跨框架对照 (onboarding / 审计参考，非认证)。防护指南为主映射，"
        "等保 2.0 与 IEC 62443 为对照条款；逐项 gap / 状态见 compliance_mapping。",
    }


def compliance_dengbao_levels(level: str | None = None) -> dict:
    """[READ] 等保 2.0 二级 vs 三级 per-pillar deltas + honest iaiops posture.

    等保 2.0 is graded: the same control tightens with the level. For each governance
    pillar this shows the 二级 baseline, what 三级 additionally requires, and how far
    iaiops moves you toward it (per-control status/gap from CONTROLS). Pass ``level``
    (l2/l3, 二级/三级, 2/3) to focus on one level; omit for both. Onboarding aid, not
    a certification.
    """
    selected = _normalize_dengbao_level(level)
    status_by_pillar = {c["pillar"]: c for c in CONTROLS}
    deltas = []
    for pillar, spec in DENGBAO_LEVELS.items():
        control = status_by_pillar.get(pillar, {})
        row = {
            "pillar": pillar,
            "iaiops": spec["iaiops"],
            "iaiops_status": control.get("status", "待核实"),
            "gap": control.get("gap", ""),
        }
        if selected in (None, "l2"):
            row["l2_requires"] = spec["l2"]
        if selected in (None, "l3"):
            row["l3_adds"] = spec["l3"]
        deltas.append(row)
    levels = [m for m in _DENGBAO_LEVEL_META if selected in (None, m["id"])]
    return {
        "framework": "网络安全等级保护 2.0 (GB/T 22239-2019)",
        "levels": levels,
        "selected_level": selected,
        "pillar_count": len(deltas),
        "deltas": deltas,
        "note": "二级为基线，三级为在其之上的增量要求 (onboarding / 自评参考，非认证)。"
        "'待核实' = 已文档化但尚未验证；逐项 gap 见 compliance_mapping。工控关键系统"
        "通常以三级为目标。",
    }


__all__ = [
    "compliance_mapping",
    "compliance_frameworks",
    "compliance_dengbao_levels",
    "CONTROLS",
    "FRAMEWORKS",
    "DENGBAO_LEVELS",
]
