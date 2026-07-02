"""Conservative per-tag baseline learning — "change-log baseline", PURE.

This is explicitly **NOT black-box anomaly detection** (docs/MARKET-INSIGHTS.md
R6: anomaly detection is noise unless zero-false-positive). It learns a per-tag
*normal band* from the site's OWN history — robust percentiles (p1/p99) plus
median/MAD, no ML dependencies — and then stays silent unless a value is beyond
that band by a conservative margin AND sustained over several consecutive
samples. Every flag cites the baseline samples it was judged against (window,
sample count, band values) and the offending samples' timestamps/values.

Honesty conventions (same spirit as :mod:`rca_weights`):

  * **refuses to learn** from thin history — below ``min_samples`` or a window
    shorter than ``min_span_s`` it returns an explicit ``insufficient_data``
    verdict listing exactly what is missing, instead of a shaky band;
  * **change-log aware** — operators record process changes (setpoint moved,
    valve replaced); learning restarts at the latest recorded change so the
    band never mixes pre-change and post-change regimes;
  * **no single-sample flags** — one spike is a glitch until proven otherwise.

Pure and deterministic: same samples → same band; inputs are never mutated.
Persistence lives in :mod:`iaiops.core.brain.baseline_store`.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from iaiops.core.brain._shared import num, s
from iaiops.core.brain.diagnostics import _parse_ts

DEFAULT_MIN_SAMPLES = 100      # below this many usable samples ⇒ refuse to learn
DEFAULT_MIN_SPAN_S = 86_400.0  # below this history span (1 day) ⇒ refuse to learn
DEFAULT_MARGIN_MAD = 3.0       # violation only beyond p1/p99 by > this × MAD
DEFAULT_SUSTAIN_N = 3          # ...AND for at least this many consecutive samples
MAX_SAMPLES = 100_000          # hard input bound (pure fn still bounds its work)
MAX_VIOLATIONS = 10            # violations reported per check (bounded output)
MAX_CITED_SAMPLES = 20         # offending samples cited per violation (bounded)

# Statuses a tag can be in — the vocabulary `baseline_status` never guesses past.
STATUS_NO_BASELINE = "no_baseline"
STATUS_LEARNING = "learning"
STATUS_OK = "ok"
STATUS_VIOLATION = "violation"


@dataclass(frozen=True)
class BaselineThresholds:
    """Immutable learning/checking thresholds (the conservative knobs)."""

    min_samples: int = DEFAULT_MIN_SAMPLES
    min_span_s: float = DEFAULT_MIN_SPAN_S
    margin_mad: float = DEFAULT_MARGIN_MAD
    sustain_n: int = DEFAULT_SUSTAIN_N


# ─── learning ─────────────────────────────────────────────────────────────────


def learn_baseline(
    samples: list[dict],
    tag: str,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_span_s: float = DEFAULT_MIN_SPAN_S,
    changes: list[dict] | None = None,
) -> dict:
    """[PURE] Learn a conservative per-tag normal band from the tag's own history.

    ``samples`` are local-store rows (``{ts, value, quality?, tag?, ...}``); only
    numeric, good-quality, timestamped samples for ``tag`` are used. ``changes``
    is the operator change log (``[{ts, note}]``): learning is segmented at the
    LATEST recorded change, so the band reflects only the post-change regime.

    Returns ``{status: "ok", tag, band:{p1, p99, median, mad}, n_samples,
    window:{from_ts, to_ts, span_s}, segment, note}`` — or an explicit
    ``{status: "insufficient_data", missing:[...]}`` refusal when the history is
    below ``min_samples`` usable samples or spans less than ``min_span_s``
    seconds. It never invents a band from thin data.
    """
    label = _require_tag(tag)
    usable, skipped = _usable_samples(samples, label)
    segment = _segment_after_latest_change(usable, changes)
    rows = segment["rows"]
    span = _span_s(rows)
    missing = _whats_missing(rows, span, max(1, int(min_samples)), float(min_span_s))
    if missing:
        return {
            "status": "insufficient_data",
            "tag": label,
            "n_samples": len(rows),
            "span_s": span,
            "skipped_samples": skipped,
            "segment": segment["info"],
            "missing": missing,
            "note": "Refusing to learn a band from thin history — a baseline "
            "built on too little data would flag noise (R6: zero false "
            "positives or it is not worth shipping).",
        }
    values = [r["value"] for r in rows]
    band = _robust_band(values)
    return {
        "status": "ok",
        "tag": label,
        "band": band,
        "n_samples": len(rows),
        "skipped_samples": skipped,
        "window": {
            "from_ts": rows[0]["ts"],
            "to_ts": rows[-1]["ts"],
            "span_s": span,
        },
        "segment": segment["info"],
        "note": "Robust band from the tag's own history (p1/p99 + median/MAD, "
        "no ML). Checks flag ONLY sustained excursions beyond the band by a "
        "conservative MAD margin, and every flag cites these baseline samples.",
    }


def _require_tag(tag: Any) -> str:
    label = s(tag, 128).strip()
    if not label:
        raise ValueError("tag is required — name the tag to learn/check, e.g. 'line1.temp'.")
    return label


def _usable_samples(samples: Any, tag: str) -> tuple[list[dict], int]:
    """Numeric, good-quality, timestamped samples for ``tag``, sorted by time.

    Rows carrying a different ``tag`` label are excluded; rows without a tag
    label are assumed to belong to the requested tag (pre-filtered input).
    Returns ``(rows, skipped_count)`` — honesty about what was dropped.
    """
    if not isinstance(samples, list):
        raise ValueError("samples must be a list of {ts, value, ...} rows.")
    rows: list[dict] = []
    skipped = 0
    for raw in samples[:MAX_SAMPLES]:
        row = _usable_row(raw, tag)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    rows.sort(key=lambda r: r["_dt"])
    return rows, skipped


def _usable_row(raw: Any, tag: str) -> dict | None:
    """One validated ``{ts, _dt, value}`` row, or None when unusable."""
    if not isinstance(raw, dict):
        return None
    row_tag = s(raw.get("tag", ""), 128).strip()
    if row_tag and row_tag != tag:
        return None
    if _is_bad_quality(raw.get("quality")):
        return None
    value = num(raw.get("value"))
    ts_raw = raw.get("ts", raw.get("timestamp"))
    dt = _parse_ts(ts_raw)
    if value is None or dt is None:
        return None
    return {"ts": s(ts_raw, 40), "_dt": dt, "value": value}


def _is_bad_quality(quality: Any) -> bool:
    """Conservative learning excludes samples the source itself flagged BAD."""
    return s(quality, 48).strip().lower().startswith("bad")


def _segment_after_latest_change(rows: list[dict], changes: Any) -> dict:
    """Keep only samples AFTER the latest recorded change point (if any).

    A recorded change (setpoint moved, instrument swapped) invalidates the prior
    regime; the band must be learned from the segment after it. Returns
    ``{rows, info}`` where ``info`` explains the segmentation applied.
    """
    latest: datetime | None = None
    latest_note = ""
    for change in changes or []:
        if not isinstance(change, dict):
            continue
        dt = _parse_ts(change.get("ts"))
        if dt is not None and (latest is None or dt > latest):
            latest = dt
            latest_note = s(change.get("note", ""), 200)
    if latest is None:
        return {"rows": rows, "info": {"segmented": False, "changes_considered": 0}}
    kept = [r for r in rows if r["_dt"] > latest]
    return {
        "rows": kept,
        "info": {
            "segmented": True,
            "changes_considered": len(changes or []),
            "after_change_ts": latest.isoformat(),
            "change_note": latest_note,
            "samples_before_change_excluded": len(rows) - len(kept),
        },
    }


def _span_s(rows: list[dict]) -> float:
    if len(rows) < 2:
        return 0.0
    return round((rows[-1]["_dt"] - rows[0]["_dt"]).total_seconds(), 3)


def _whats_missing(
    rows: list[dict], span: float, min_samples: int, min_span_s: float
) -> list[str]:
    """Explicit, teaching list of what the history still lacks (refusal detail)."""
    missing: list[str] = []
    if len(rows) < min_samples:
        missing.append(
            f"need >= {min_samples} usable samples, have {len(rows)} "
            f"({min_samples - len(rows)} more required)"
        )
    if span < min_span_s:
        missing.append(
            f"need >= {min_span_s:.0f}s of history span, have {span:.0f}s "
            f"({min_span_s - span:.0f}s more required)"
        )
    return missing


def _robust_band(values: list[float]) -> dict:
    """p1/p99 + median + MAD — robust, explainable, no ML dependencies."""
    ordered = sorted(values)
    med = statistics.median(ordered)
    mad = statistics.median(sorted(abs(v - med) for v in ordered))
    return {
        "p1": round(_percentile(ordered, 1.0), 6),
        "p99": round(_percentile(ordered, 99.0), 6),
        "median": round(med, 6),
        "mad": round(mad, 6),
    }


def _percentile(ordered: list[float], pct: float) -> float:
    """Linear-interpolated percentile over a pre-sorted list."""
    if not ordered:
        raise ValueError("cannot take a percentile of no values")
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


# ─── checking ─────────────────────────────────────────────────────────────────


def check_against_baseline(
    samples: list[dict],
    baseline: dict,
    margin_mad: float = DEFAULT_MARGIN_MAD,
    sustain_n: int = DEFAULT_SUSTAIN_N,
) -> dict:
    """[PURE] Check fresh samples against a learned band — conservative by design.

    A violation is reported ONLY when values are beyond the band (above p99 or
    below p1) by more than ``margin_mad`` × MAD, AND sustained for at least
    ``sustain_n`` consecutive samples — a single spike is never flagged. Every
    violation cites the baseline window (from/to ts, n samples), the band values
    it was judged against, and the offending samples' timestamps/values.

    Returns ``{status: "ok"|"violation", tag, checked_samples, thresholds,
    baseline_citation, violations:[...]}``. ``baseline`` must be a successful
    :func:`learn_baseline` result (``status == "ok"``).
    """
    band, citation, tag = _validate_baseline(baseline)
    sustain = max(2, int(sustain_n))  # a "sustained" excursion is >= 2 by definition
    margin = max(0.0, float(margin_mad)) * band["mad"]
    high = band["p99"] + margin
    low = band["p1"] - margin
    rows, _skipped = _usable_samples(samples, tag)
    runs = _sustained_runs(rows, low, high, sustain)
    violations = [_cite_violation(run, band, citation, low, high) for run in runs]
    return {
        "status": STATUS_VIOLATION if violations else STATUS_OK,
        "tag": tag,
        "checked_samples": len(rows),
        "thresholds": {
            "low": round(low, 6),
            "high": round(high, 6),
            "margin_mad": float(margin_mad),
            "sustain_n": sustain,
        },
        "baseline_citation": citation,
        "violations": violations[:MAX_VIOLATIONS],
        "violations_truncated": len(violations) > MAX_VIOLATIONS,
        "note": "Silent by default: values inside the band — or beyond it but "
        "unsustained (< sustain_n consecutive samples) — are NOT flagged.",
    }


def _validate_baseline(baseline: Any) -> tuple[dict, dict, str]:
    """Boundary check: require a successful learn_baseline result shape."""
    if not isinstance(baseline, dict) or baseline.get("status") != "ok":
        raise ValueError(
            "baseline must be a successful learn_baseline result (status='ok'). "
            "Learn one first — and if learning refused (insufficient_data), "
            "collect more history instead of checking against a guess."
        )
    band = baseline.get("band")
    window = baseline.get("window")
    if not isinstance(band, dict) or not isinstance(window, dict):
        raise ValueError("baseline is malformed: missing 'band'/'window'. Re-learn it.")
    values = {k: num(band.get(k)) for k in ("p1", "p99", "median", "mad")}
    if any(v is None for v in values.values()):
        raise ValueError("baseline band must carry numeric p1/p99/median/mad. Re-learn it.")
    citation = {
        "window_from": s(window.get("from_ts"), 40),
        "window_to": s(window.get("to_ts"), 40),
        "n_samples": int(baseline.get("n_samples") or 0),
        "band": {k: float(v) for k, v in values.items() if v is not None},
    }
    return citation["band"], citation, s(baseline.get("tag", ""), 128)


def _sustained_runs(
    rows: list[dict], low: float, high: float, sustain_n: int
) -> list[list[dict]]:
    """Consecutive out-of-band runs of length >= sustain_n (same direction)."""
    runs: list[list[dict]] = []
    current: list[dict] = []
    direction = ""
    for row in rows:
        side = "above" if row["value"] > high else ("below" if row["value"] < low else "")
        if side and side == direction:
            current.append(row)
        elif side:
            _flush_run(runs, current, sustain_n)
            current, direction = [row], side
        else:
            _flush_run(runs, current, sustain_n)
            current, direction = [], ""
    _flush_run(runs, current, sustain_n)
    return runs


def _flush_run(runs: list[list[dict]], current: list[dict], sustain_n: int) -> None:
    if len(current) >= sustain_n:
        runs.append(list(current))


def _cite_violation(
    run: list[dict], band: dict, citation: dict, low: float, high: float
) -> dict:
    """One fully-cited violation: baseline window + band + offending samples."""
    above = run[0]["value"] > high
    return {
        "direction": "above" if above else "below",
        "beyond": round(band["p99"] if above else band["p1"], 6),
        "threshold": round(high if above else low, 6),
        "consecutive_samples": len(run),
        "from_ts": run[0]["ts"],
        "to_ts": run[-1]["ts"],
        "samples": [
            {"ts": r["ts"], "value": round(r["value"], 6)} for r in run[:MAX_CITED_SAMPLES]
        ],
        "samples_truncated": len(run) > MAX_CITED_SAMPLES,
        "baseline": citation,
    }


# ─── status classification ────────────────────────────────────────────────────


def classify_status(record: dict | None) -> str:
    """[PURE] Classify a stored tag record — never guesses.

    ``no_baseline``: nothing learned and no refused learn attempt on record;
    ``learning``: the last learn attempt refused (insufficient_data) — still
    accumulating history; ``ok``: a band exists and the last recorded check (if
    any) found nothing; ``violation``: the last recorded check flagged a
    sustained excursion.
    """
    if not isinstance(record, dict):
        return STATUS_NO_BASELINE
    baseline = record.get("baseline")
    if isinstance(baseline, dict) and baseline.get("status") == "ok":
        last_check = record.get("last_check")
        if isinstance(last_check, dict) and last_check.get("status") == STATUS_VIOLATION:
            return STATUS_VIOLATION
        return STATUS_OK
    last_learn = record.get("last_learn")
    if isinstance(last_learn, dict) and last_learn.get("status") == "insufficient_data":
        return STATUS_LEARNING
    return STATUS_NO_BASELINE


__all__ = [
    "BaselineThresholds",
    "learn_baseline",
    "check_against_baseline",
    "classify_status",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_MIN_SPAN_S",
    "DEFAULT_MARGIN_MAD",
    "DEFAULT_SUSTAIN_N",
    "MAX_SAMPLES",
    "STATUS_NO_BASELINE",
    "STATUS_LEARNING",
    "STATUS_OK",
    "STATUS_VIOLATION",
]
