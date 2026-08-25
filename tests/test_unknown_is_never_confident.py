"""A value that means "I do not know" must never render as a confident number.

An audit on 2026-08-25 found seven instances of one defect. Not seven bugs — one,
arriving through the single gap a comparison-based guard cannot close:

    min(100.0, nan) == 100.0

Every NaN comparison is False, so `min` keeps its first argument, `max` keeps its
first argument, and `<= 0` lets it past. The results, all reproduced before the
fix:

* `meter_svg(nan)` → a full green bar labelled **100.0%**, on the headline
  availability factor
* `stacked_bar_svg(total=nan)` → an empty chart whose legend claimed every loss
  was **100%** of planned time
* `humanize_seconds(nan)` → **"0ms"**, from the function whose own docstring warns
  against "misleading in the direction that makes a gap look like nothing"
* `humanize_seconds(None)` → `TypeError`, a family the CLI does not catch
* `pct_from_fraction(nan)` → **"nan%"** in a customer-facing report
* `int(nan)` / `int(inf)` → `ValueError` / `OverflowError`, the second uncaught
* a refused measurement rendered as a **table of zeros** that reads as measured

Three of those flatter. This is the class the codebase exists to refuse, and the
whole session's work was machinery for refusing it — which NaN then walked under.

The tests below are a PENETRATION SWEEP, not examples. Every public renderer gets
every flavour of "unknown", and the assertion is the same for all of them: no
confident number, no uncaught exception. That shape is deliberate — the reason
this class survived is that every existing fixture carried real numbers, so
nothing ever asked the question.
"""

from __future__ import annotations

import math

import pytest

from iaiops.core.report.fmt import (
    UNKNOWN,
    count,
    finite,
    humanize_seconds,
    pct_from_fraction,
    pct_from_percent,
    total,
)
from iaiops.core.report.strings import EN
from iaiops.core.report.svg import meter_svg, stacked_bar_svg

pytestmark = pytest.mark.unit

NAN = float("nan")
INF = float("inf")

#: Everything a caller can hand a renderer that means "I do not know". `""` and
#: `"n/a"` are in here because a store round-trip and a hand-written bundle both
#: produce them, and they used to raise rather than refuse.
UNKNOWNS = [NAN, INF, -INF, None, "", "n/a", [], {}]

#: Digits that must never appear in output derived from an unknown. `100` is the
#: specific lie the clamp produced; `0` is the other one — "we could not see it"
#: rendered as "it was zero".
FORBIDDEN_IN_OUTPUT = ("100.0%", "nan", "inf", "NaN", "Infinity")


class TestTheGuardItself:
    @pytest.mark.parametrize("value", UNKNOWNS)
    def test_every_flavour_of_unknown_collapses_to_none(self, value):
        assert finite(value) is None

    @pytest.mark.parametrize("value", [0, 0.0, -1, 1.5, "2.5", " 3 ", True, False])
    def test_a_real_number_survives(self, value):
        """The complement. A guard that rejected everything would pass the sweep
        above and make the product useless."""
        assert finite(value) is not None

    def test_it_uses_isfinite_not_a_comparison(self):
        """The whole point. `min`/`max`/`<=` cannot exclude NaN — that is how this
        class got in, and a re-implementation with comparisons would let it back."""
        assert math.isnan(NAN) and not (NAN <= 0) and min(100.0, NAN) == 100.0
        assert finite(NAN) is None


class TestNoRendererEverInventsANumber:
    @pytest.mark.parametrize("value", UNKNOWNS)
    @pytest.mark.parametrize(
        "render",
        [humanize_seconds, pct_from_fraction, pct_from_percent, count],
        ids=["humanize_seconds", "pct_from_fraction", "pct_from_percent", "count"],
    )
    def test_it_returns_the_dash_and_does_not_raise(self, render, value):
        assert render(value) == UNKNOWN

    @pytest.mark.parametrize("value", UNKNOWNS)
    def test_a_sum_with_one_unknown_addend_is_unknown(self, value):
        """Not the sum of the parts it happens to know. Treating an unknown addend
        as zero is how "we could not see part of this window" becomes "there was no
        blind time"."""
        assert total(10.0, value, 5.0) is None

    def test_a_sum_of_known_addends_is_the_sum(self):
        assert total(10.0, 5.0) == pytest.approx(15.0)


