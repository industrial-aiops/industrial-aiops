"""NIS2 Art. 21 and CRA Annex I — product self-assessment crosswalks.

The 等保 / IEC 62443 / GxP crosswalk in ``compliance`` is organised by
governance pillar. The two European texts are organised by *their own* items,
because that is how an EU assessor reads them: NIS2 Article 21(2)(a)–(j) and
CRA Annex I Part I(1), Part I(2)(a)–(m) and Part II(1)–(8). Each item states:

* ``coverage`` — ``product_evidence`` (a cited mechanism produces evidence
  relevant to the measure; never that the measure is met), ``gap`` (a technical
  measure the product could speak to and does not), ``organisational`` (a
  process measure; the product provides no evidence), or ``待核实``;
* ``mechanisms`` — ids into ``compliance_eu_mechanisms.MECHANISMS``, each
  anchored in code and resolved by the tests;
* ``pillars`` — exact ``CONTROLS[].pillar`` strings, so the enterprise E1/E9
  report can attach this site's runtime evidence through the same key it
  already uses. Organisational rows carry none: runtime evidence printed under
  a measure the product never touches would be the flattering error.

Neither text obliges this product. NIS2 obliges essential and important
*entities*; the CRA obliges the *manufacturer* of a product with digital
elements. Pure data + selectors; no I/O.
"""

from __future__ import annotations

from iaiops.core.brain.compliance_eu_mechanisms import MECHANISMS

COVERAGE: tuple[str, ...] = ("product_evidence", "gap", "organisational", "待核实")

_AUDIT = "可审计 (auditability)"
_LEAST = "最小权限 (least privilege)"
_DATA = "数据保护 (data protection)"
_AUTH = "双向认证 (mutual authentication)"
_ZONE = "分区隔离 (zoning / isolation)"

_ORG = "Organisational measure — product provides no evidence."

EU_DISCLAIMER = (
    "Product self-assessment, not a certification and not legal advice. NIS2 "
    "(Directive (EU) 2022/2555) obliges essential and important entities — the "
    "operator — not the products they use; the CRA (Regulation (EU) 2024/2847) "
    "obliges the manufacturer of a product with digital elements. Each row names "
    "the iaiops mechanism whose output is relevant evidence and what it leaves "
    "uncovered; whether a measure is met is the entity's or the manufacturer's "
    "assessment, not this table's."
)

SOURCE_NOTE = (
    "Item wording is paraphrased from Directive (EU) 2022/2555 (OJ L 333, "
    "27.12.2022) and Regulation (EU) 2024/2847 (OJ L, 20.11.2024). It was "
    "cross-checked against reproductions of those texts because EUR-Lex refused "
    "automated retrieval — 待核实 against the Official Journal before quoting any "
    "item verbatim to an assessor."
)


def _item(
    id_: str,
    ref: str,
    measure: str,
    coverage: str,
    iaiops: str,
    gap: str = "",
    mechanisms: tuple[str, ...] = (),
    pillars: tuple[str, ...] = (),
) -> dict:
    return {
        "id": id_,
        "ref": ref,
        "measure": measure,
        "coverage": coverage,
        "iaiops": iaiops,
        "gap": gap,
        "mechanisms": mechanisms,
        "pillars": pillars,
    }


