# Community worklist

Added 2026-11-16. Maintain this list during normal project work; it does not
create a scheduled automation. Actual participation and PR states are recorded in
[COMMUNITY-CONTRIBUTIONS.md](COMMUNITY-CONTRIBUTIONS.md), including the account's
existing Tahu #472 and Margo submissions. Planned directions are not completed registrations. No paid membership,
registration, outreach or upstream submission is implied by this list.

## Margo follow-up queue — 2026-11-24

Recorded while the contributor is traveling without the test environment.
No new upstream submission or hardware/runtime validation is implied.

- [ ] **First, close existing review loops:** [Symphony #92](https://github.com/margo/symphony/pull/92)
  needs a concise concurrency scenario and minimal reproducer; [#93](https://github.com/margo/symphony/pull/93)
  needs the exact onboarding requests/EasyCLI reproduction for distinct versioned
  artifacts with the same application ID/name when the environment is available.
  The travel/update reply is posted; await feedback before repeating it.
- [ ] **Read now; test later:** review [digest pinning #239](https://github.com/margo/specification/pull/239)
  and [immutability issue #238](https://github.com/margo/specification/issues/238)
  against existing package/component/image receipts. Distinguish digests at each
  layer, tag mutation, and runtime image references; do not claim implementation.
- [ ] Review [allowEmpty #237](https://github.com/margo/specification/pull/237)
  for missing/empty/default parameter boundaries; runtime checks await environment.
- [ ] Track CTT tasks [#519](https://github.com/margo/sandbox/issues/519),
  [#520](https://github.com/margo/sandbox/issues/520),
  [#521](https://github.com/margo/sandbox/issues/521),
  [#522](https://github.com/margo/sandbox/issues/522): requirement-ID mapping and
  coverage gaps. Existing assignees are working on them; clarify title/body scope
  before contributing, and avoid duplicate implementation.
- [ ] Follow [MIAF credentials #94](https://github.com/margo/symphony/pull/94)
  (Draft; SVID rotation remains open) and [EasyCLI logs #518](https://github.com/margo/sandbox/issues/518)
  (assigned). Observation only until a concrete uncovered problem is identified.
- [ ] Track [CTT #21](https://github.com/margo/conformance_test_toolkit/pull/21)
  review; do not equate the proposal with merged conformance support.

## Authorized submissions — 2026-11-17

- Fledge: [PR #1748](https://github.com/fledge-iot/fledge/pull/1748), notification
  evaluation-data documentation; submitted after review, not yet accepted/merged.
- PIVOT: [existing issue #2 comment](https://github.com/fledge-power/fledgepower-pivot-model/issues/2#issuecomment-6946004370),
  lossless example observations and schema/API clarification; not an implementation PR.
- Full Fledge service/plugin validation and typed PIVOT bindings remain open.

## Contribution follow-up entry point

Use [the contribution ledger](COMMUNITY-CONTRIBUTIONS.md) for PR content, current
state, ownership, evidence and next action. Its read-only GitHub API refresh command
is documented there. Check this ledger before claiming no upstream submission or
opening another issue; changes made outside this chat are included when verified.

## Maintenance completed on main — 2026-11-16

[PR #299](https://github.com/industrial-aiops/industrial-aiops/pull/299) is merged.
The IGEL source demo now uses the 0.34.1 baseline, both OPC UA installation extras
require pyOpenSSL >=26.4, and five local CA-chain/CRL checks are included. These
changes are on main; they are not a new published package release. All six PR CI
checks passed, including the Python 3.11/3.12 gates and Linux integration contracts.

First research and experiment: [entry-point report](community/2026-11-16-entry-points.md).
PR #300 merged on 2026-11-17: the parent-death refusal is now on main, still
unreleased. Next: Fledge notification context and a full delivery-plugin capture. Keep Margo
state-retention follow-up active. Vendor PKI, CRL provenance checks, IGEL/AGNES and
physical-device validation remain open; community registrations remain planned.

## First experiment — 2026-11-16

Independent Tahu helper payloads reproduced an iaiops parent-node-death cache gap;
regression and fix landed on main in PR #300; no new package release was made. No upstream defect is attributed to
Tahu. Its default-timestamp behavior was also reproduced, but existing PRs #398/#472
already cover it. Other projects have source-backed candidate tasks, not verified
integrations. See the report for exact sources and evidence limits.

## Fledge progress — 2026-11-17

[Local probe report](community/2026-11-17-fledge-notification.md): five actual C++
reason-enrichment cases passed at the pinned notification-service revision.
Current source already attaches evaluation data under `reason.data`; the missing
value claim was not reproduced at this function boundary. Full service/plugin and
version-specific validation remain pending. The documentation was submitted as
[Fledge #1748](https://github.com/fledge-iot/fledge/pull/1748); acceptance remains separate.

## Working routine

- Pick one small item per maintenance session, after immediate product defects.
- Read current upstream issues/release notes and record source URL, date and commit.
- Look for a concrete problem affecting users of both projects. Check for existing
  work before duplicating it; do not manufacture issues for visibility.
- Reproduce locally with pinned versions. Separate synthetic, independent-stack,
  reference-sandbox and physical-device evidence. Keep human semantics unconfirmed.
- Record findings as: observation → reproduction → impact → proposed contribution
  → upstream feedback → next action. Prepare small tests/docs/fixes before outreach.
- Check contribution rules/licensing before copying source. Membership, compatibility
  listings and contributor status are distinct; never claim a completed integration
  or certification from a demo. External messages/submissions require explicit direction.

## Active exploration queue

| Community | Potential contribution / first investigation | Mutual value | Status |
|---|---|---|---|
| [Margo](https://github.com/margo/sandbox) | Follow sandbox #490/#491 and CTT #18/#19; reproduce upstream changes before revising our state-retention and conformance claims | Reliable stateful industrial workloads; reference deployment evidence | Existing participation; continue follow-up |
| [Eclipse Sparkplug / Tahu](https://github.com/eclipse-tahu/tahu) | Independently produced BIRTH/DEATH, stale-value, reconnect and alias/sequence cases; compare with our tap/namespace audit and identify reproducible mismatches | Data trust and cross-implementation interoperability | Research and offline Tahu replay started; fix merged via #300; expand offline matrix |
| [LF Edge Fledge](https://lfedge.org/projects/fledge/) | Inspect existing north plugins/API and examples; prototype one read-only path into coverage/incident analysis before proposing another plugin | Give existing industrial data pipelines explainable coverage and incident evidence | Function-level probe passed; full service test pending |
| [LF Energy](https://lfenergy.org/projects/) — FledgePOWER | Inspect current project status and contribution process; seek a simulator-based IEC-104/DNP3/IEC-61850 observation case using iaiops-energy | Reproducible protocol-health evidence for energy gateways | Planned; coordinate with energy repository |
| [LF Energy SEAPATH](https://lfenergy.org/projects/seapath/) | Check workload deployment/observability examples; assess a non-critical read-only collector scenario, with no protection/control claims | Understand operations evidence for virtualized substation workloads | Planned; hardware/partner evidence pending |
| [OPC Foundation open-source ecosystem](https://opcfoundation.org/cloud/) | Start with UA Cloud Library/information-model examples and certificate troubleshooting; keep suggested point semantics separate from operator confirmation | Better model interpretation, diagnostics and reproducible interop reports | Function-level probe passed; full service test pending |

Priority: deepen Margo; start Sparkplug, then Fledge. Explore energy projects
when a concrete lab case or partner appears; keep OPC UA work narrowly scoped.
This ordering is a working preference, not a promise of acceptance by any community.

## Finding log

| Date | Community / source | Observation | Evidence and limits | Next step |
|---|---|---|---|---|
| 2026-11-16 | OPC UA / local asyncua source | Existing vendor trust tests lack CA-chain/CRL scenarios | Added local strict-validator tests; independent vendor PKI and robust CRL provenance checks remain separate | Review reproducible gaps before preparing an upstream report |
| 2026-11-16 | Sparkplug / Tahu pinned Python helper | Parent NDEATH did not invalidate iaiops device-cache reads | Reproduced with external-generated payloads; local regression and fix, offline only | Merged via #300; extend lifecycle matrix; no upstream claim |
| 2026-11-16 | Tahu timestamp defaults | Reproduced equal default timestamps across two calls | Existing PRs #398/#472 found | Follow existing work; do not duplicate |
| 2026-11-16 | Fledge / LF Energy / OPC UA | Reviewed current source/docs/issues; candidate tasks recorded | No runtimes or public uploads executed | Proceed with one local bounded fixture per candidate |

Use a new row for each verified finding. Leave an unsuccessful experiment visible;
do not turn lack of data into evidence that a device or project is healthy.

## Merge review and weekend environment work — 2026-11-25

- PRs #302/#303/#304: reconcile with 0.36.0 main and run current CI before merging.
  These are contribution records and local probes, not completed service integrations.
- PR #281: retain release hold until IA-06 importer/authorized device samples and
  actual FAT/exFAT/SMB no-hard-link media acceptance are available. PR #284 is
  stacked on #281 and retains the same gate. Unit tests cannot close these gates.
- PR #295: retain Draft pending the planned reconnect/event-time and broader
  Sparkplug coverage, and comparison with already merged #300 and 0.35/0.36 fixes.
- Weekend (after environment access returns): prioritize Symphony #92 concurrent
  manifest scenario and #93 distinct-version EasyCLI reproducer, then the Fledge
  real-service/plugin capture. Collector reception on a second platform remains
  the separate P1 acceptance task in ROADMAP.md; do not mark it tested here.