class TestTheChartsRefuseRatherThanFill:
    @pytest.mark.parametrize("value", UNKNOWNS)
    def test_a_meter_shows_its_refusal(self, value):
        """`fraction is None` was already handled; NaN — the OTHER not-a-number —
        was promoted to a perfect score on the headline factor."""
        html = meter_svg("Availability", value, refused="could not be computed")
        assert '<div class="meter-refused">' in html
        for lie in FORBIDDEN_IN_OUTPUT:
            assert lie not in html

    def test_a_real_fraction_still_draws_a_bar(self):
        """The complement: refusing everything would pass the sweep above."""
        html = meter_svg("Availability", 0.759)
        assert '<div class="meter-refused">' not in html
        assert "75.9%" in html

    @pytest.mark.parametrize("value", UNKNOWNS)
    def test_an_unknown_total_draws_nothing(self, value):
        assert (
            stacked_bar_svg([{"label": "x", "value": 1.0, "var": "ok"}], total=value, title="t")
            == ""
        )

    @pytest.mark.parametrize("value", UNKNOWNS)
    def test_an_unknown_segment_is_labelled_unknown_not_sized(self, value):
        html = stacked_bar_svg(
            [
                {"label": "known", "value": 30.0, "var": "ok"},
                {"label": "unknown", "value": value, "var": "bad"},
            ],
            total=100.0,
            title="t",
        )
        assert UNKNOWN in html
        for lie in FORBIDDEN_IN_OUTPUT:
            assert lie not in html

    def test_the_known_segment_is_still_drawn_beside_it(self):
        """One unknown segment must not blank the whole chart."""
        html = stacked_bar_svg(
            [
                {"label": "known", "value": 30.0, "var": "ok"},
                {"label": "unknown", "value": NAN, "var": "bad"},
            ],
            total=100.0,
            title="t",
        )
        assert "30.0%" in html

    @pytest.mark.parametrize("missing", ["label", "value", "var"])
    def test_a_segment_missing_a_key_does_not_crash(self, missing):
        """`stacked_bar_svg` is public; it indexed with `[]` everywhere but `dim`."""
        seg = {"label": "x", "value": 1.0, "var": "ok"}
        seg.pop(missing)
        assert isinstance(stacked_bar_svg([seg], total=10.0, title="t"), str)


