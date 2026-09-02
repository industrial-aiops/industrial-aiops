"""One band per tag is wrong the moment the tag has more than one normal.

:mod:`iaiops.core.brain.baseline` learns ONE robust band per tag, segmented only
at the latest operator change. An OT normal range moves with context — shift,
product or recipe, start-up versus steady state — so a single band is either too
wide to catch a real excursion or too mixed to learn at all. A dryer running
recipe A at 180 °C and recipe B at 240 °C gets a band spanning both, and then
neither regime can go wrong.

So: learn per context, and locate the context before comparing.

**The context is declared, never inferred** (D16). Each sample carries a label
under a field the caller names; nothing here guesses which shift a timestamp
belongs to or clusters values into regimes it then treats as real. Two facts
follow, and they are the reason this is safe to ship:

* a context whose history is thin **refuses to learn**, exactly as the global
  learner does — it does not borrow the other contexts' samples;
* a reading whose context has no band is ``unknown_context``, **not** compared
  against some other band. Falling back to a global band is the tempting move
  and the wrong one: it renders "we have never seen this regime" as "this regime
  is normal", which is the flattering direction and the one nobody reports.

Samples carrying no context label are counted and named, not swept into a
default bucket — a default bucket is the same fallback wearing a different hat.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.brain._shared import s
from iaiops.core.brain.baseline import (
    DEFAULT_MARGIN_MAD,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_MIN_SPAN_S,
    DEFAULT_SUSTAIN_N,
    MAX_SAMPLES,
    check_against_baseline,
    learn_baseline,
)

#: Field a sample carries its declared context label in, unless the caller says
#: otherwise. Never derived from the timestamp or the value.
DEFAULT_CONTEXT_KEY = "context"

#: Upper bound on distinct contexts learned in one call. More than this and the
#: "context" is almost certainly an identifier (a batch id), not a regime — which
#: would learn one band per sample and call it a baseline.
MAX_CONTEXTS = 50

STATUS_UNKNOWN_CONTEXT = "unknown_context"


def context_of(sample: Any, context_key: str) -> str:
    """The sample's declared context label, or '' when it carries none."""
    if not isinstance(sample, dict):
        return ""
    return s(sample.get(context_key, ""), 96).strip()


def learn_contextual_baselines(
    samples: list[dict],
    tag: str,
    context_key: str = DEFAULT_CONTEXT_KEY,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_span_s: float = DEFAULT_MIN_SPAN_S,
    changes: list[dict] | None = None,
) -> dict[str, Any]:
    """[PURE] Learn one conservative band per declared context.

    ``samples`` are local-store rows that additionally carry ``context_key``.
    Each context is handed to :func:`~iaiops.core.brain.baseline.learn_baseline`
    unchanged, so a context is held to exactly the same evidence bar as a global
    baseline — and refuses on the same terms.
    """
    if not isinstance(samples, list):
        raise ValueError("samples must be a list of {ts, value, context, ...} rows.")
    key = s(context_key, 64).strip()
    if not key:
        raise ValueError("context_key is required — name the field that declares the context.")

    buckets: dict[str, list[dict]] = {}
    uncontexted = 0
    for row in samples[:MAX_SAMPLES]:
        label = context_of(row, key)
        if not label:
            uncontexted += 1
            continue
        buckets.setdefault(label, []).append(row)

    if len(buckets) > MAX_CONTEXTS:
        raise ValueError(
            f"{len(buckets)} distinct values of {key!r} — that is an identifier, not a "
            f"regime (limit {MAX_CONTEXTS}). One band per batch number is not a baseline; "
            "bucket by something a process engineer would name, like shift or recipe."
        )

    contexts = {
        label: learn_baseline(
            rows, tag, min_samples=min_samples, min_span_s=min_span_s, changes=changes
        )
        for label, rows in sorted(buckets.items())
    }
    learned = sorted(k for k, v in contexts.items() if v.get("status") == "ok")
    refused = sorted(k for k, v in contexts.items() if v.get("status") != "ok")

    return {
        "tag": s(tag, 128).strip(),
        "context_key": key,
        "contexts": contexts,
        "learned_contexts": learned,
        "refused_contexts": refused,
        "uncontexted_samples": uncontexted,
        "note": (
            f"{len(learned)} of {len(contexts)} context(s) had enough history to learn a band. "
            "A refused context is left without one rather than borrowing another context's "
            "samples, and a reading in it will be reported as unknown_context — never "
            "compared against a band learned somewhere else."
            + (
                f" {uncontexted} sample(s) carried no {key!r} label and were not learned from; "
                "they are named rather than pooled into a default bucket."
                if uncontexted
                else ""
            )
        ),
    }


def check_in_context(
    samples: list[dict],
    contextual: dict,
    context: str,
    margin_mad: float = DEFAULT_MARGIN_MAD,
    sustain_n: int = DEFAULT_SUSTAIN_N,
) -> dict[str, Any]:
    """[PURE] Check fresh samples against the band for ONE declared context.

    An unlearned context returns :data:`STATUS_UNKNOWN_CONTEXT` and stops there.
    That is the whole point of the module: the alternative — quietly using the
    global or nearest band — reports "we have never seen this regime" as "this
    regime is normal".
    """
    if not isinstance(contextual, dict) or "contexts" not in contextual:
        raise ValueError("contextual must be a learn_contextual_baselines() result.")
    label = s(context, 96).strip()
    known = contextual.get("learned_contexts") or []
    baseline = (contextual.get("contexts") or {}).get(label)

    if baseline is None or baseline.get("status") != "ok":
        reason = (
            f"No band was learned for context {label!r}."
            if baseline is None
            else f"Context {label!r} exists but refused to learn: "
            f"{'; '.join(baseline.get('missing') or ['thin history'])}."
        )
        return {
            "status": STATUS_UNKNOWN_CONTEXT,
            "tag": contextual.get("tag", ""),
            "context": label,
            "context_key": contextual.get("context_key", DEFAULT_CONTEXT_KEY),
            "known_contexts": list(known),
            "checked_samples": len([r for r in (samples or []) if isinstance(r, dict)]),
            "reason": reason,
            "note": (
                "Not compared against another context's band on purpose. Borrowing one "
                "would turn 'this regime has never been observed' into 'this regime is "
                "normal' — a silent pass, in the direction nobody reports. Collect this "
                "context's own history, or check it against the global baseline "
                "explicitly if that is genuinely what you mean."
            ),
        }

    out = check_against_baseline(samples, baseline, margin_mad=margin_mad, sustain_n=sustain_n)
    return {**out, "context": label, "context_key": contextual.get("context_key")}


__all__ = [
    "DEFAULT_CONTEXT_KEY",
    "MAX_CONTEXTS",
    "STATUS_UNKNOWN_CONTEXT",
    "check_in_context",
    "context_of",
    "learn_contextual_baselines",
]
