# Community entry points — 2026-11-16

Research plus a first executable contribution. No upstream message, issue, PR,
registration or paid membership was submitted. Findings are not endorsements or
compatibility claims. Issue status is a snapshot and must be rechecked before work.

## 1. Sparkplug / Tahu: start with independent lifecycle evidence

Read `eclipse-tahu/tahu` develop commit
`c19db8c926dcc8c1f28ad604a13d73d95f281323`, its Python helper and open issue list.
The default branch is master; do not assume it represents active development.

**Executed:** unmodified Python helper source generated NBIRTH, DBIRTH and NDEATH
payloads. Replay into iaiops 0.34.1 main `1508515` read a cached device value after
parent NDEATH. The new regression first failed, then passed after the tap checked
parent-node death as well as device death. Device BIRTH cannot revive a dead
parent; another node remains readable; parent BIRTH requires device BIRTH again.
This is an iaiops defect, not an accusation against Tahu.

**Executed, already reported upstream:** two calls to `addMetric` without a timestamp,
50ms apart, share the default timestamp on this pinned helper. GitHub search found
[PR #398](https://github.com/eclipse-tahu/tahu/pull/398) and
[PR #472](https://github.com/eclipse-tahu/tahu/pull/472). Do not create a duplicate.
The old generated protobuf also needs the pure-Python compatibility backend in
this environment. It is isolated in a subprocess, without changing iaiops' runtime.

**Next contribution:** a small reusable lifecycle replay matrix plus results for
other host implementations, offered through existing discussion only after review.
[Issue #465](https://github.com/eclipse-tahu/tahu/issues/465) concerns Java template
alias decoding, a separate problem; it was read, not reproduced here.

Reproduce with the instructions in `tests/data/sparkplug-node-death/README.md`.
No broker, network subscription, physical device or TCK was exercised.

## 2. Fledge: complement existing quality detection

Reviewed develop `a20fc6dce1bfa47657e50760458383f815944ba2` and
[data quality documentation](https://fledge-iot.readthedocs.io/en/latest/monitoring/quality.html).
It already documents watchdog/no-data and threshold notifications. Do not propose
these as missing features or replace its pipeline.

[Issue #1716](https://github.com/fledge-iot/fledge/issues/1716) requests the triggering
reading value in notification delivery. Inspect notification payload/schema and
existing PRs before offering a minimal example preserving event time and context.
This is a useful possible starting point for a shared incident-evidence example,
not yet a reproduced defect. Package/registry outages #1715/#1714 are reported by
others; their infrastructure was not tested here.

**Next local experiment:** a pinned reading export with explicitly declared cadence,
source timestamp, ingestion timestamp and quality. Compare coverage/gap explanations
with the original data; retain unknown time. Inspect current API/export schemas
before designing an adapter. No Fledge runtime or plugin integration executed yet.

## 3. LF Energy: PIVOT evidence before a substation platform deployment

The actual repositories are under [fledge-power](https://github.com/fledge-power),
not a guessed monolithic `fledgepower` repository.

[Python PIVOT model request #2](https://github.com/fledge-power/fledgepower-pivot-model/issues/2)
asks about accurate class generation. Repository revision recorded via GitHub metadata:
`c00cbf776c90a3e0d0ffdeee4e6659508ba1d2cb`. A potential small contribution is a Python
schema/example validator retaining value, timestamp and quality distinctions,
with accepted/rejected example fixtures. Do not invent a replacement schema or
claim full protocol compatibility. Read the current schema and contribution rules
before implementation; no PIVOT runtime result is asserted here.

[IEC-104 issue #80](https://github.com/fledge-power/fledge-south-iec104/issues/80)
concerns general-interrogation completion across multiple ASDUs. This could become
a read-only iaiops-energy interoperability scenario. It has not been reproduced;
keep energy-specific code and validation in the energy repository. Skip control
command work as an initial contribution.

SEAPATH's entry is [seapath/ansible](https://github.com/seapath/ansible), whose README
explains contribution linting and cluster CI (main snapshot
`20244c248acff58637078480854d70e0df1ee6bf`). Its
[official project page](https://lfenergy.org/projects/seapath/) includes monitoring
workloads. A later contribution could document a non-critical collector workload
and distinguish application/collection health from protection-system health.
No SEAPATH playbook, cluster, real-time or failover test was run; first obtain an
appropriate lab rather than treating a container smoke test as platform validation.

## 4. OPC UA: a narrow import/export reproduction

Reviewed UA-CloudLibrary main `d0cd8f3d922b0c52c11828135d2cf975e47a6888` and current issues.
[Issue #326](https://github.com/OPCFoundation/UA-CloudLibrary/issues/326) describes
large uploaded values exceeding query-string limits. A useful contribution could
be a self-hosted regression showing preservation of a large NodeSet values body,
plus backward compatibility for existing clients. This report was read, not
reproduced; do not upload experiments to the shared public service.

[Issue #324](https://github.com/OPCFoundation/UA-CloudLibrary/issues/324) concerns a
published DigitalProductPassport NodeSet. Inspect its sample/validation discussion
before proposing offline model diagnostics. Information-model roles remain
suggestions until a person confirms the site semantics.

First check contribution and licence requirements: the GitHub API returned
`NOASSERTION` for the repository's licence classifier, which is not a conclusion
that the project has no licence. No upstream source is copied into iaiops here.

## Evidence and limits

The committed binary fixtures are protocol payloads generated by the pinned Tahu
helper with explicit synthetic inputs. Upstream implementation source remains
outside this repository. Hashes, baseline result and reproduction steps accompany
the fixtures. Published package version remains 0.34.1; the tap fix merged to main via PR #300 on 2026-11-17 and is not yet released. No hardware or independent broker validation is implied.


Local validation: 72 Sparkplug/tap/recorded-frame/point-draft tests passed, plus
14 LLM-free and no-PLC-logic-write boundary tests. Ruff check/format and Bandit
Medium+ gate passed. Baseline regression failed before the fix; the standalone
Tahu replay changed from cached device value 1 to a refused reading after NDEATH.


Follow-up: [2026-11-17 Fledge function probe](2026-11-17-fledge-notification.md).
