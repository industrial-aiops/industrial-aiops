"""The product mechanisms the NIS2 / CRA crosswalk is allowed to cite.

One registry, so a row cannot name a mechanism by prose alone. Every entry
carries ``anchors`` — where the mechanism lives — and
``tests/test_compliance_eu.py`` resolves each one (``py:`` = importable
``module:attr``; ``file:`` = repository file, optionally ``#`` a token it must
contain). A mechanism the code does not contain cannot be cited, which is the
stretch this registry exists to stop.

``fact`` states what the mechanism does *and its known limit*, in the same
sentence, because a fact without its limit is the flattering half of a fact.
"""

from __future__ import annotations

MECHANISMS: dict[str, dict] = {
    "audit_trail": {
        "name": "Governed audit trail",
        "fact": "Every MCP tool and every CLI command runs through @governed_tool and "
        "leaves an append-only row in ~/.iaiops/audit.db (tool, params with secrets "
        "redacted, result status, risk level, OS user, approver) — denied and failed "
        "calls included. There is no switch to turn it off.",
        "anchors": (
            "py:iaiops.core.governance:governed_tool",
            "py:iaiops.core.governance.audit:AuditEngine",
        ),
    },
    "audit_hash_chain": {
        "name": "Audit hash chain + `iaiops audit verify`",
        "fact": "Each audit row carries a SHA-256 chain (prev_hash/row_hash); "
        "`iaiops audit verify` walks it and reports the first break. Unkeyed: it "
        "detects an edited or deleted row, not an attacker who rewrites the whole "
        "suffix — forward the trail off-box for that.",
        "anchors": (
            "py:iaiops.core.governance.audit:AuditEngine.verify_chain",
            "py:iaiops.core.governance.audit:compute_row_hash",
        ),
    },
    "audit_forward": {
        "name": "`iaiops audit forward` (SIEM)",
        "fact": "Streams new audit rows as JSON lines to a syslog (UDP) or HTTP "
        "collector with a persisted cursor. Best-effort / at-least-once: no delivery "
        "acknowledgement.",
        "anchors": ("py:iaiops.core.governance.forward:build_sink",),
    },
    "evidence_bundle": {
        "name": "`iaiops compliance evidence` (evidence zip)",
        "fact": "Exports audit rows, the chain-verification result, rules.yaml and a "
        "non-probing doctor summary as one deterministic zip for an assessor.",
        "anchors": ("py:iaiops.core.governance.evidence:export_evidence_bundle",),
    },
    "approvals_moc": {
        "name": "Named approval tokens (MOC)",
        "fact": "High-risk calls need a recorded approver: `iaiops approve` issues a "
        "one-shot, TTL-bound token consumed by the next matching call and written to "
        "the audit row. The approver is a name, not an authenticated identity.",
        "anchors": (
            "py:iaiops.core.governance.approvals:record_approval",
            "py:iaiops.core.governance.approvals:consume_approval",
        ),
    },
    "dry_run_undo": {
        "name": "Dry-run default + undo",
        "fact": "Device-write tools default to dry_run=True (preview only); a real "
        "write captures the BEFORE value and registers an inverse. Where no inverse "
        "exists the undo says 'none' rather than inventing one.",
        "anchors": ("py:iaiops.core.governance.undo:UndoStore",),
    },
    "policy_engine": {
        "name": "Policy engine (rules.yaml)",
        "fact": "Deny rules, risk tiers and change limits from ~/.iaiops/rules.yaml, "
        "evaluated before a governed call runs; the kill switch never bypasses deny "
        "rules or approver tiers for high/critical calls.",
        "anchors": ("py:iaiops.core.governance.policy:PolicyEngine",),
    },
    "budget_breaker": {
        "name": "Call budget + runaway circuit-breaker",
        "fact": "Per-process call/token budget and a breaker that trips when the same "
        "(tool, params) repeats past a threshold, bounding the load an agent can put "
        "on plant devices.",
        "anchors": ("py:iaiops.core.governance.budget:BudgetTracker",),
    },
    "sanitize": {
        "name": "Device-text sanitisation",
        "fact": "Text returned by devices is sanitised and length-bounded before it "
        "reaches a model, against prompt injection through device strings.",
        "anchors": ("py:iaiops.core.governance.sanitize:sanitize",),
    },
    "no_egress_gate": {
        "name": "IAIOPS_NO_EGRESS posture gate",
        "fact": "IAIOPS_NO_EGRESS=1 withholds every tool declared egress=True at "
        "registration, so the server cannot ship data off-box. Opt-in, not default.",
        "anchors": ("py:mcp_server.noegress:apply_no_egress",),
    },
    "mcp_profiles": {
        "name": "Menu-selected MCP surface (IAIOPS_MCP) + stdio default",
        "fact": "IAIOPS_MCP selects only the protocols a site needs, so unused "
        "connectors are not exposed; the server speaks stdio by default and opens a "
        "network listener only when IAIOPS_MCP_TRANSPORT asks for one.",
        "anchors": (
            "py:mcp_server.profiles:resolve_selection",
            "file:mcp_server/server.py#IAIOPS_MCP_TRANSPORT",
        ),
    },
    "secret_store": {
        "name": "Encrypted secret store",
        "fact": "Credentials live in ~/.iaiops/secrets.enc (Fernet, scrypt-derived "
        "key), never in plaintext config; `iaiops secret rotate` re-encrypts under a "
        "new master password, `iaiops secret rm` deletes one. No HSM/KMS.",
        "anchors": (
            "py:iaiops.core.runtime.secretstore:SecretStore",
            "py:iaiops.core.runtime.secretstore:SecretStore.delete",
        ),
    },
    "channel_tls": {
        "name": "OPC UA security mode / MQTT TLS",
        "fact": "OPC UA certificate security (policy/mode, client cert/key, optional "
        "server cert) and MQTT TLS (CA + client cert) are wired from config. Live "
        "validation against real gear is 待核实; Modbus, S7, MC, EtherCAT and other "
        "OT transports have no encryption to turn on.",
        "anchors": (
            "py:iaiops.connectors.opcua.transport:_build_opcua_client",
            "py:iaiops.connectors.sparkplug.transport:_build_mqtt_client",
        ),
    },
    "param_redaction": {
        "name": "Sensitive-parameter redaction",
        "fact": "Parameters a tool declares sensitive (passwords, tokens) are redacted "
        "before the audit row is written.",
        "anchors": ("file:iaiops/core/governance/decorators.py#sensitive_params",),
    },
    "scan_bounds": {
        "name": "Bounded site survey (`iaiops scan`)",
        "fact": "Read-only survey over an industrial-port allowlist with a "
        "zero-packet preview of its worst-case duration; a source guard asserts the "
        "discovery layer has no write path.",
        "anchors": (
            "py:iaiops.core.discovery.ports:sweepable_ports",
            "py:iaiops.core.discovery.preview:plan_preview",
            "py:iaiops.core.discovery.guard:assert_no_write_path",
        ),
    },
    "asset_inventory": {
        "name": "Asset inventory",
        "fact": "Fingerprints the endpoints iaiops is configured to reach (reads each "
        "device's identity where the protocol exposes one). Active, not passive: it "
        "finds only what it is pointed at.",
        "anchors": ("py:iaiops.core.brain.asset_inventory:asset_inventory",),
    },
    "store_prune": {
        "name": "`iaiops store prune` (retention)",
        "fact": "Prunes collected history by retention rule. It does not touch the "
        "audit trail, which is append-only by design.",
        "anchors": ("py:iaiops.cli.store:store_prune_cmd",),
    },
    "self_assessment": {
        "name": "Self-assessment crosswalk + report",
        "fact": "This crosswalk and `iaiops compliance report`: a per-item statement "
        "of which mechanism is relevant and what remains, gaps included.",
        "anchors": ("py:iaiops.core.brain.compliance_report:render_markdown_report",),
    },
    "verify_determinism": {
        "name": "`iaiops verify determinism`",
        "fact": "Runs a pinned dataset through the analysis layers in fresh "
        "interpreters with the network blocked and compares SHA-256 digests; exits 1 "
        "on disagreement, so it can be a test step.",
        "anchors": ("py:iaiops.cli.verify:determinism_cmd",),
    },
    "ci_gate": {
        "name": "Release quality gate (CI)",
        "fact": "Every change runs pytest, ruff and bandit (zero Medium+ findings) in "
        "CI. No dependency-vulnerability scan, fuzzing or third-party review is part "
        "of it.",
        "anchors": ("file:.github/workflows/ci.yml#bandit",),
    },
    "locked_deps": {
        "name": "Locked dependency graph",
        "fact": "uv.lock pins the full resolved dependency graph with hashes; each "
        "connector declares its library pin (docs/HLD.md §5). A lockfile, not an SBOM.",
        "anchors": ("file:uv.lock",),
    },
    "signed_images": {
        "name": "cosign-signed container images",
        "fact": "Release container images and the Margo application package are "
        "cosign-signed; the public key ships at deploy/margo/cosign.pub. Whether the "
        "PyPI wheel carries a signature or attestation is 待核实.",
        "anchors": (
            "file:.github/workflows/publish-image.yml#cosign sign",
            "file:deploy/margo/cosign.pub",
        ),
    },
    "container_hardening": {
        "name": "Hardened container profile",
        "fact": "The edge image runs non-root on a read-only root filesystem with "
        "state on one volume; CI checks both.",
        "anchors": (
            "file:deploy/margo/compose.yaml#read_only: true",
            "file:deploy/margo/Dockerfile#Non-root",
        ),
    },
    "changelog": {
        "name": "Per-release CHANGELOG",
        "fact": "Every release lists its fixes in CHANGELOG.md. It describes defects; "
        "it is not a vulnerability advisory (no identifiers, no severity).",
        "anchors": ("file:CHANGELOG.md#Unreleased",),
    },
    "free_distribution": {
        "name": "MIT licence, public distribution",
        "fact": "Releases are published free of charge under the MIT licence (PyPI, "
        "GitHub, container registry).",
        "anchors": ("file:LICENSE#MIT License",),
    },
}


__all__ = ["MECHANISMS"]
