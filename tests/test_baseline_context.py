"""A band per regime — and the fallback that must never happen.

One band per tag is wrong the moment a tag has more than one normal: a dryer at
180 °C on recipe A and 240 °C on recipe B gets a band spanning both, after which
neither regime can go wrong. Learning per declared context fixes that, and
introduces exactly one temptation worth guarding against.

**The reading whose context was never learned.** Comparing it against the global
band, or the nearest one, makes the output look complete — and turns "we have
never seen this regime" into "this regime is normal". That is a silent pass in
the flattering direction, so most of this file is about it not happening.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.baseline_context import (
    MAX_CONTEXTS,
    STATUS_UNKNOWN_CONTEXT,
    check_in_context,
    learn_contextual_baselines,
)

pytestmark = pytest.mark.unit


def _rows(context, base, n=200, start_day=1):
    """n samples in one context, spanning >1 day so the learner is satisfied."""
    return [
        {
            "ts": f"2026-01-{start_day + i // 120:02d}T{(i // 5) % 24:02d}:{(i * 7) % 60:02d}:00Z",
            "tag": "dryer.temp",
            "value": base + (i % 5) * 0.5,
            "quality": "good",
            "context": context,
        }
        for i in range(n)
    ]


def _learned():
    return learn_contextual_baselines(
        _rows("recipe-A", 180.0) + _rows("recipe-B", 240.0), "dryer.temp"
    )


# ─── learning per context ────────────────────────────────────────────────────


def test_two_regimes_learn_two_separate_bands():
    out = _learned()
    assert out["learned_contexts"] == ["recipe-A", "recipe-B"]
    a = out["contexts"]["recipe-A"]["band"]
    b = out["contexts"]["recipe-B"]["band"]
    assert a["median"] == pytest.approx(181.0, abs=1.5)
    assert b["median"] == pytest.approx(241.0, abs=1.5)
    # the whole point: neither band spans the other regime
    assert a["p99"] < b["p1"]


def test_a_thin_context_refuses_instead_of_borrowing():
    """It is held to the same evidence bar as a global baseline."""
    out = learn_contextual_baselines(
        _rows("recipe-A", 180.0) + _rows("recipe-C", 300.0, n=4), "dryer.temp"
    )
    assert out["learned_contexts"] == ["recipe-A"]
    assert out["refused_contexts"] == ["recipe-C"]
    assert out["contexts"]["recipe-C"]["status"] == "insufficient_data"
    assert "band" not in out["contexts"]["recipe-C"]


def test_samples_without_a_context_are_named_not_pooled():
    """A default bucket is the same fallback wearing a different hat."""
    rows = _rows("recipe-A", 180.0) + [
        {"ts": "2026-01-01T00:00:00Z", "value": 999.0, "quality": "good"}
    ]
    out = learn_contextual_baselines(rows, "dryer.temp")
    assert out["uncontexted_samples"] == 1
    assert out["learned_contexts"] == ["recipe-A"]
    assert "" not in out["contexts"] and "default" not in out["contexts"]
    assert "no 'context' label" in out["note"]


def test_an_identifier_masquerading_as_a_context_is_refused():
    """One band per batch number is not a baseline."""
    rows = [
        {
            "ts": f"2026-01-01T00:{i:02d}:00Z",
            "value": 1.0,
            "quality": "good",
            "context": f"batch-{i}",
        }
        for i in range(MAX_CONTEXTS + 5)
    ]
    with pytest.raises(ValueError, match="identifier, not a"):
        learn_contextual_baselines(rows, "t")


def test_the_context_field_is_named_by_the_caller():
    rows = [{**r, "recipe": r.pop("context")} for r in _rows("recipe-A", 180.0)]
    out = learn_contextual_baselines(rows, "dryer.temp", context_key="recipe")
    assert out["context_key"] == "recipe"
    assert out["learned_contexts"] == ["recipe-A"]


# ─── checking: the fallback that must not happen ─────────────────────────────


def test_a_reading_in_an_unlearned_context_is_never_compared_to_another_band():
    out = check_in_context(
        [{"ts": "2026-02-01T00:00:00Z", "value": 181.0}] * 5, _learned(), "recipe-Z"
    )
    assert out["status"] == STATUS_UNKNOWN_CONTEXT
    assert out["known_contexts"] == ["recipe-A", "recipe-B"]
    assert "violations" not in out
    assert "never been observed" in out["note"]


def test_a_reading_in_a_refused_context_says_why_it_refused():
    contextual = learn_contextual_baselines(
        _rows("recipe-A", 180.0) + _rows("recipe-C", 300.0, n=4), "dryer.temp"
    )
    out = check_in_context([{"ts": "2026-02-01T00:00:00Z", "value": 300.0}], contextual, "recipe-C")
    assert out["status"] == STATUS_UNKNOWN_CONTEXT
    assert "refused to learn" in out["reason"]


def test_a_reading_normal_for_its_own_regime_is_not_flagged():
    """recipe-B's 240 °C would be far outside recipe-A's band."""
    out = check_in_context(
        [{"ts": f"2026-02-01T00:{i:02d}:00Z", "value": 240.5} for i in range(6)],
        _learned(),
        "recipe-B",
    )
    assert out["status"] == "ok"
    assert out["context"] == "recipe-B"


def test_an_excursion_within_a_regime_is_still_caught():
    """The complement: per-context bands must not be so wide they catch nothing."""
    out = check_in_context(
        [{"ts": f"2026-02-01T00:{i:02d}:00Z", "value": 260.0} for i in range(6)],
        _learned(),
        "recipe-B",
    )
    assert out["status"] == "violation"
    assert out["violations"]


def test_the_single_band_this_replaces_would_have_missed_it():
    """Evidence the feature is worth having, not just that it runs.

    A global band over both regimes spans 180–241, so 260 sits only a little
    outside it while 200 — impossible for either recipe — sits comfortably
    inside. That is the failure mode: one band, two normals, neither checkable.
    """
    from iaiops.core.brain.baseline import check_against_baseline, learn_baseline

    mixed = learn_baseline(_rows("recipe-A", 180.0) + _rows("recipe-B", 240.0), "dryer.temp")
    assert mixed["status"] == "ok"
    global_out = check_against_baseline(
        [{"ts": f"2026-02-01T00:{i:02d}:00Z", "value": 200.0} for i in range(6)], mixed
    )
    assert global_out["status"] == "ok", "200 °C is impossible for either recipe"

    per_context = check_in_context(
        [{"ts": f"2026-02-01T00:{i:02d}:00Z", "value": 200.0} for i in range(6)],
        _learned(),
        "recipe-A",
    )
    assert per_context["status"] == "violation", "and per-context, it is caught"


def test_check_requires_a_contextual_result():
    with pytest.raises(ValueError, match="learn_contextual_baselines"):
        check_in_context([], {"band": {}}, "x")