NIS2_ITEMS: tuple[dict, ...] = (
    _item(
        "nis2-21-2-a",
        "NIS2 Art. 21(2)(a)",
        "Policies on risk analysis and information system security.",
        "organisational",
        f"{_ORG} The asset inventory and this self-assessment's gap list are inputs a "
        "risk analysis can use; they are listed under (i) and (f), not counted here.",
    ),
    _item(
        "nis2-21-2-b",
        "NIS2 Art. 21(2)(b)",
        "Incident handling.",
        "organisational",
        f"{_ORG} iaiops has no security-incident detection, handling workflow or "
        "Art. 23 reporting. `iaiops case` / `investigate` record equipment faults, "
        "not cybersecurity incidents. The audit trail can be read during an "
        "investigation (see (f)).",
    ),
    _item(
        "nis2-21-2-c",
        "NIS2 Art. 21(2)(c)",
        "Business continuity (backup management, disaster recovery) and crisis management.",
        "organisational",
        f"{_ORG} Undo reverses a single device write; it is not backup or disaster "
        "recovery. `audit forward` copies the audit trail off-box, nothing else.",
    ),
    _item(
        "nis2-21-2-d",
        "NIS2 Art. 21(2)(d)",
        "Supply chain security, including the entity's relationships with its direct "
        "suppliers or service providers.",
        "organisational",
        f"{_ORG} For the entity's assessment of iaiops as one of its suppliers, the "
        "supplier facts (signed images, locked dependencies, no SBOM, no disclosure "
        "policy yet) are the CRA Part II rows.",
    ),
    _item(
        "nis2-21-2-e",
        "NIS2 Art. 21(2)(e)",
        "Security in network and information systems acquisition, development and "
        "maintenance, including vulnerability handling and disclosure.",
        "product_evidence",
        "Changes iaiops makes to OT systems are controlled and recorded: device writes "
        "default to dry-run, need a named approver, are checked against policy change "
        "limits, capture the BEFORE value for undo, and leave an audit row.",
        "Vulnerability handling and disclosure for the entity's systems is "
        "organisational. iaiops's own vulnerability handling has no disclosure policy "
        "yet (CRA Part II(5)).",
        ("dry_run_undo", "approvals_moc", "policy_engine", "audit_trail"),
        (_LEAST, _AUDIT),
    ),
    _item(
        "nis2-21-2-f",
        "NIS2 Art. 21(2)(f)",
        "Policies and procedures to assess the effectiveness of cybersecurity "
        "risk-management measures.",
        "product_evidence",
        "Checkable records an effectiveness review can test against: the audit chain "
        "verdict, the evidence zip, an executable determinism check, and this "
        "self-assessment.",
        "The assessment procedure itself is the entity's. The product supplies "
        "records, not the review.",
        ("audit_hash_chain", "evidence_bundle", "verify_determinism", "self_assessment"),
        (_AUDIT,),
    ),
    _item(
        "nis2-21-2-g",
        "NIS2 Art. 21(2)(g)",
        "Basic cyber hygiene practices and cybersecurity training.",
        "organisational",
        f"{_ORG}",
    ),
    _item(
        "nis2-21-2-h",
        "NIS2 Art. 21(2)(h)",
        "Policies and procedures on the use of cryptography and, where appropriate, encryption.",
        "product_evidence",
        "Credentials encrypted at rest; OPC UA and MQTT channels can run "
        "certificate-based TLS; the audit trail is SHA-256 chained (integrity, not "
        "secrecy).",
        "The cryptography policy is the entity's. Modbus, S7, MC, EtherCAT and other "
        "OT transports carry no encryption; the audit database and collected history "
        "are not encrypted at rest; no HSM/KMS.",
        ("secret_store", "channel_tls", "audit_hash_chain"),
        (_AUTH, _DATA),
    ),
    _item(
        "nis2-21-2-i",
        "NIS2 Art. 21(2)(i)",
        "Human resources security, access control policies and asset management.",
        "product_evidence",
        "Access control on what iaiops may do: risk tiers, policy deny rules, named "
        "approvals for writes. Asset management input: an active asset inventory of "
        "the endpoints iaiops reaches, and a bounded site survey.",
        "Human resources security is organisational — the product provides no "
        "evidence. Per-user identity and RBAC are delegated to the host / MCP client; "
        "the access-control policy itself is the entity's.",
        ("policy_engine", "approvals_moc", "asset_inventory", "scan_bounds"),
        (_LEAST,),
    ),
    _item(
        "nis2-21-2-j",
        "NIS2 Art. 21(2)(j)",
        "Multi-factor or continuous authentication, secured voice/video/text "
        "communications and secured emergency communication systems, where appropriate.",
        "gap",
        "Not provided by iaiops.",
        "No multi-factor or continuous authentication of iaiops users. Mutual TLS on "
        "OPC UA / MQTT authenticates a device channel, not a person. Voice, video, text "
        "and emergency communications are outside the product.",
    ),
)


