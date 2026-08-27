"""The eight investigation steps, and what each one needs from a site.

HLD §13.4 holds the map from the IT-side original to the OT equivalents, and
which steps this repo can already walk. This module is that table as code.

Each builder returns a :class:`Step` whose requirements are judged from the
facts `readiness` already gathers — no device is contacted and no analysis is
run. That restraint is the whole of delivery step 1 (§13.10): answer the
capability question first, wire the analysis later.

[PURE] No I/O.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.investigate.model import Step
from iaiops.core.readiness.model import Requirement

#: Order is the contract — `reachable_through` walks it.
STEP_KEYS = (
    "define_incident",
    "collect_evidence",
    "normalize_and_check",
    "compress_and_rank",
    "correlate_timeline",
    "test_hypotheses",
    "knowledge_check",
    "conclude_and_close",
)


def build_steps(facts: dict[str, Any]) -> tuple[Step, ...]:
    return tuple(
        builder(facts)
        for builder in (
            _define_incident,
            _collect_evidence,
            _normalize_and_check,
            _compress_and_rank,
            _correlate_timeline,
            _test_hypotheses,
            _knowledge_check,
            _conclude_and_close,
        )
    )


def _define_incident(facts: dict[str, Any]) -> Step:
    n = facts["endpoints"]
    return Step(
        number=1,
        key="define_incident",
        label="Define the incident",
        value="A named window on a named asset — every later step is scoped by it.",
        requirements=(
            Requirement(
                key="endpoints",
                label="at least one configured endpoint",
                met=n > 0,
                detail=f"{n} configured" if n else "no endpoints in config.yaml",
                fix="Run `iaiops scan run --targets <cidr>` to find devices, then `iaiops init`.",
            ),
        ),
    )


def _collect_evidence(facts: dict[str, Any]) -> Step:
    store = facts["store"]
    rows = int(store.get("samples", 0) or 0)
    alarm_capable = facts["alarm_capable_endpoints"]
    return Step(
        number=2,
        key="collect_evidence",
        label="Collect the evidence",
        # Relations are NOT here. They are declared, not collected, and their
        # only consumer is step 5 — carrying the same unmet-and-inexpressible
        # requirement in two steps double-counts one gap and dilutes the flag
        # that is supposed to mean "the product offers no way at all".
        value="Sampled history, alarms, historian and change baseline for the window.",
        requirements=(
            Requirement(
                key="samples",
                label="collected samples in the local store",
                met=rows > 0,
                detail=f"{rows:,} sample(s) stored" if rows else "local store is empty",
                fix="Collect first: `iaiops collect run <endpoint> --duration 1h`.",
            ),
            Requirement(
                key="alarm_source",
                label="an alarm-capable endpoint",
                met=bool(alarm_capable),
                detail=(
                    f"alarm-capable: {', '.join(alarm_capable)}"
                    if alarm_capable
                    else "no configured endpoint surfaces alarms"
                ),
                fix=(
                    "Alarms come from OPC-UA A&C today; a run-state tag "
                    "alone carries no alarm text."
                ),
                optional=True,
            ),
        ),
    )


def _normalize_and_check(facts: dict[str, Any]) -> Step:
    store = facts["store"]
    rows = int(store.get("samples", 0) or 0)
    return Step(
        number=3,
        key="normalize_and_check",
        label="Normalize and check the data",
        value="One clock, one entity naming, and an honest account of what was not seen.",
        requirements=(
            Requirement(
                key="samples_to_check",
                label="samples to check",
                met=rows > 0,
                detail=f"{rows:,} sample(s) available" if rows else "nothing collected to check",
                fix="Collect first: `iaiops collect run <endpoint> --duration 1h`.",
            ),
        ),
    )


def _compress_and_rank(facts: dict[str, Any]) -> Step:
    alarm_capable = facts["alarm_capable_endpoints"]
    return Step(
        number=4,
        key="compress_and_rank",
        label="Compress and rank",
        value="Alarm floods segmented, chattering and stale alarms separated out (ISA-18.2).",
        requirements=(
            Requirement(
                key="alarm_events",
                label="an alarm source to compress",
                met=bool(alarm_capable),
                detail=(
                    f"alarm-capable: {', '.join(alarm_capable)}"
                    if alarm_capable
                    else "no configured endpoint surfaces alarms"
                ),
                fix="Alarm analysis needs an alarm source; OPC-UA A&C is the path today.",
            ),
        ),
    )


def _correlate_timeline(facts: dict[str, Any]) -> Step:
    store = facts["store"]
    rows = int(store.get("samples", 0) or 0)
    return Step(
        number=5,
        key="correlate_timeline",
        label="Correlate the timeline",
        value=("Trigger, symptom, propagation and recovery — each line citing an evidence id."),
        requirements=(
            Requirement(
                key="single_asset_series",
                label="a sampled series for the asset",
                met=rows > 0,
                detail=f"{rows:,} sample(s) stored" if rows else "local store is empty",
                fix="Collect first: `iaiops collect run <endpoint> --duration 1h`.",
            ),
            Requirement(
                key="propagation_relations",
                label="declared relations for cross-asset propagation",
                met=False,
                detail="no line relationships are declared",
                fix="",
                # Optional on purpose: without relations the timeline degrades to
                # a SINGLE-asset one rather than disappearing (§13.7), and the
                # degradation has to be stated rather than silently applied.
                optional=True,
                expressible=False,
            ),
        ),
    )


def _test_hypotheses(facts: dict[str, Any]) -> Step:
    store = facts["store"]
    rows = int(store.get("samples", 0) or 0)
    return Step(
        number=6,
        key="test_hypotheses",
        label="Test the hypotheses",
        value=(
            "Each candidate with its supporting evidence, counter-evidence, gaps and next step."
        ),
        requirements=(
            Requirement(
                key="evidence_to_rank",
                label="evidence to rank",
                met=rows > 0,
                detail=f"{rows:,} sample(s) stored" if rows else "no evidence collected",
                fix="Collect first: `iaiops collect run <endpoint> --duration 1h`.",
            ),
        ),
    )


def _knowledge_check(facts: dict[str, Any]) -> Step:
    """The step this product cannot satisfy at all today (HLD §13.8, D36).

    Fault mechanisms are hardcoded constants; there is no knowledge base, no
    per-protocol mechanism library and no way to mount one. Reporting that as
    "you have not configured it" would send somebody looking for a setting that
    does not exist — and skipping the step would read as "checked, nothing
    wrong", which is worse still.
    """
    return Step(
        number=7,
        key="knowledge_check",
        label="Check against known mechanisms",
        value=(
            "Device model, firmware and applicability constraints that rule a candidate in or out."
        ),
        requirements=(
            Requirement(
                key="mechanism_library",
                label="a mounted fault-mechanism library",
                met=False,
                detail="fault mechanisms are built in and fixed; nothing can be mounted",
                fix="",
                expressible=False,
            ),
            Requirement(
                key="site_cases",
                label="this site's own confirmed cases",
                met=False,
                detail="checked at run time, not from configuration",
                fix="Confirm incidents as they happen: `iaiops case confirm <id> --cause <cause>`.",
                optional=True,
            ),
        ),
    )


def _conclude_and_close(facts: dict[str, Any]) -> Step:
    store = facts["store"]
    rows = int(store.get("samples", 0) or 0)
    return Step(
        number=8,
        key="conclude_and_close",
        label="Conclude and close the loop",
        value="A graded conclusion, and the confirmed label fed back for learning.",
        requirements=(
            Requirement(
                key="something_to_conclude_about",
                label="collected history to conclude from",
                met=rows > 0,
                detail=f"{rows:,} sample(s) stored" if rows else "no history to conclude from",
                fix="Collect first: `iaiops collect run <endpoint> --duration 1h`.",
            ),
        ),
    )
