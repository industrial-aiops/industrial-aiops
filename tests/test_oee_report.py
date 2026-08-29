"""The OEE report — what it puts first, and what it refuses to imply.

`scan` and `compliance` could both write a file; `oee measure` could not, so the
number this product most wants a customer to see was the only one that could not
be put on paper. These tests cover the two properties that make a forwardable
report honest rather than merely pretty.

**Coverage before the figure.** The scan report's module docstring argues the
section order IS the argument — it opens with what it did, not what it found.
Here the equivalent is that "we could see 85% of the window" must precede "OEE
66%". A report that leads with the number and footnotes the coverage hands the
reader a measured fact and lets them supply a false precision.

**The percentage trap.** `pct_of_planned` in the loss ladder is a fraction (0-1)
while `coverage_pct` and friends are already percentages (0-100). Rendering one
as the other turns a quarter of the shift into "0.3%" — a number small enough
that nobody queries it. Two named formatters exist so the mix-up is visible at
the call site; these tests make sure it stays that way.
"""

from __future__ import annotations

import re

import pytest

from iaiops.core.brain.oee_report import _figure, render_oee_report
from iaiops.core.report.strings import EN, ZH, strings
from iaiops.core.report.svg import _BAR_W, meter_svg

pytestmark = pytest.mark.unit


def _losses(**over) -> dict:
    base = {
        "status": "ok",
        "planned_time_s": 179.9,
        # 122.5 + (46.6 + 5.9 + 4.9) = 179.9 exactly. The ladder identity holds in
        # real data (checked against a live run), so a fixture that missed it by
        # 0.1s was testing a shape the product never produces — and the bar test
        # is tight enough to have noticed, which is the point of it.
        "fully_productive_time_s": 122.5,
        "oee_from_losses": 0.680378,
        "planned_time_basis": "observed_known_time",
        "coverage_pct": 100.0,
        "optimistic_cycle": False,
        "fully_classified": False,
        "by_bucket": {"availability": {"loss_s": 47.5, "pct_of_planned": 0.264}},
        "note": "Losses are a decomposition of OBSERVED time.",
        "losses": [
            {
                "loss": "breakdown",
                "bucket": "availability",
                "time_s": 46.6,
                "pct_of_planned": 0.259,
                "classified": False,
            },
            {
                "loss": "setup",
                "bucket": "availability",
                "time_s": 0.0,
                "pct_of_planned": 0.0,
                "classified": False,
            },
            {
                "loss": "minor_stops",
                "bucket": "performance",
                "time_s": 0.0,
                "pct_of_planned": 0.0,
                "classified": False,
            },
            {
                "loss": "speed_loss",
                "bucket": "performance",
                "time_s": 5.9,
                "pct_of_planned": 0.033,
                "classified": False,
            },
            {
                "loss": "startup_rejects",
                "bucket": "quality",
                "time_s": 0.0,
                "pct_of_planned": 0.0,
                "classified": False,
                "count": 0.0,
            },
            {
                "loss": "production_rejects",
                "bucket": "quality",
                "time_s": 4.9,
                "pct_of_planned": 0.028,
                "classified": False,
                "count": 50.0,
            },
        ],
        "largest_loss": {"loss": "breakdown", "bucket": "availability", "time_s": 46.6},
    }
    return {**base, **over}


def payload(**over) -> dict:
    base = {
        "measured": {
            "tag": "0",
            "status": "ok",
            "running_s": 132.4,
            "stopped_s": 47.5,
            "unknown_s": 10.3,
            "coverage_pct": 85.37,
            "n_samples": 654,
            "sample_cadence_s": 0.25,
            "stops": 4,
            "minor_stops": 2,
            "minor_stop_s": 7.2,
            "availability": 0.7593,
            "note": "over KNOWN time",
        },
        "comparison": {
            "status": "ok",
            "gap_points": 21.07,
            "reported_pct": 97.0,
            "measured_pct": 75.93,
            "coverage_pct": 85.37,
            "minor_stops": 2,
            "minor_stop_s": 7.2,
            "explanation": "Measured 75.93% against 97% reported.",
        },
        "production": {
            "status": "ok",
            "produced": 1274.0,
            "discontinuities": 1,
            "unobserved_steps": 2,
            "n_samples": 654,
            "note": "rising increments",
        },
        "performance": {
            "performance": 0.941,
            "performance_raw": 0.941,
            "warning": "",
            "note": "ideal cycle x parts / run time",
        },
        "quality": {"quality": 0.961, "note": "good / total"},
        "factors": {"availability": 0.7593, "performance": 0.941, "quality": 0.961},
        "oee": 0.6863,
        "losses": _losses(),
    }
    return {**base, **over}