CRA_ITEMS: tuple[dict, ...] = (
    _item(
        "cra-i-1-1",
        "CRA Annex I Part I(1)",
        "Designed, developed and produced to ensure an appropriate level of "
        "cybersecurity based on the risks.",
        "organisational",
        f"{_ORG} This rests on the manufacturer's cybersecurity risk assessment "
        "(Art. 13(2)); none has been published for iaiops.",
    ),
    _item(
        "cra-i-1-2-a",
        "CRA Annex I Part I(2)(a)",
        "Made available on the market without known exploitable vulnerabilities.",
        "product_evidence",
        "Each release passes a static security scan with zero Medium+ findings and "
        "ships a locked dependency graph.",
        "No dependency-vulnerability scan (e.g. OSV / pip-audit) in the gate; no "
        "published statement of known vulnerabilities.",
        ("ci_gate", "locked_deps"),
    ),
    _item(
        "cra-i-1-2-b",
        "CRA Annex I Part I(2)(b)",
        "Secure by default configuration, with the possibility to reset to the original state.",
        "product_evidence",
        "Defaults: read-first, device writes preview-only (dry_run=True) and "
        "approver-gated, stdio transport (no listener), non-root read-only container.",
        "IAIOPS_NO_EGRESS is opt-in, not the default. There is no reset-to-original command.",
        ("dry_run_undo", "approvals_moc", "mcp_profiles", "container_hardening"),
        (_LEAST,),
    ),
    _item(
        "cra-i-1-2-c",
        "CRA Annex I Part I(2)(c)",
        "Vulnerabilities can be addressed through security updates (automatic by "
        "default where applicable, with user notification and opt-out).",
        "product_evidence",
        "Updates ship as new releases on PyPI and as signed container images, each "
        "with a CHANGELOG entry.",
        "No automatic updates and no update notification; the operator pulls "
        "releases. No separate security-update channel.",
        ("signed_images", "changelog"),
    ),
    _item(
        "cra-i-1-2-d",
        "CRA Annex I Part I(2)(d)",
        "Protection from unauthorised access by appropriate control mechanisms, and "
        "reporting on possible unauthorised access.",
        "product_evidence",
        "What a caller may do is gated by risk tier, policy deny rules and named "
        "approvals; credentials are encrypted; denied calls are written to the audit "
        "trail.",
        "Caller identity is not authenticated by iaiops (delegated to the host / MCP "
        "client). Denied calls are recorded, not alerted on, unless the trail is "
        "forwarded to a SIEM that alerts.",
        ("policy_engine", "approvals_moc", "secret_store", "audit_trail"),
        (_LEAST, _AUDIT),
    ),
    _item(
        "cra-i-1-2-e",
        "CRA Annex I Part I(2)(e)",
        "Protect the confidentiality of stored, transmitted or otherwise processed "
        "data (e.g. encryption at rest and in transit).",
        "product_evidence",
        "Credentials encrypted at rest; OPC UA / MQTT TLS in transit where configured; "
        "secrets redacted from audit rows.",
        "Audit database and collected history are not encrypted at rest. Most OT "
        "transports have no encryption to turn on.",
        ("secret_store", "channel_tls", "param_redaction"),
        (_DATA, _AUTH),
    ),
    _item(
        "cra-i-1-2-f",
        "CRA Annex I Part I(2)(f)",
        "Protect the integrity of stored, transmitted or otherwise processed data, "
        "commands, programs and configuration, and report on corruptions.",
        "product_evidence",
        "The audit trail is hash-chained and `iaiops audit verify` reports the first "
        "break; the evidence zip carries the verdict.",
        "The chain is unkeyed (a full-suffix rewrite is not detected without an "
        "off-box copy). Integrity of collected history and of config.yaml is not "
        "protected — 待核实. Corruption is reported when verify is run, not "
        "automatically.",
        ("audit_hash_chain", "evidence_bundle"),
        (_AUDIT,),
    ),
    _item(
        "cra-i-1-2-g",
        "CRA Annex I Part I(2)(g)",
        "Process only data that are adequate, relevant and limited to the intended "
        "purpose (data minimisation).",
        "product_evidence",
        "Sensitive parameters are redacted before audit; collected history is pruned "
        "by retention rule.",
        "Which tags are collected is the operator's configuration. Audit rows keep the "
        "OS user and approver names by design — personal data the audit purpose "
        "needs; whether that is minimal is the manufacturer's assessment.",
        ("param_redaction", "store_prune"),
        (_DATA,),
    ),
    _item(
        "cra-i-1-2-h",
        "CRA Annex I Part I(2)(h)",
        "Protect the availability of essential and basic functions, including "
        "resilience against denial-of-service attacks.",
        "gap",
        "No availability or denial-of-service resilience measure for iaiops itself is claimed.",
        "The default stdio transport opens no network listener; when the HTTP "
        "transport is enabled, its resilience is not assessed.",
    ),
    _item(
        "cra-i-1-2-i",
        "CRA Annex I Part I(2)(i)",
        "Minimise the negative impact on the availability of services provided by "
        "other devices or networks.",
        "product_evidence",
        "Load on plant devices is bounded: call budget and runaway breaker, bounded "
        "collection, port-allowlisted survey with a worst-case preview.",
        "Collection rates are operator-configured; the effect on fragile legacy "
        "devices is 待核实 per device.",
        ("budget_breaker", "scan_bounds"),
        (_ZONE,),
    ),
    _item(
        "cra-i-1-2-j",
        "CRA Annex I Part I(2)(j)",
        "Designed, developed and produced to limit attack surfaces, including external interfaces.",
        "product_evidence",
        "Only the protocols a site selects are exposed; stdio by default; egress tools "
        "can be withheld at registration; minimal container.",
        "IAIOPS_NO_EGRESS is opt-in. When the HTTP transport is enabled its "
        "authentication is delegated to whatever fronts it.",
        ("mcp_profiles", "no_egress_gate", "container_hardening"),
        (_ZONE,),
    ),
    _item(
        "cra-i-1-2-k",
        "CRA Annex I Part I(2)(k)",
        "Designed, developed and produced to reduce the impact of an incident using "
        "appropriate exploitation mitigation mechanisms and techniques.",
        "product_evidence",
        "A compromised or confused agent is contained: writes preview by default and "
        "need a named approver, an undo captures the prior state, device-returned "
        "text is sanitised, the container runs non-root and read-only.",
        "No memory-safety or sandboxing claim beyond the container. Some writes have "
        "no inverse (undo reports 'none').",
        ("dry_run_undo", "approvals_moc", "sanitize", "container_hardening"),
        (_LEAST,),
    ),
    _item(
        "cra-i-1-2-l",
        "CRA Annex I Part I(2)(l)",
        "Provide security-related information by recording and monitoring relevant "
        "internal activity (access to or modification of data, services or "
        "functions), with an opt-out mechanism for the user.",
        "product_evidence",
        "Every tool call and CLI command — reads, writes, denials, failures — is "
        "recorded in a hash-chained trail and can be streamed to a SIEM.",
        "No opt-out mechanism: the trail cannot be switched off, deliberately, so it "
        "stays tamper-evident. Whether that departure from the opt-out clause is "
        "acceptable is the manufacturer's assessment — 待核实.",
        ("audit_trail", "audit_hash_chain", "audit_forward"),
        (_AUDIT,),
    ),
    _item(
        "cra-i-1-2-m",
        "CRA Annex I Part I(2)(m)",
        "Users can securely and easily remove on a permanent basis all data and "
        "settings, and securely transfer data to other products where applicable.",
        "product_evidence",
        "Individual secrets can be deleted; collected history can be pruned.",
        "No single command removes all data and settings — that is deleting "
        "~/.iaiops by hand. The audit trail is append-only and cannot be removed from "
        "inside the product. No secure-transfer function.",
        ("secret_store", "store_prune"),
        (_DATA,),
    ),
    _item(
        "cra-i-2-1",
        "CRA Annex I Part II(1)",
        "Identify and document vulnerabilities and components, including a software "
        "bill of materials (SBOM) covering at least top-level dependencies.",
        "product_evidence",
        "The resolved dependency graph is locked in uv.lock; connectors declare their "
        "library pins.",
        "No SBOM in a commonly used machine-readable format (SPDX / CycloneDX) is "
        "published; uv.lock is a lockfile, not an SBOM. No vulnerability register.",
        ("locked_deps",),
    ),
    _item(
        "cra-i-2-2",
        "CRA Annex I Part II(2)",
        "Address and remediate vulnerabilities without delay, including by providing "
        "security updates (separately from functionality updates where feasible).",
        "product_evidence",
        "Fixes ship in regular releases and are listed per release in the CHANGELOG.",
        "No separate security-update channel and no stated remediation timeline.",
        ("changelog",),
    ),
    _item(
        "cra-i-2-3",
        "CRA Annex I Part II(3)",
        "Apply effective and regular tests and reviews of the security of the product.",
        "product_evidence",
        "Every change runs the CI gate (pytest, ruff, bandit 0 Medium+).",
        "No penetration test, fuzzing or independent security review.",
        ("ci_gate",),
    ),
    _item(
        "cra-i-2-4",
        "CRA Annex I Part II(4)",
        "Once a security update is available, share and publicly disclose information "
        "about fixed vulnerabilities (description, affected product, impact, "
        "severity, remediation).",
        "gap",
        "Not provided.",
        "No security advisories are published. The CHANGELOG describes defects, not "
        "vulnerabilities — no identifiers, severity or affected-version statements.",
    ),
    _item(
        "cra-i-2-5",
        "CRA Annex I Part II(5)",
        "Put in place and enforce a policy on coordinated vulnerability disclosure.",
        "gap",
        "Not provided.",
        "No coordinated vulnerability disclosure policy (no SECURITY.md).",
    ),
    _item(
        "cra-i-2-6",
        "CRA Annex I Part II(6)",
        "Facilitate sharing of information about potential vulnerabilities, including "
        "a contact address for reporting them.",
        "gap",
        "Not provided.",
        "No published security contact address.",
    ),
    _item(
        "cra-i-2-7",
        "CRA Annex I Part II(7)",
        "Provide mechanisms to securely distribute updates so exploitable "
        "vulnerabilities are fixed or mitigated in a timely manner.",
        "product_evidence",
        "Container images and the Margo package are cosign-signed with a published public key.",
        "Wheel signing / attestation on PyPI is 待核实. No automatic distribution.",
        ("signed_images",),
    ),
    _item(
        "cra-i-2-8",
        "CRA Annex I Part II(8)",
        "Security updates disseminated without delay and free of charge, with "
        "advisory messages on action to take.",
        "product_evidence",
        "Every release is free of charge under the MIT licence.",
        "No advisory messages accompany updates (see Part II(4)).",
        ("free_distribution", "changelog"),
    ),
)


