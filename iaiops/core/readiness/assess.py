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
        "monitored_tags": monitored,
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


def _oee_mapping_req(_facts: dict[str, Any]) -> Requirement:
    """The one prerequisite that cannot be supplied today.

    ``oee_compute`` takes five plain numbers (planned/run/ideal-cycle/total/good)
    and ``MonitorTag`` carries only a ref, a label and thresholds — there is no
    field that says "this tag is the production counter". So OEE is a calculator
    a human feeds, not something derivable from a configured site, and saying
    "not configured" would send someone hunting for a setting that does not exist.
    """
    return Requirement(
        key="oee_role_mapping",
        label="a run/stop/count/cycle tag mapping",
        met=False,
        detail="config has no way to declare a tag's production role yet",
        fix=(
            "Today OEE is computed by passing the five figures in directly "
            "(`iaiops analytics oee ...`). Deriving them from configured tags needs a "
            "semantic role on MonitorTag, which does not exist yet — see docs/ROADMAP.md."
        ),
        expressible=False,
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
            requirements=(_endpoints_req(facts), _oee_mapping_req(facts)),
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