class TestTheWholeReportSurvivesAnAllUnknownPayload:
    """The end of the chain. Each renderer refusing is necessary but not enough —
    the page assembles them, and `int()`/`f"{x:,.0f}"` sites sat between."""

    def _payload(self) -> dict:
        return {
            "measured": {
                "tag": "0",
                "status": "insufficient_data",
                "running_s": NAN,
                "stopped_s": None,
                "unknown_s": NAN,
                "coverage_pct": NAN,
                "n_samples": INF,
                "sample_cadence_s": NAN,
                "stops": NAN,
                "minor_stops": NAN,
                "availability": NAN,
                "note": "3 usable samples — below 10. Collect first ('iaiops collect run').",
            },
            "comparison": None,
            "production": {
                "status": "ok",
                "produced": NAN,
                "discontinuities": 0,
                "unobserved_steps": 0,
                "n_samples": 0,
                "note": "",
            },
            "performance": {"performance": NAN, "warning": "", "note": "no cycle"},
            "quality": {"quality": None, "note": "no good count"},
            "factors": {"availability": NAN, "performance": NAN, "quality": None},
            "oee": NAN,
            "losses": {"status": "no_availability", "note": "no availability measured"},
        }

    def _render(self, **over) -> str:
        from iaiops.core.brain.oee_report import render_oee_report

        data = {**self._payload(), **over}
        return render_oee_report(
            data, endpoint="line1", site="Plant A", generated_at="2026-08-25T00:00:00Z"
        )

    def test_it_renders_at_all(self):
        assert self._render().startswith("<!doctype html>")

    def test_it_claims_no_number_it_could_not_compute(self):
        """Scoped to the RENDERED figures. The appendix deliberately shows what
        arrived — including that it was NaN — because "the tool received NaN" and
        "the tool received nothing" are different bugs to chase."""
        html = self._render()
        rendered = html[: html.index(EN["appendix_h"])]
        for lie in FORBIDDEN_IN_OUTPUT:
            assert lie not in rendered, f"the page claims {lie!r}"

    def test_the_appendix_is_parseable_json(self):
        """It exists so a reader can take the numbers away and check them. A bare
        `NaN` token is what `json.dumps` emits and what no strict parser accepts."""
        import html as html_mod
        import json
        import re

        page = self._render()
        blob = re.search(r"<pre><code>(.*?)</code></pre>", page, re.S).group(1)
        parsed = json.loads(html_mod.unescape(blob))  # raises if `NaN` is bare
        assert parsed["measured"]["running_s"] == "NaN"
        assert parsed["measured"]["n_samples"] == "Infinity"

    def test_a_refusal_with_real_zeros_still_shows_its_reason(self):
        """The one that matters, and the one the first version of this test missed.

        A real `insufficient_data` result carries actual `0.0`s — it spreads
        `base`, it does not carry NaN. So an all-NaN payload cannot exercise the
        zero-tile guard at all: the NaN guards catch it first and the test passes
        whether or not the guard exists. (It did; a mutation removing the guard
        survived.) This payload is what the engine actually returns."""
        html = self._render(
            measured={
                "tag": "0",
                "status": "insufficient_data",
                "running_s": 0.0,
                "stopped_s": 0.0,
                "unknown_s": 0.0,
                "coverage_pct": 0.0,
                "n_samples": 3,
                "minor_stops": 0,
                "minor_stop_s": 0.0,
                "availability": None,
                "note": "3 usable samples — below 10. Collect first.",
            }
        )
        assert "below 10" in html
        assert "0.0%" not in html, "a refused measurement rendered a table of zeros"
        assert EN["coverage"] not in html or html.index(EN["not_measurable"]) < html.index(
            EN["oee_h"]
        )

    def test_a_refused_measurement_shows_its_reason_not_a_table_of_zeros(self):
        """The CLI guards this by name — "running 0ms · stopped 0ms · blind 0ms
        reads like a measured result" — and the REPORT, the artifact that gets
        forwarded, did not."""
        html = self._render()
        assert "below 10" in html
        assert "0.0%" not in html

    def test_the_honesty_section_is_not_double_escaped(self):
        """`_needs` escaped on append AND on render, so `&#x27;` went through the
        one section that exists to be honest — on the SHIPPED English strings,
        which contain apostrophes."""
        assert "&amp;#x27;" not in self._render()
        assert "&amp;amp;" not in self._render()

    def test_a_healthy_payload_still_shows_its_numbers(self):
        """The complement, and the one that matters: a page that refused
        everything would pass every test above."""
        html = self._render(
            measured={
                "tag": "0",
                "status": "ok",
                "running_s": 132.4,
                "stopped_s": 47.5,
                "unknown_s": 0.0,
                "coverage_pct": 100.0,
                "n_samples": 654,
                "sample_cadence_s": 0.25,
                "stops": 4,
                "minor_stops": 2,
                "minor_stop_s": 7.2,
                "availability": 0.7593,
                "note": "ok",
            },
            factors={"availability": 0.7593, "performance": 0.941, "quality": 0.961},
            oee=0.6863,
        )
        assert "75.9%" in html and "654" in html