FRAMEWORK_META: dict[str, dict] = {
    "nis2": {
        "id": "nis2",
        "name": "NIS2 — Directive (EU) 2022/2555, Art. 21(2)",
        "region": "EU · entities (operators)",
        "kind": "directive / risk-management measures",
        "obliges": "essential and important entities — not products",
        "applies": "Member-State transposition was due by 17 Oct 2024 and applies from "
        "18 Oct 2024 (Art. 41); national transposition varies — 待核实 per Member State.",
        "scope": "Measures the operator takes for its own network and information "
        "systems. iaiops is a system such an entity uses; rows say what evidence it "
        "produces for the entity's measure.",
    },
    "cra": {
        "id": "cra",
        "name": "CRA — Regulation (EU) 2024/2847, Annex I",
        "region": "EU · manufacturers",
        "kind": "regulation / essential cybersecurity requirements",
        "obliges": "the manufacturer of a product with digital elements",
        "applies": "Applies from 11 Dec 2027; Art. 14 reporting from 11 Sep 2026 (Art. 71(2)).",
        "scope": "Whether the free MIT edition is in CRA scope (commercial activity, "
        "open-source treatment) is 待核实 and not settled here; the commercial "
        "enterprise edition is more likely in scope — also 待核实. Rows describe iaiops "
        "as the product under assessment.",
    },
}

