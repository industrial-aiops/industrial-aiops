"""The named computations the determinism check runs over the reference dataset.

One entry per analysis a customer actually reads a number out of. Each is a pure
call into :mod:`iaiops.core.brain` over :mod:`iaiops.core.verify.dataset` — no
device, no store, no clock, no network.

Adding a check here widens the guarantee; it also moves that check's digest, and
only that one, so a recorded run stays comparable on everything it already
covered. Removing one narrows the guarantee silently, which is why the CLI
prints the check names beside the digests rather than only the total.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from iaiops.core.verify import dataset as ds


@dataclass(frozen=True)
class Check:
    """One named, reproducible computation over the reference dataset."""

    name: str
    #: What a reader of the record should understand this digest to cover.
    covers: str
    fn: Callable[[], Any]


def _run_state_tag():
    from iaiops.core.runtime.config import MonitorTag, TagRole

    return MonitorTag(
        ref="ns=2;i=40",
        label="line run state",
        role=TagRole.RUN_STATE,
        running_when=(ds.RUNNING_VALUE,),
    )


def _window() -> tuple[str, str]:
    from datetime import timedelta

    return (
        ds.EPOCH.isoformat(),
        (ds.EPOCH + timedelta(seconds=ds.total_span_s())).isoformat(),
    )


def availability() -> Any:
    from iaiops.core.brain.oee_measure import measure_availability

    return measure_availability(ds.run_state_samples(), _run_state_tag(), window=_window())


def production() -> Any:
    from iaiops.core.brain.oee_production import count_production

    measured = availability()
    return count_production(ds.total_count_samples(), blind_windows=measured.get("blind_windows"))


def losses() -> Any:
    from iaiops.core.brain.oee_losses import losses_from_measured
    from iaiops.core.brain.oee_production import count_production

    measured = availability()
    blind = measured.get("blind_windows")
    return losses_from_measured(
        measured,
        totals=count_production(ds.total_count_samples(), blind_windows=blind),
        goods=count_production(ds.good_count_samples(), blind_windows=blind),
        ideal_cycle_time_s=ds.IDEAL_CYCLE_TIME_S,
    )


def alarm_load() -> Any:
    from iaiops.core.brain.alarm_flood import alarm_flood_report

    return alarm_flood_report(ds.alarm_events())


def control_chart() -> Any:
    from iaiops.core.brain.spc import spc_check

    return spc_check(ds.measurement_series(), usl=12.0, lsl=8.0)


def conservative_baseline() -> Any:
    from iaiops.core.brain.baseline import learn_baseline

    return learn_baseline(ds.analogue_samples(), tag="ns=2;i=41")


def root_cause() -> Any:
    from iaiops.core.brain.rca import downtime_rca

    return downtime_rca(
        ds.incident_window(),
        alarms=ds.alarm_events(),
        tags=ds.incident_tags(),
        state_series=ds.run_state_samples(),
    )


#: The suite, in the order it is run and recorded.
CHECKS: tuple[Check, ...] = (
    Check(
        "availability", "Availability, blind-window accounting and minor stoppages", availability
    ),
    Check("production", "Counted parts, wrap/reset handling and unobserved steps", production),
    Check("losses", "The Six Big Losses ladder and the OEE factors", losses),
    Check("alarm_load", "ISA-18.2 flood episodes, chattering and load profile", alarm_load),
    Check(
        "control_chart", "Western Electric / Nelson rule violations and capability", control_chart
    ),
    Check(
        "conservative_baseline", "The learned normal band and its refusals", conservative_baseline
    ),
    Check("root_cause", "The RCA copilot's ranked hypotheses, grades and citations", root_cause),
)


def check_names() -> tuple[str, ...]:
    """Names of every check in the suite, in run order."""
    return tuple(c.name for c in CHECKS)


__all__ = ["CHECKS", "Check", "check_names"]