def _stacked_bar(html: str) -> str:
    """The losses bar, found by its viewBox width rather than a hardcoded number —
    the constant moved once already and a literal in the test would have hidden it."""
    return re.search(rf'<svg viewBox="0 0 {_BAR_W:.0f} [\d.]+".*?</svg>', html, re.S).group(0)


def render(**kwargs) -> str:
    opts = {"endpoint": "line1", "site": "Plant A", "generated_at": "2026-08-24T18:00:00Z"}
    data = kwargs.pop("payload", None) or payload()
    return render_oee_report(data, **{**opts, **kwargs})


class TestTheTrustBlockComesFirst:
    def test_what_we_could_see_precedes_the_figure(self):
        """The section order is the argument, exactly as it is for the scan report."""
        html = render()
        assert html.index(EN["seen_h"]) < html.index(f">{EN['oee_h']}<")

    def test_coverage_appears_before_the_headline_number(self):
        html = render()
        assert html.index("85.4%") < html.index("68.6%")

    def test_blind_time_is_named_and_said_to_be_excluded(self):
        """Counting it as downtime is the flattering error this line refuses."""
        html = render()
        assert EN["blind"] in html
        assert "not counted as downtime" in html

    def test_the_cadence_limit_is_stated_rather_than_left_to_be_discovered(self):
        html = render()
        assert "twice the sample cadence" in html

    def test_it_says_no_production_schedule_was_supplied(self):
        """'Planned time' in the ladder means observed time. Left unsaid, a reader
        assumes we were given the shift plan."""
        assert "No production schedule was supplied." in render()


class TestPercentagesAreNotMixed:
    def test_a_loss_share_renders_as_a_percentage_not_a_fraction(self):
        """`pct_of_planned` is 0-1. Rendered with the wrong formatter, a quarter
        of the shift prints as 0.3% — small enough that nobody queries it."""
        html = render()
        assert "25.9%" in html, "the 0.259 loss share should read as 25.9%"
        assert "0.3%" not in html

    def test_an_already_percent_value_is_not_multiplied_again(self):
        """`coverage_pct` is already 0-100; multiplying gives 8537%."""
        html = render()
        assert "85.4%" in html
        assert "8537" not in html

    def test_the_headline_is_the_product_of_the_three_factors(self):
        html = render()
        assert "68.6%" in html  # 0.7593 x 0.941 x 0.961


class TestARefusedFactorShowsItsReason:
    def test_a_missing_factor_renders_its_note_not_a_blank(self):
        """A blank meter reads as zero, and zero is a measurement."""
        html = render(
            payload=payload(
                quality={
                    "quality": None,
                    "note": "No good-count declared, so Quality is not reported.",
                },
                factors={"availability": 0.7593, "performance": 0.941, "quality": None},
                oee=None,
            )
        )
        assert "No good-count declared" in html

    def test_a_measured_factor_is_not_marked_refused(self):
        """The complement: an implementation that marked everything refused would
        pass the test above."""
        html = render()
        # The ELEMENT, not the class name — the class also appears in the
        # stylesheet, so a bare substring check can never fail.
        assert '<div class="meter-refused">' not in html

    def test_no_single_figure_says_which_factor_is_missing(self):
        html = render(
            payload=payload(
                factors={"availability": 0.7593, "performance": 0.941, "quality": None},
                oee=None,
            )
        )
        assert EN["quality"] in html
        assert "multiplying in a guess" in html

    def test_a_refused_loss_ladder_shows_its_note_not_an_empty_table(self):
        html = render(
            payload=payload(
                losses={
                    "status": "inputs_not_declared",
                    "missing": ["good count"],
                    "note": "The Six Big Losses need good count.",
                }
            )
        )
        assert "The Six Big Losses need good count." in html
        assert "<tbody></tbody>" not in html