_ITEMS = {"nis2": NIS2_ITEMS, "cra": CRA_ITEMS}


def normalize_eu_framework(framework: str) -> str:
    """Map a user-supplied framework id to 'nis2' / 'cra', or raise ValueError."""
    key = str(framework).strip().lower().replace(" ", "").replace("-", "")
    if key not in _ITEMS:
        raise ValueError(f"Unknown EU framework {framework!r}. Use one of: nis2, cra.")
    return key


def refs_citing(framework: str, pillar: str) -> list[str]:
    """The item refs of ``framework`` that cite ``pillar`` (reverse index)."""
    return [i["ref"] for i in _ITEMS[framework] if pillar in i["pillars"]]


def compliance_eu(framework: str) -> dict:
    """[READ] NIS2 Art. 21 or CRA Annex I ↔ iaiops, item by item (honest coverage).

    Raises:
        ValueError: on a framework other than nis2 / cra.
    """
    fw = normalize_eu_framework(framework)
    items = [
        {
            **item,
            "mechanism_detail": [{"id": m, **MECHANISMS[m]} for m in item["mechanisms"]],
        }
        for item in _ITEMS[fw]
    ]
    summary = {c: sum(1 for i in items if i["coverage"] == c) for c in COVERAGE}
    meta = FRAMEWORK_META[fw]
    return {
        "framework": {k: meta[k] for k in ("id", "name", "region", "kind", "obliges")},
        "applies": meta["applies"],
        "scope": meta["scope"],
        "item_count": len(items),
        "coverage_summary": summary,
        "items": items,
        "disclaimer": EU_DISCLAIMER,
        "source": SOURCE_NOTE,
        "note": "'product_evidence' = a cited mechanism produces evidence relevant to "
        "the measure, never that the measure is met; every such row names what is "
        "left. 'organisational' rows cite nothing on purpose.",
    }


__all__ = [
    "COVERAGE",
    "CRA_ITEMS",
    "EU_DISCLAIMER",
    "FRAMEWORK_META",
    "MECHANISMS",
    "NIS2_ITEMS",
    "SOURCE_NOTE",
    "compliance_eu",
    "normalize_eu_framework",
    "refs_citing",
]
