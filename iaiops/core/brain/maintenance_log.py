"""Maintenance-log → RCA corpus bridge (pure, advisory).

Closes the ``learn_cause_weights`` follow-up in ``docs/ROADMAP.md``: a site's
CMMS / work-order export is the natural labeled-incident history, but its rows
name causes in free vendor/site vocabulary ("bearing failure", "网络中断"), not
the copilot's cause taxonomy. This module normalizes such rows into the
``[{cause, signals}]`` corpus that ``learn_cause_weights`` consumes:

1. an explicit cause column that already uses the taxonomy wins;
2. else a synonym table (built-in EN/中文 CMMS vocabulary + caller overrides);
3. else keyword inference over the row's free text — using the SAME
   ``CAUSE_KEYWORDS`` the RCA core cites, and only when the match is
   UNAMBIGUOUS (one candidate cause). Ambiguous or unmatchable rows are
   returned in ``unmapped`` with the reason — never silently guessed.

``signals`` (what the evidence pointed at) come from an explicit column when
present, else from the row's *symptom/alarm* text via the same keywords; a row
with no inferable signals keeps ``signals=[]`` (it still counts toward corpus
size but adds no signal support — honest, no fabricated evidence).

Pure functions only — file/CSV handling lives in the CLI.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain.rca import CAUSE_KEYWORDS
from iaiops.core.brain.rca_weights import LEARNABLE_CAUSES, learn_cause_weights
from iaiops.core.runtime.envelope import envelope_fields

MAX_ROWS = 5000  # defensive bound for agent-supplied payloads
_EXCERPT = 120

# Row keys tried (in order) for the confirmed cause and for descriptive text.
CAUSE_FIELDS: tuple[str, ...] = ("cause", "root_cause", "failure_class", "category", "problem_code")
TEXT_FIELDS: tuple[str, ...] = ("description", "problem", "notes", "comment", "text", "故障描述")
SIGNAL_TEXT_FIELDS: tuple[str, ...] = ("symptom", "symptoms", "alarm", "alarms", "现象")

# Common CMMS vocabulary → taxonomy cause. Deliberately small and unambiguous;
# anything fuzzier falls through to keyword inference or lands in ``unmapped``.
_SYNONYMS: dict[str, str] = {
    # mechanical
    "bearing failure": "mechanical_fault",
    "mechanical failure": "mechanical_fault",
    "motor fault": "mechanical_fault",
    "机械故障": "mechanical_fault",
    "轴承损坏": "mechanical_fault",
    "电机故障": "mechanical_fault",
    # comms
    "communication loss": "comms_loss",
    "network down": "comms_loss",
    "plc offline": "comms_loss",
    "通讯故障": "comms_loss",
    "网络中断": "comms_loss",
    "掉线": "comms_loss",
    # sensor
    "sensor failure": "sensor_fault",
    "bad sensor": "sensor_fault",
    "传感器故障": "sensor_fault",
    "探头故障": "sensor_fault",
    # material
    "no material": "material_starvation",
    "material shortage": "material_starvation",
    "缺料": "material_starvation",
    "断料": "material_starvation",
    # quality
    "quality issue": "quality_reject",
    "out of spec": "quality_reject",
    "质量不良": "quality_reject",
    "不良品": "quality_reject",
    # changeover
    "product changeover": "changeover",
    "tool change": "changeover",
    "换型": "changeover",
    "换模": "changeover",
    # utility
    "power failure": "utility_fault",
    "power outage": "utility_fault",
    "compressed air": "utility_fault",
    "停电": "utility_fault",
    "断气": "utility_fault",
    "断水": "utility_fault",
}


def _norm(text: Any) -> str:
    return str(text or "").strip().lower()


def _causes_in_text(text: str) -> set[str]:
    """Every taxonomy cause whose keywords appear in ``text`` (already lowercased)."""
    return {
        cause for cause, keywords in CAUSE_KEYWORDS.items() if any(kw in text for kw in keywords)
    }


def _resolve_cause(row: dict, synonyms: dict[str, str]) -> tuple[str, str]:
    """Return ``(cause, how)`` or ``("", reason)`` for one row — never guesses."""
    for field in CAUSE_FIELDS:
        raw = _norm(row.get(field))
        if not raw:
            continue
        if raw in LEARNABLE_CAUSES:
            return raw, f"explicit '{field}'"
        if raw in synonyms:
            return synonyms[raw], f"synonym '{raw}'"
    text = " ".join(_norm(row.get(f)) for f in TEXT_FIELDS if row.get(f))
    if not text:
        return "", "no cause column matched and no descriptive text to infer from"
    candidates = _causes_in_text(text)
    if len(candidates) == 1:
        return next(iter(candidates)), "keyword inference (unambiguous)"
    if not candidates:
        return "", "no taxonomy keyword found in the descriptive text"
    return "", f"ambiguous — text matches {sorted(candidates)}; add a synonym or explicit cause"


def _resolve_signals(row: dict) -> list[str]:
    """Signals from an explicit column, else from symptom/alarm text (may be [])."""
    raw = row.get("signals")
    if isinstance(raw, (list, tuple)):
        return [s for s in (_norm(x) for x in raw) if s in LEARNABLE_CAUSES]
    text = " ".join(_norm(row.get(f)) for f in SIGNAL_TEXT_FIELDS if row.get(f))
    return sorted(_causes_in_text(text)) if text else []


def corpus_from_maintenance_log(
    rows: Any,
    synonyms: dict[str, str] | None = None,
    learn: bool = True,
    min_samples: int = 8,
    smoothing: float = 1.0,
) -> dict:
    """[PURE] Normalize CMMS/work-order rows into the RCA incident corpus.

    ``rows`` is a list of dicts (one per closed work order). ``synonyms`` extends
    the built-in vocabulary (``{"spindle crash": "mechanical_fault"}``); values
    must be taxonomy causes. With ``learn=True`` the mapped corpus is fed
    straight to ``learn_cause_weights`` and the result is included as ``weights``.

    Returns dict: {corpus, n_rows, n_mapped, unmapped:[{row, reason, excerpt}],
    mapped_via:{how: count}, weights?, next_step}.
    """
    if not isinstance(rows, list):
        raise ValueError(
            "rows must be a list of work-order dicts (one per closed maintenance "
            f"record); got {type(rows).__name__}."
        )
    extra = {}
    for key, value in (synonyms or {}).items():
        cause = _norm(value)
        if cause not in LEARNABLE_CAUSES:
            raise ValueError(
                f"synonyms[{key!r}] = {value!r} is not a taxonomy cause; valid causes: "
                f"{sorted(LEARNABLE_CAUSES)}."
            )
        extra[_norm(key)] = cause
    merged = {**_SYNONYMS, **extra}

    corpus: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    mapped_via: dict[str, int] = {}
    for i, row in enumerate(rows[:MAX_ROWS]):
        if not isinstance(row, dict):
            unmapped.append({"row": i, "reason": "not a dict", "excerpt": str(row)[:_EXCERPT]})
            continue
        cause, how = _resolve_cause(row, merged)
        if not cause:
            excerpt = " ".join(str(row.get(f)) for f in (*CAUSE_FIELDS, *TEXT_FIELDS) if row.get(f))
            unmapped.append({"row": i, "reason": how, "excerpt": excerpt[:_EXCERPT]})
            continue
        via = how.split(" '")[0]
        mapped_via[via] = mapped_via.get(via, 0) + 1
        corpus.append({"cause": cause, "signals": _resolve_signals(row)})

    result: dict[str, Any] = {
        "corpus": corpus,
        "n_rows": min(len(rows), MAX_ROWS),
        "n_mapped": len(corpus),
        "unmapped": unmapped,
        "mapped_via": mapped_via,
        "next_step": (
            "Feed 'corpus' to learn_cause_weights (or use the included 'weights') and "
            "pass the resulting cause_weights to downtime_root_cause. Review 'unmapped' "
            "rows — add synonyms for recurring site vocabulary rather than relabeling "
            "by hand."
        ),
        # Standard return envelope — always present, so a reader never has to
        # infer completeness from the ABSENCE of the legacy 'truncated' key.
        **envelope_fields(returned=min(len(rows), MAX_ROWS), total=len(rows)),
    }
    if len(rows) > MAX_ROWS:
        # Legacy key: a STRING, not a bool. Kept verbatim for published
        # consumers; `is_truncated` above is the unambiguous boolean.
        result["truncated"] = f"only the first {MAX_ROWS} of {len(rows)} rows were processed"
    if learn:
        result["weights"] = learn_cause_weights(corpus, min_samples, smoothing)
    return result


__all__ = ["corpus_from_maintenance_log", "CAUSE_FIELDS", "TEXT_FIELDS", "SIGNAL_TEXT_FIELDS"]