class TestTheLossLadderIsDrawn:
    def test_every_loss_has_a_row(self):
        html = render()
        for name in (
            "breakdown",
            "setup",
            "minor_stops",
            "speed_loss",
            "startup_rejects",
            "production_rejects",
        ):
            assert EN[f"loss_{name}"] in html

    def test_a_loss_with_no_count_is_a_dash_not_the_word_none(self):
        """Only two of the six carry a count; the other four must not print None."""
        html = render()
        assert ">None<" not in html
        assert 'class="blank"' in html

    def test_a_loss_with_a_count_shows_it(self):
        """The complement to the dash test — an implementation that blanked every
        cell would pass that one."""
        assert ">50.0<" in render() or ">50<" in render()

    def test_the_segments_fill_the_bar_and_do_not_overflow(self):
        """Fully productive + six losses = planned, exactly. A bar drawn past its
        own width would be the visible form of an arithmetic error."""
        html = render()
        bar = _stacked_bar(html)
        widths = [float(w) for w in re.findall(r'<rect x="[\d.]+" y="0" width="([\d.]+)"', bar)]
        assert sum(widths) == pytest.approx(_BAR_W, abs=0.5)

    def test_a_segment_that_would_overrun_the_bar_is_clipped(self):
        """The ladder identity (productive + losses = planned) is checked in the
        brain, but the chart must not draw past its own width if it ever breaks.
        A bar rendering 140% of itself is the visible form of an arithmetic error;
        silently letting it spill is how the error stops being visible."""
        broken = _losses(
            fully_productive_time_s=122.4,
            losses=[
                {
                    "loss": "breakdown",
                    "bucket": "availability",
                    "time_s": 500.0,
                    "pct_of_planned": 2.78,
                    "classified": False,
                },
            ],
        )
        html = render(payload=payload(losses=broken))
        bar = _stacked_bar(html)
        widths = [float(w) for w in re.findall(r'<rect x="[\d.]+" y="0" width="([\d.]+)"', bar)]
        assert sum(widths) <= _BAR_W + 0.5, f"the bar drew {sum(widths):.1f} of {_BAR_W}"

    def test_the_true_number_survives_the_clip(self):
        """Clipping the drawing must not quietly shrink the reported value —
        that would hide the bad input the clip exists to expose."""
        broken = _losses(
            losses=[
                {
                    "loss": "breakdown",
                    "bucket": "availability",
                    "time_s": 500.0,
                    "pct_of_planned": 2.78,
                    "classified": False,
                },
            ],
        )
        assert "500.0s" in render(payload=payload(losses=broken))

    def test_the_largest_loss_is_named(self):
        assert EN["largest"] in render()

    def test_an_unclassified_bucket_says_so(self):
        """No split input was supplied, so no bucket may print as explained."""
        assert EN["unclassified"] in render()


class TestItNeverExecutesWhatTheSiteTyped:
    HOSTILE = "<script>alert(1)</script>"

    def test_a_hostile_site_name_is_escaped(self):
        html = render(site=self.HOSTILE)
        assert self.HOSTILE not in html
        assert "&lt;script&gt;" in html

    def test_a_hostile_note_is_escaped(self):
        html = render(note=self.HOSTILE)
        assert self.HOSTILE not in html

    def test_a_hostile_tag_name_is_escaped(self):
        data = payload()
        data["measured"]["tag"] = self.HOSTILE
        assert self.HOSTILE not in render(payload=data)

    def test_a_hostile_string_inside_the_appendix_is_escaped(self):
        """The appendix dumps the payload verbatim — the easiest place to forget."""
        data = payload()
        data["measured"]["note"] = self.HOSTILE
        assert self.HOSTILE not in render(payload=data)

    def test_the_page_contains_no_script_tag_at_all(self):
        """This report has no sortable table, so it ships no script — 'this file
        runs nothing' is true by construction here, not merely by policy."""
        assert "<script" not in render()


class TestItMakesNoNetworkRequest:
    def test_nothing_is_loaded_from_anywhere(self):
        html = render()
        for pattern in ("http://", "https://", "//cdn", "@import", "url(http"):
            assert pattern not in html, f"the report references {pattern!r}"

    def test_there_are_no_external_resource_elements(self):
        html = render().lower()
        for tag in ("<link", "<img", "<iframe", "<object", "<embed", "<source"):
            assert tag not in html, f"the report contains {tag}"

    def test_the_chart_is_inline_svg_rather_than_an_image(self):
        """A data-URI image would have been the easy way and would fail the rule
        above; inline <svg> is what fits the constraint."""
        html = render()
        assert "<svg" in html and "<rect" in html


class TestStructure:
    def test_it_is_a_complete_standalone_document(self):
        html = render()
        assert html.startswith("<!doctype html>")
        assert "<title>" in html and html.rstrip().endswith("</html>")
        assert 'charset="utf-8"' in html

    def test_it_renders_in_both_colour_schemes(self):
        """It is opened on whatever laptop is in the plant office."""
        html = render()
        assert "prefers-color-scheme: dark" in html
        assert re.search(r":root\s*\{", html)

    def test_the_same_payload_renders_the_same_bytes(self):
        """No clock inside. Two shifts have to be diffable."""
        assert render() == render()

    def test_wide_content_scrolls_inside_its_own_container(self):
        assert 'class="scroll"' in render()


