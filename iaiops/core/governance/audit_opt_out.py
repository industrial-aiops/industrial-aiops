"""The one opt-out the audit trail allows: successful low/medium-risk calls.

CRA Annex I Part I(2)(l) asks that activity recording come "with an opt-out
mechanism for the user". The trail is also this product's governance backbone,
so the opt-out is deliberately narrow:

* ``IAIOPS_AUDIT_OPT_OUT=reads`` — the only accepted value — stops recording
  calls that are low/medium risk **and** succeeded;
* high/critical calls (device writes) are always recorded, and still fail closed
  when the trail cannot be written;
* denied and failed calls are always recorded — they are the security-relevant
  ones;
* the opt-out itself is written to the trail once per process, so the record
  shows from when reads went unrecorded.

Any other value keeps recording and warns: a typo must never switch the trail
off.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

_log = logging.getLogger("iaiops.audit")

OPT_OUT_ENV = "IAIOPS_AUDIT_OPT_OUT"
MARKER_TOOL = "audit_opt_out"
_SCOPE = "reads"
_OFF_VALUES = frozenset({"", "off", "none", "0", "no", "false"})
#: Mirrors decorators._FAIL_CLOSED_RISK; a test keeps the two equal.
ALWAYS_RECORDED_RISK = ("high", "critical")

_lock = threading.Lock()
_marked = False
_warned_values: frozenset[str] = frozenset()


def _requested() -> str:
    return os.environ.get(OPT_OUT_ENV, "").strip().lower()


def _warn_unknown_once(value: str) -> None:
    global _warned_values
    with _lock:
        if value in _warned_values:
            return
        _warned_values = _warned_values | {value}
    _log.warning(
        "%s=%r is not a recognised opt-out; the audit trail keeps recording "
        "everything. The only accepted value is %r (successful low/medium-risk "
        "calls).",
        OPT_OUT_ENV,
        value,
        _SCOPE,
    )


def opted_out() -> bool:
    """True when successful low/medium-risk calls should go unrecorded."""
    value = _requested()
    if value == _SCOPE:
        return True
    if value not in _OFF_VALUES:
        _warn_unknown_once(value)
    return False


def skips(risk_level: str, status: str) -> bool:
    """Whether this finished call's audit row is opted out."""
    return status == "ok" and risk_level not in ALWAYS_RECORDED_RISK and opted_out()


def mark_once(audit: Any) -> None:
    """Write the opt-out marker row the first time a row is skipped."""
    global _marked
    with _lock:
        if _marked:
            return
        _marked = True
    audit.log(
        skill="iaiops",
        tool=MARKER_TOOL,
        params={"scope": _SCOPE, "env": OPT_OUT_ENV},
        status="ok",
        risk_level="low",
        rationale="successful low/medium-risk calls are not recorded from here on "
        "(CRA Annex I Part I(2)(l) opt-out); high/critical, denied and failed calls "
        "still are",
    )


def status() -> dict[str, Any]:
    """The opt-out state, for doctor / evidence summaries."""
    on = opted_out()
    return {
        "opted_out": on,
        "scope": _SCOPE if on else "",
        "env": OPT_OUT_ENV,
        "always_recorded": [*ALWAYS_RECORDED_RISK, "denied", "failed"],
    }


def reset_for_tests() -> None:
    """Forget the once-per-process marker and warnings (tests only)."""
    global _marked, _warned_values
    with _lock:
        _marked = False
        _warned_values = frozenset()


__all__ = [
    "ALWAYS_RECORDED_RISK",
    "MARKER_TOOL",
    "OPT_OUT_ENV",
    "mark_once",
    "opted_out",
    "reset_for_tests",
    "skips",
    "status",
]
