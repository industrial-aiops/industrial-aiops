"""The product mechanisms the NIS2 / CRA crosswalk is allowed to cite.

One registry, so a row cannot name a mechanism by prose alone. Every entry
carries ``anchors`` — where the mechanism lives — and
``tests/test_compliance_eu.py`` resolves each one (``py:`` = importable
``module:attr``; ``file:`` = repository file, optionally ``#`` a token it must
contain — a directive or assignment, not a comment). Behavioural pins for the
facts that a default could silently flip (dry-run, transport, audit fail-open,
rotation) live in the same test file.

``fact`` states what the mechanism does *and its known limit*, in the same
text, because a fact without its limit is the flattering half of a fact.
"""

from __future__ import annotations

from types import MappingProxyType

_MECHANISMS: dict[str, dict] = {
    "audit_trail": {
        "name": "Governed audit trail",
        "fact": "Every MCP tool and CLI command runs through @governed_tool and writes a "
        "row to ~/.iaiops/audit.db (tool, params with secrets redacted, status, risk "
        "level, OS user, approver), denied and failed calls included. Limits: if "
        "audit.db cannot be written, low/medium-risk calls still run unaudited (one "
        "warning per process) and only high/critical calls fail closed; the "
        "`iaiops mcp` launcher itself is not audited (its tools are).",
        "anchors": (
            "py:iaiops.core.governance:governed_tool",
            "py:iaiops.core.governance.audit:AuditEngine",
            "file:iaiops/core/governance/decorators.py#_FAIL_CLOSED_RISK",
        ),
    },
    "audit_opt_out": {
        "name": "Audit opt-out for reads (IAIOPS_AUDIT_OPT_OUT=reads)",
        "fact": "IAIOPS_AUDIT_OPT_OUT=reads stops recording successful low/medium-risk "
        "calls; high/critical calls, denials and failures are always recorded, the "
        "opt-out writes a marker row once per process, and doctor and the evidence "
        "zip report it. Any other value keeps recording and warns. Limits: there is "
        "no opt-out for writes, by design.",
        "anchors": (
            "py:iaiops.core.governance.audit_opt_out:skips",
            "file:iaiops/core/governance/decorators.py#audit_opt_out.skips(",
        ),
    },
    "audit_rotation": {
        "name": "Audit rotation and archive deletion",
        "fact": "At 100 MB the audit DB is archived and a new file starts a new hash "
        "chain; only the 5 most recent archives are kept and older ones are deleted "
        "automatically. Chain verification and the evidence zip cover the current "
        "file only.",
        "anchors": (
            "py:iaiops.core.governance.audit:AuditEngine._maybe_rotate",
            "py:iaiops.core.governance.audit:AuditEngine._cleanup_archives",
        ),
    },
    "audit_hash_chain": {
        "name": "Audit hash chain + `iaiops audit verify`",
        "fact": "Each audit row carries a SHA-256 chain (prev_hash/row_hash); "
        "`iaiops audit verify` walks it and reports the first break. Limits: unkeyed "
        "— it detects an edited or deleted row, not a rewrite of the whole suffix; "
        "it covers the current DB file only (see rotation); it runs when invoked, "
        "not continuously.",
        "anchors": (
            "py:iaiops.core.governance.audit:AuditEngine.verify_chain",
            "py:iaiops.core.governance.audit:compute_row_hash",
        ),
    },
    "audit_forward": {
        "name": "`iaiops audit forward` (SIEM)",
        "fact": "Streams new audit rows as JSON lines to a syslog (UDP) or HTTP "
        "collector with a persisted cursor. Best-effort / at-least-once: no delivery "
        "acknowledgement; the cursor is a row id, so rows written after a rotation "
        "are not forwarded until ids pass the old cursor — 待核实 / open defect.",
        "anchors": ("py:iaiops.core.governance.forward:build_sink",),
    },
    "evidence_bundle": {
        "name": "`iaiops compliance evidence` (evidence zip)",
        "fact": "Exports audit rows, the chain-verification result, rules.yaml and a "
        "non-probing doctor summary as one deterministic zip. Current audit DB file "
        "only.",
        "anchors": ("py:iaiops.core.governance.evidence:export_evidence_bundle",),
    },
    "approvals_moc": {
        "name": "Named approval tokens (MOC)",
        "fact": "High-risk calls need a recorded approver: `iaiops approve` issues a "
        "one-shot, TTL-bound token consumed by the next matching call and written to "
        "the audit row. Limits: the approver is a typed name, not an authenticated "
        "identity; a static OPCUA_AUDIT_APPROVED_BY env var is still honoured as a "
        "deprecated, reusable fallback; a rules.yaml risk_tiers list that matches "
        "nothing leaves an operation at tier none.",
        "anchors": (
            "py:iaiops.core.governance.approvals:record_approval",
            "py:iaiops.core.governance.approvals:consume_approval",
        ),
    },
    "dry_run_undo": {
        "name": "Dry-run default + undo (MCP write tools)",
        "fact": "The MCP device-write tools default to dry_run=True (preview only); a "
        "real write captures the BEFORE value and registers an inverse, or says "
        "'none' where none exists. Limit: the CLI write commands preview by default "
        "too, but register no undo.",
        "anchors": ("py:iaiops.core.governance.undo:UndoStore",),
    },
    "policy_engine": {
        "name": "Policy engine (rules.yaml)",
        "fact": "Deny rules, risk tiers and change limits from ~/.iaiops/rules.yaml, "
        "evaluated before a governed call runs. Limits: change limits and deny rules "
        "exist only if the operator writes them (none by default); "
        "IAIOPS_POLICY_DISABLED=1 bypasses them for low/medium calls — only "
        "high/critical keep deny rules and approver tiers.",
        "anchors": (
            "py:iaiops.core.governance.policy:PolicyEngine",
            "file:iaiops/core/governance/policy.py#_POLICY_DISABLED_ENV = ",
        ),
    },
    "budget_breaker": {
        "name": "Runaway breaker + opt-in call ceilings",
        "fact": "On by default: a breaker trips when the same (tool, params) repeats "
        "more than 25 times in 120 s. Opt-in, off by default: per-process call-count "
        "and wall-time ceilings. A varied sweep is not bounded by either.",
        "anchors": (
            "py:iaiops.core.governance.budget:BudgetTracker",
            "file:iaiops/core/governance/budget.py#_DEFAULT_RUNAWAY_MAX = 25",
        ),
    },
    "sanitize": {
        "name": "Device-text sanitisation",
        "fact": "Text returned by devices has control and format characters stripped "
        "and is length-bounded before it reaches a model. It does not detect or "
        "remove plain-language prompt injection.",
        "anchors": ("py:iaiops.core.governance.sanitize:sanitize",),
    },
    "no_egress_gate": {
        "name": "IAIOPS_NO_EGRESS posture gate",
        "fact": "IAIOPS_NO_EGRESS=1 withholds every MCP tool declared egress=True at "
        "registration. Opt-in, not default. Not a firewall: it does not cover "
        "`iaiops audit forward` or other CLI commands, and tool results still reach "
        "the MCP client and its model.",
        "anchors": ("py:mcp_server.noegress:apply_no_egress",),
    },
    "mcp_profiles": {
        "name": "Menu-selected MCP surface (IAIOPS_MCP) + stdio default",
        "fact": "IAIOPS_MCP selects only the protocols a site needs, so unused "
        "connectors are not exposed. A pip install speaks stdio unless "
        "IAIOPS_MCP_TRANSPORT asks for HTTP; the Margo application package defaults "
        "to streamable-http on 0.0.0.0, which starts only with a bearer token (see "
        "http_bearer_auth).",
        "anchors": (
            "py:mcp_server.profiles:resolve_selection",
            "py:mcp_server.transport:resolve_transport",
            "file:deploy/margo/package.compose.yaml#IAIOPS_MCP_TRANSPORT:-streamable-http",
        ),
    },
    "http_bearer_auth": {
        "name": "Bearer-token authentication (HTTP/SSE transports)",
        "fact": "Off loopback the HTTP/SSE server refuses to start without "
        "IAIOPS_MCP_TOKEN or IAIOPS_MCP_TOKEN_FILE (at least 32 characters); with a "
        "token configured, every request needs 'Authorization: Bearer <token>', "
        "compared in constant time; refusals are logged and audited (one row per "
        "client per minute). Limits: one shared token, not a per-user identity; no "
        "TLS of its own (terminate it in front, or keep the port on a trusted "
        "segment); stdio has no token — it inherits the OS identity of the client "
        "that spawned it.",
        "anchors": (
            "py:mcp_server.http_auth:require_token_for_bind",
            "py:mcp_server.http_auth:bearer_token_app",
            "file:mcp_server/transport.py#require_token_for_bind(host, token)",
        ),
    },
    "secret_store": {
        "name": "Encrypted secret store",
        "fact": "Credentials can live in ~/.iaiops/secrets.enc (Fernet, scrypt-derived "
        "key); `iaiops secret rotate` re-encrypts under a new master password, "
        "`iaiops secret rm` deletes one. Limits: a legacy plaintext ~/.iaiops/.env "
        "(OT_<NAME>_PASSWORD) is still honoured as a fallback with a warning; the "
        "master password reaches non-interactive runs by env var; no HSM/KMS.",
        "anchors": (
            "py:iaiops.core.runtime.secretstore:SecretStore",
            "py:iaiops.core.runtime.secretstore:SecretStore.delete",
            "file:iaiops/core/runtime/config.py#ENV_FILE = ",
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
        "before the audit row is written. Only declared parameters.",
        "anchors": ("file:iaiops/core/governance/decorators.py#sensitive_params: list",),
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
        "fact": "Prunes collected history by retention rule. It does not touch the audit trail.",
        "anchors": ("py:iaiops.cli.store:store_prune_cmd",),
    },
    "reset_command": {
        "name": "`iaiops reset` (remove all data and settings)",
        "fact": "Lists, then — with --apply, a named approver and two confirmations — "
        "removes everything iaiops wrote under its state roots: config, encrypted "
        "secrets, the audit trail and archives, undo and approval state, collected "
        "history; the trail restarts with the reset's own row. CLI only, no MCP tool. "
        "Limits: files are unlinked, not shredded; external historians, forwarded "
        "audit rows and files written with --out elsewhere are not reached, and the "
        "command says so.",
        "anchors": (
            "py:iaiops.core.runtime.reset:apply_reset",
            "py:iaiops.cli.reset:reset_cmd",
        ),
    },
    "verify_determinism": {
        "name": "`iaiops verify determinism`",
        "fact": "Runs a pinned dataset through the analysis layers in fresh "
        "interpreters with the network blocked and compares SHA-256 digests; exits 1 "
        "on disagreement, so it can be a test step. It checks analysis, not security.",
        "anchors": ("py:iaiops.cli.verify:determinism_cmd",),
    },
    "ci_gate": {
        "name": "Release quality gate (CI)",
        "fact": "Every change runs pytest, ruff and bandit (zero Medium+ findings) on "
        "iaiops's own source. No fuzzing, penetration test or third-party review is "
        "part of it.",
        "anchors": ("file:.github/workflows/ci.yml#uvx bandit",),
    },
    "locked_deps": {
        "name": "Development lockfile",
        "fact": "uv.lock pins the resolved dependency graph for development and CI. "
        "What ships does not use it: the wheel declares version ranges and the "
        "release image resolves them with pip at build time. A lockfile, not an SBOM.",
        "anchors": ("file:uv.lock#version = 1",),
    },
    "signed_images": {
        "name": "cosign-signed container images",
        "fact": "Release container images and the Margo application package are "
        "cosign-signed; the public key ships at deploy/margo/cosign.pub. PyPI uploads "
        "go through Trusted Publishing (publish-pypi.yml, short-lived OIDC, no stored "
        "token), whose action also uploads attestations (set explicitly); until a "
        "release has gone through it, the wheels on PyPI carry no signature or "
        "attestation — 待核实.",
        "anchors": (
            "file:.github/workflows/publish-image.yml#cosign sign --yes",
            "file:deploy/margo/cosign.pub#BEGIN PUBLIC KEY",
            "file:.github/workflows/publish-pypi.yml#pypa/gh-action-pypi-publish",
        ),
    },
    "dependency_audit": {
        "name": "Dependency-vulnerability scan (CI)",
        "fact": "Every change exports the locked runtime dependency set (all extras, no "
        "dev group) and runs pip-audit on it; a known vulnerability fails the build "
        "unless .github/pip-audit-ignore.txt lists it with a reason. Limits: it scans "
        "the lock, not each install (a pip install resolves declared ranges); it runs "
        "per change, not continuously against released versions.",
        "anchors": (
            "file:.github/workflows/ci.yml#uvx pip-audit -r runtime-requirements.txt",
            "file:.github/pip-audit-ignore.txt",
        ),
    },
    "sbom": {
        "name": "CycloneDX SBOM per release",
        "fact": "Each tagged release attaches a CycloneDX 1.5 SBOM exported from uv.lock "
        "(every dependency, transitive included) to the GitHub release; CI builds the "
        "same SBOM on every change. Limits: it describes the locked set the release "
        "was tested with, not an individual install; no release has carried one yet "
        "— 待核实 until one does.",
        "anchors": (
            "file:.github/workflows/publish-pypi.yml#--format cyclonedx1.5",
            "file:.github/workflows/ci.yml#--format cyclonedx1.5",
        ),
    },
    "security_policy": {
        "name": "SECURITY.md (coordinated disclosure)",
        "fact": "Coordinated vulnerability disclosure policy: private reporting through "
        "GitHub or e-mail, response targets, a 90-day disclosure window, and a GitHub "
        "Security Advisory per fixed vulnerability (affected/fixed versions, impact, "
        "severity, remediation) linked from a CHANGELOG `### Security` section. "
        "Limits: targets, not service levels; not yet exercised by a reported "
        "vulnerability.",
        "anchors": (
            "file:SECURITY.md#Coordinated disclosure",
            "file:SECURITY.md#security/advisories/new",
        ),
    },
    "container_hardening": {
        "name": "Hardened container profile",
        "fact": "The edge image runs as a non-root user; the shipped compose files "
        "mount the root filesystem read-only with state on one volume (a property "
        "of the compose file, not of the image). CI checks both.",
        "anchors": (
            "file:deploy/margo/Dockerfile#USER iaiops",
            "file:deploy/margo/compose.yaml#read_only: true",
        ),
    },
    "changelog": {
        "name": "Per-release CHANGELOG",
        "fact": "Every release lists its fixes in CHANGELOG.md. It describes defects; "
        "it is not a vulnerability advisory (no identifiers, no severity).",
        "anchors": ("file:CHANGELOG.md#Changelog",),
    },
    "free_distribution": {
        "name": "MIT licence, public distribution",
        "fact": "Releases are published free of charge under the MIT licence (PyPI, "
        "GitHub, container registry).",
        "anchors": ("file:LICENSE#MIT License",),
    },
}

#: Read-only view: a caller cannot add or replace a mechanism at runtime.
MECHANISMS = MappingProxyType(_MECHANISMS)


__all__ = ["MECHANISMS"]
