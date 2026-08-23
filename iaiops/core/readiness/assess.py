"""Assess what this installation can actually do today — from local state only.

The gap this closes: every capability except ``scan`` assumes you already know
your endpoints, and nothing told a new user which scenarios their site can
currently run or what each blocked one is waiting for (see ``docs/HLD.md §9``).

Two disciplines make the answer trustworthy:

**It emits nothing.** No device is contacted. Readiness is a judgement about
configuration and locally stored history, so it runs instantly, on an aeroplane,
against a site you have not been authorised to probe — the same posture as
``scan plan``. A readiness check that had to touch the plant would not get run.

**It reports, it never fills in.** Which tag is the production counter is
process knowledge, not an inferable signal property, and a wrong guess produces
plausible-looking OEE numbers — considerably worse than an error. So this module
names what is missing and stops (``docs/HLD.md §9.4``, D16).

Where a prerequisite cannot be supplied at all yet, it says so rather than
implying the operator forgot: ``MonitorTag`` has no semantic role field, so the
OEE run/stop/count mapping is currently **inexpressible**, not merely unset.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from iaiops.core.readiness.model import Capability, ReadinessReport, Requirement

#: Protocols whose servers can hand us alarm/condition events. Everything else
#: returns an empty alarm list, which is a real limit on the evidence available
#: to root-cause analysis rather than a configuration mistake.
ALARM_CAPABLE_PROTOCOLS = frozenset({"opcua"})

#: Mirrors iaiops.core.brain.baseline — a baseline refuses to learn below these,
#: so reporting a different number here would promise something the learner
#: would then decline to do.
BASELINE_MIN_SAMPLES = 100
BASELINE_MIN_SPAN_DAYS = 1.0


def gather_facts(config: Any = None, db_path: Any = None) -> dict[str, Any]:
    """Collect everything the assessment reasons from. Touches no device.

    A missing or unreadable config is a fact about the site ("nothing is
    configured yet"), not an error — that is precisely the state a first-time
    user is in, and it is the one this command most needs to answer for.
    """
    from iaiops.core.sink.sqlite_local import store_coverage

    targets: tuple[Any, ...] = ()
    historian = None
    config_error = ""
    if config is None:
        try:
            from iaiops.core.runtime.config import load_config

            config = load_config()
        except Exception as exc:  # noqa: BLE001 — an unconfigured site is the point
            config_error = f"{type(exc).__name__}: {exc}"
    if config is not None:
        targets = tuple(getattr(config, "targets", ()) or ())
        historian = getattr(config, "historian", None)

    protocols = sorted(
        {str(getattr(t, "protocol", "")) for t in targets if getattr(t, "protocol", "")}
    )
    monitored = sum(len(getattr(t, "tags", ()) or ()) for t in targets)
    from iaiops.core.collect.reader import can_collect

    collectable = [
        str(getattr(t, "name", "")) for t in targets if can_collect(str(getattr(t, "protocol", "")))
    ]
    from iaiops.core.runtime.config import TagRole, roles_present

    oee_roles: dict[str, str] = {}
    role_conflict = ""
    for t in targets:
        try:
            oee_roles.update(roles_present(getattr(t, "tags", ()) or ()))
        except ValueError as exc:
            role_conflict = str(exc)
    coverage = store_coverage(db_path)

    return {
        "config_error": config_error,
        "endpoints": len(targets),
        "endpoint_names": [str(getattr(t, "name", "")) for t in targets][:50],
        "protocols": protocols,
        "alarm_capable_endpoints": [
            str(getattr(t, "name", ""))
            for t in targets
            if str(getattr(t, "protocol", "")) in ALARM_CAPABLE_PROTOCOLS
        ],
        "collectable_endpoints": collectable,
        "oee_roles": dict(sorted(oee_roles.items())),
        "role_conflict": role_conflict,
        "oee_required_roles": [TagRole.RUN_STATE, TagRole.TOTAL_COUNT],
        "ideal_cycle_time_s": next(
            (
                float(getattr(t, "ideal_cycle_time_s"))
                for t in targets
                if getattr(t, "ideal_cycle_time_s", None) is not None
            ),
            None,
        ),
        "monitored_tags": monitored,
        "retention_raw_days": getattr(config, "retention_raw_days", None) if config else None,
        "historian": bool(historian),
        "historian_reader": str(getattr(historian, "reader", "")) if historian else "",
        "store": coverage,
    }


def _endpoints_req(facts: dict[str, Any]) -> Requirement:
    n = facts["endpoints"]
    return Requirement(
        key="endpoints",
        label="at least one configured endpoint",
        met=n > 0,
        detail=f"{n} configured" if n else "no endpoints in config.yaml",
        fix="Run `iaiops scan run --targets <cidr>` to find devices, then `iaiops init`.",
    )


def _collectable_req(facts: dict[str, Any]) -> Requirement:
    """Whether any configured endpoint can be sampled on a schedule.

    Not every protocol can: a point-read path is what continuous collection
    needs, and some connectors are stream- or file-shaped instead. Reporting
    this as a missing configuration would be wrong — it is a property of the
    protocol, so the fix names the protocols that do work.
    """
    names = facts["collectable_endpoints"]
    from iaiops.core.collect.reader import collectable_protocols

    return Requirement(
        key="collectable_endpoint",
        label="an endpoint that can be sampled on a schedule",
        met=bool(names),
        detail=(
            f"collectable endpoints: {', '.join(names)}"
            if names
            else "no configured endpoint has a point-read path"
        ),
        fix=(
            "Continuous collection needs a protocol with a point-read path. "
            f"Available today: {', '.join(collectable_protocols())}."
        ),
    )


def _retention_req(facts: dict[str, Any]) -> Requirement:
    """Whether this site has decided how long raw samples live.

    Measured on this codebase: three tags at 200ms is 2.0 GB a week and 102 GB a
    year. Continuous collection WITHOUT a retention decision is a disk filling up
    on a schedule, and the site finds out months in, usually at the worst moment.

    Optional rather than blocking: a default policy applies, so collection still
    works. But an unstated policy is a decision nobody made, and this says so.
    """
    from iaiops.core.retain.policy import DEFAULT_RAW_DAYS

    days = facts.get("retention_raw_days")
    return Requirement(
        key="retention",
        label="a retention decision for raw samples",
        met=days is not None,
        detail=(
            f"raw samples kept {days} days"
            if days is not None
            else f"not declared — the {DEFAULT_RAW_DAYS}-day default applies"
        ),
        fix=(
            "Add a `retention:` block with `raw_days:` to config.yaml. Three tags at "
            "200ms is about 2 GB a week, so continuous collection without a stated "
            "policy fills a disk on a schedule. Derived facts (stoppages, per-shift "
            "figures) never expire — they are ~35,000x smaller and are what answers "
            "about a period whose raw data is gone."
        ),
        optional=True,
    )


def _samples_req(facts: dict[str, Any]) -> Requirement:
    store = facts["store"]
    n = store["samples"]
    return Requirement(
        key="samples",
        label="collected samples in the local store",
        met=n > 0,
        detail=f"{n:,} samples across {store['tags']} tags" if n else "local store is empty",
        fix="Collect some data first — any protocol read writes to the local store.",
    )


def _monitored_tags_req(facts: dict[str, Any]) -> Requirement:
    n = facts["monitored_tags"]
    return Requirement(
        key="monitored_tags",
        label="a list of the tags that matter",
        met=n > 0,
        detail=f"{n} tags declared under endpoints" if n else "no tags declared in config.yaml",
        fix=(
            "Add a `tags:` list to the endpoint in config.yaml. Which points matter is "
            "process knowledge — this tool will not choose them for you."
        ),
    )


def _alarm_source_req(facts: dict[str, Any]) -> Requirement:
    names = facts["alarm_capable_endpoints"]
    return Requirement(
        key="alarm_source",
        label="an alarm source",
        met=bool(names),
        detail=(
            f"OPC-UA endpoints able to supply conditions: {', '.join(names)}"
            if names
            else (
                "no OPC-UA endpoint — alarms come from "
                f"{'/'.join(sorted(ALARM_CAPABLE_PROTOCOLS))} only"
            )
        ),
        fix=(
            "Alarm evidence needs an OPC-UA server exposing Alarms & Conditions. "
            "Without one the analysis still runs, with one fewer class of evidence."
        ),
        optional=True,
    )


def _historian_req(facts: dict[str, Any]) -> Requirement:
    return Requirement(
        key="historian",
        label="a historian connection",
        met=facts["historian"],
        detail=(
            f"reader: {facts['historian_reader']}"
            if facts["historian"]
            else "no `historian:` block in config.yaml"
        ),
        fix=(
            "Add a `historian:` block. Without it the copilot samples the CURRENT "
            "values, so the hours of drift before a stoppage are invisible."
        ),
        optional=True,
    )


def _baseline_history_req(facts: dict[str, Any]) -> Requirement:
    store = facts["store"]
    days = store.get("span_days", 0.0)
    best = store.get("best_covered_samples", 0)
    enough = best >= BASELINE_MIN_SAMPLES and days >= BASELINE_MIN_SPAN_DAYS
    if store["samples"]:
        detail = (
            f"best-covered tag {store.get('best_covered_tag', '?')!r}: "
            f"{best:,} samples over {days:g} days "
            f"(needs ≥{BASELINE_MIN_SAMPLES} over ≥{BASELINE_MIN_SPAN_DAYS:g} day)"
        )
    else:
        detail = "no history collected yet"
    return Requirement(
        key="baseline_history",
        label="enough history to learn a normal band",
        met=enough,
        detail=detail,
        fix=(
            "Keep collecting. A baseline is learned per tag and refuses below "
            f"{BASELINE_MIN_SAMPLES} samples or {BASELINE_MIN_SPAN_DAYS:g} day of span — "
            "that refusal is the feature that keeps false alarms near zero."
        ),
    )


def _oee_mapping_req(facts: dict[str, Any]) -> Requirement:
    """Whether this line declares the tags OEE is computed from.

    Until roles existed this was **inexpressible** — there was no field that
    could say "this tag is the production counter", so the honest report was
    that the product offered no way to supply it. It is now a normal, checkable
    prerequisite: still never guessed (D16/D23), but now sayable.

    ``run_state`` and ``total_count`` are the floor. ``good_count`` refines
    Quality and its absence degrades rather than blocks, because a line that
    does not count rejects still has a real Availability and Performance.
    """
    from iaiops.core.runtime.config import TagRole

    declared = facts["oee_roles"]
    required = [TagRole.RUN_STATE, TagRole.TOTAL_COUNT]
    missing = [r for r in required if r not in declared]

    if facts["role_conflict"]:
        return Requirement(
            key="oee_role_mapping",
            label="a run-state and production-count tag",
            met=False,
            detail=facts["role_conflict"],
            fix="One line has one production counter — declare which tag holds it.",
        )

    return Requirement(
        key="oee_role_mapping",
        label="a run-state and production-count tag",
        met=not missing,
        detail=(
            "declared: " + ", ".join(f"{k}={v}" for k, v in declared.items())
            if declared
            else "no tag declares an OEE role"
        ),
        fix=(
            f"Add `role:` to the tags in config.yaml — missing {', '.join(missing)}. "
            "A run_state tag must also say `running_when:` (which value means running); "
            "assuming 'anything non-zero' would count idle and fault as production. "
            "Which tag counts production is process knowledge — not inferred here."
        ),
    )


def _oee_quality_req(facts: dict[str, Any]) -> Requirement:
    """Good/reject count refines Quality; without it OEE is still meaningful."""
    from iaiops.core.runtime.config import TagRole

    declared = facts["oee_roles"]
    have = [r for r in (TagRole.GOOD_COUNT, TagRole.REJECT_COUNT) if r in declared]
    return Requirement(
        key="oee_quality_tag",
        label="a good- or reject-count tag",
        met=bool(have),
        detail=", ".join(have) if have else "no quality count declared",
        fix=(
            "Without one, Quality cannot be measured and OEE reports Availability × "
            "Performance only — honest, but not the whole figure."
        ),
        optional=True,
    )


def _ideal_cycle_req(facts: dict[str, Any]) -> Requirement:
    """The design cycle time, without which Performance cannot be computed.

    Optional on purpose. Availability is the factor that minor stoppages live in,
    and it needs only a run-state tag — so the headline gap between a hand-kept
    figure and a measured one is reachable before anyone has to look up a
    product spec. Reporting Availability alone and saying so is honest;
    inventing a cycle time to complete the formula would not be.
    """
    value = facts.get("ideal_cycle_time_s")
    return Requirement(
        key="ideal_cycle_time",
        label="the design cycle time",
        met=value is not None,
        detail=f"{value:g}s per part" if value is not None else "not declared on any endpoint",
        fix=(
            "Add `ideal_cycle_time_s:` to the endpoint. Without it OEE reports "
            "Availability (and Quality, if counts are declared) but not Performance — "
            "which is honest, and still shows the stoppages a manual count misses."
        ),
        optional=True,
    )


def assess(config: Any = None, db_path: Any = None) -> ReadinessReport:
    """Report what this site can run today, and what each gap is waiting for."""
    facts = gather_facts(config, db_path)

    capabilities = (
        Capability(
            key="site_survey",
            label="Site survey (scan)",
            value="Find what is on a network and what each device speaks.",
            requirements=(
                Requirement(
                    key="nothing",
                    label="nothing — needs only a target range",
                    met=True,
                    detail="always available; `scan plan` emits nothing at all",
                ),
            ),
        ),
        Capability(
            key="data_quality",
            label="Data quality scorecard",
            value="Score every tag for bad timestamps, staleness and quality bits.",
            requirements=(_samples_req(facts),),
        ),
        Capability(
            key="export",
            label="Export / Grafana",
            value="CSV, SQLite or Parquet out; a Prometheus endpoint to graph.",
            requirements=(_samples_req(facts),),
        ),
        Capability(
            key="continuous_collection",
            label="Continuous collection (assessment run)",
            value="Sample a line for days so real OEE and minor stoppages become visible.",
            requirements=(
                _endpoints_req(facts),
                _collectable_req(facts),
                _monitored_tags_req(facts),
            ),
        ),
        Capability(
            key="baseline_alerting",
            label="Conservative baseline alerting",
            value="A per-tag normal band learned from this site's own history.",
            requirements=(_samples_req(facts), _baseline_history_req(facts)),
        ),
        Capability(
            key="dataflow_diagnosis",
            label="Dataflow break location",
            value="Which hop stopped: device, collector, gateway or historian.",
            requirements=(_endpoints_req(facts),),
        ),
        Capability(
            key="downtime_rca",
            label="Downtime root cause",
            value="Ranked causes with citations you can check, around an incident.",
            requirements=(
                _endpoints_req(facts),
                _monitored_tags_req(facts),
                _alarm_source_req(facts),
                _historian_req(facts),
            ),
        ),
        Capability(
            key="alarm_governance",
            label="Alarm flood governance",
            value="Bad-actor ranking and chatter, against ISA-18.2 targets.",
            # The SAME requirement, but required here rather than optional: an
            # alarm source is one evidence class among four for root cause, and
            # the entire input for alarm governance.
            requirements=(dataclasses.replace(_alarm_source_req(facts), optional=False),),
        ),
        Capability(
            key="oee",
            label="OEE from configured tags",
            value="Availability × Performance × Quality, derived from the line itself.",
            requirements=(
                _endpoints_req(facts),
                _collectable_req(facts),
                _oee_mapping_req(facts),
                _ideal_cycle_req(facts),
                _oee_quality_req(facts),
            ),
        ),
    )

    notes: list[str] = []
    if facts["config_error"]:
        notes.append(
            f"config.yaml could not be read ({facts['config_error']}) — treating this as "
            "a site that has not been configured yet."
        )
    if not facts["store"]["exists"]:
        notes.append(
            "No local store yet. It is created by the first read that collects samples; "
            "its absence is not a fault."
        )
    notes.append(
        "Nothing was contacted to produce this report — it is derived from config.yaml "
        "and the local store only."
    )
    return ReadinessReport(capabilities=capabilities, facts=facts, notes=tuple(notes))


__all__ = [
    "ALARM_CAPABLE_PROTOCOLS",
    "BASELINE_MIN_SAMPLES",
    "BASELINE_MIN_SPAN_DAYS",
    "gather_facts",
    "assess",
]