class TestBothLanguagesRender:
    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_it_renders(self, lang):
        html = render(lang=lang)
        assert html.startswith("<!doctype html>")
        assert f'lang="{lang}"' in html

    def test_the_chinese_page_is_not_half_english(self):
        html = render(lang="zh")
        assert ZH["seen_h"] in html
        assert EN["seen_h"] not in html

    def test_an_unknown_language_is_refused_rather_than_falling_back(self):
        """A silent fallback leaves the reader unable to tell a translation gap
        from a deliberate term."""
        with pytest.raises(ValueError) as excinfo:
            render(lang="de")
        assert "en" in str(excinfo.value) and "zh" in str(excinfo.value)


class TestTheStringTablesHaveTheSameKeys:
    def test_no_key_is_missing_from_either_table(self):
        """A missed translation falls back to English inside a Chinese page, and
        the strings added last are the honesty caveats."""
        assert set(EN) == set(ZH)

    def test_no_value_is_empty(self):
        for table, name in ((EN, "EN"), (ZH, "ZH")):
            for key, value in table.items():
                assert value, f"{name}[{key!r}] is empty"

    def test_the_claim_lists_are_the_same_length(self):
        """A bullet dropped from one language is a caveat only half the readers see."""
        assert len(EN["not_claimed"]) == len(ZH["not_claimed"])

    def test_both_tables_are_reachable_by_name(self):
        assert strings("en") is EN and strings("zh") is ZH


class TestThePrerequisiteRow:
    def test_it_lists_what_had_to_be_supplied(self):
        """The row the sales deck leaves out, and the reason a demo fails at first
        contact with a real site."""
        html = render()
        assert EN["needs_h"] in html
        assert EN["need_run_state"] in html

    def test_a_missing_input_is_listed_as_missing(self):
        html = render(
            payload=payload(
                quality={"quality": None, "note": "no good count"},
                factors={"availability": 0.7593, "performance": 0.941, "quality": None},
                oee=None,
            )
        )
        assert 'class="want"' in html

    def test_a_complete_site_says_nothing_is_missing(self):
        """The complement: an implementation that always printed a 'missing' list
        would pass the test above."""
        html = render()
        assert EN["nothing_missing"] in html
        assert 'class="want"' not in html

    def test_it_does_not_say_nothing_is_missing_while_listing_something(self):
        """A page that prints 'still missing: a good-count tag' and 'Nothing. Every
        input these figures need was declared.' contradicts itself, and a reader
        who believes the second line stops looking for the first."""
        html = render(
            payload=payload(
                quality={"quality": None, "note": "no good count"},
                factors={"availability": 0.7593, "performance": 0.941, "quality": None},
                oee=None,
            )
        )
        assert 'class="want"' in html
        assert EN["nothing_missing"] not in html


class TestAClampedMeterIsNotAFullGreenBar:
    """A Performance of 3726% clamps to 100% and rendered as a full green bar.

    Seen in the real report from a lab line whose declared cycle time was wrong.
    The paragraph under the meters carried the raw number, so it was not hidden —
    but the bar is what a reader looks at, and a full bar at the ceiling is the
    strongest "everything is perfect" signal a page can send, on the artifact
    that gets forwarded into a report. #218 fixed this for the CLI only.
    """

    def test_the_meter_says_it_was_clamped(self):
        html = meter_svg("Performance", 1.0, clamped_from=37.26)
        assert "clamped from 3726.0%" in html

    def test_the_accessible_name_says_it_too(self):
        html = meter_svg("Performance", 1.0, clamped_from=37.26)
        assert 'aria-label="Performance 100.0%, clamped from 3726.0%"' in html

    def test_an_unclamped_meter_is_not_decorated(self):
        assert "clamped" not in meter_svg("Quality", 0.96, clamped_from=0.96)

    def test_a_meter_with_no_raw_value_is_not_decorated(self):
        assert "clamped" not in meter_svg("Availability", 0.876)

    def test_a_nan_raw_value_does_not_produce_a_clamp_note(self):
        """`finite` covers it; NaN comparisons are all False and would slip through."""
        assert "clamped" not in meter_svg("Performance", 1.0, clamped_from=float("nan"))

    def test_the_oee_report_passes_the_raw_value_through(self):
        """The seam. Testing meter_svg alone says nothing about what calls it."""
        payload = {
            "factors": {"availability": 0.876, "performance": 1.0, "quality": 0.96},
            "performance": {"performance_raw": 37.26, "note": ""},
            "quality": {"note": ""},
            "measured": {"note": ""},
            "oee": 0.841,
        }
        assert "clamped from 3726.0%" in _figure(strings("en"), payload)
