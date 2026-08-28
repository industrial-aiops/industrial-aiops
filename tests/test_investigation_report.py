"""The investigation as one self-contained HTML file.

HLD §13.9's front-end table orders these: CLI **first**, the self-contained HTML
report **alongside it**, the App page after, MCP last. The MCP front end was built
first (#205/#206) and this — ordered ahead of it — was skipped. `scan` and
`oee measure` both write a report; the investigation, which is the thing an
integrator actually hands to a plant, could not.

**Where this deliberately differs from the OEE report.** `oee measure --report`
*refuses* to write a file when the measurement was refused, because an OEE report
is a number and a file that exists at all is a claim that the number was measured.
An investigation report is the opposite: its content is *how far this got and what
each remaining step needs*, so a blocked investigation is the case most worth
forwarding — that is the whole deliverable for a site that has not been
instrumented yet. What it must never do is let a blocked investigation LOOK
finished, which is why the headline is the walk, never a conclusion.
"""

from __future__ import annotations

import re

import pytest

from iaiops.core.investigate.report import render_live_report, render_plan_report

pytestmark = pytest.mark.unit

HOSTILE = "<script>alert('x')</script>"


def plan_payload(**over):
    """Shaped like `assess_investigation().as_dict()`."""
    data = {
        "site": "line-a",
        "reachable_through": 2,
        "total_steps": 8,
        "blocked_later": ["correlate_timeline"],
        "steps": [
            {
                "number": 1,
                "key": "define_incident",
                "label": "Define the incident",
                "status": "ready",
                "headline": "ready",
                "value": "A window and an asset to reason about.",
                "requirements": [{"key": "window", "label": "a window", "met": True, "detail": ""}],
            },
            {
                "number": 2,
                "key": "collect_evidence",
                "label": "Collect the evidence",
                "status": "ready",
                "headline": "ready",
                "value": "Samples around the window.",
                "requirements": [{"key": "samples", "label": "samples", "met": True, "detail": ""}],
            },
            {
                "number": 3,
                "key": "normalize_and_check",
                "label": "Normalize and check the data",
                "status": "blocked",
                "headline": "blocked — needs: declared tag semantics",
                "value": "Knowing which tag means what.",
                "requirements": [
                    {
                        "key": "roles",
                        "label": "declared tag semantics",
                        "met": False,
                        "detail": "no tag declares a role",
                        "fix": "Add `role:` to the tags in config.yaml.",
                        "optional": False,
                    }
                ],
            },
            {
                "number": 4,
                "key": "compress_and_rank",
                "label": "Compress and rank",
                "status": "blocked",
                "headline": "blocked — needs: a production schedule",
                "value": "Ranked candidate causes.",
                "requirements": [
                    {
                        "key": "schedule",
                        "label": "a production schedule",
                        "met": False,
                        "detail": "none supplied",
                        "fix": "",
                        "optional": False,
                        "not_yet_expressible": True,
                    }
                ],
            },
        ],
    }
    data.update(over)
    return data


def live_payload(**over):
    """Shaped like `Investigation.as_dict()`."""
    data = {
        "version": 1,
        "id": "inv-20260828-0001",
        "site": "line-a",
        "scope": {
            "endpoint": "press-01",
            "start": "2026-08-26T10:00:00+00:00",
            "end": "2026-08-26T10:30:00+00:00",
            "asset": "press",
        },
        "opened_at": "2026-08-28T09:00:00+00:00",
        "reached": 2,
        "total_steps": 8,
        "steps": [
            {
                "number": 1,
                "key": "define_incident",
                "label": "Define the incident",
                "state": "done",
                "summary": "30 minutes on press-01.",
            },
            {
                "number": 2,
                "key": "collect_evidence",
                "label": "Collect the evidence",
                "state": "done",
                "summary": "412 samples over 6 tags.",
            },
            {
                "number": 3,
                "key": "normalize_and_check",
                "label": "Normalize and check the data",
                "state": "refused",
                "summary": "No tag declares a role, and this will not be guessed.",
            },
            {
                "number": 4,
                "key": "compress_and_rank",
                "label": "Compress and rank",
                "state": "not_possible",
                "summary": "No production schedule can be supplied to this product yet.",
            },
        ],
    }
    data.update(over)
    return data


def plan(**kw):
    return render_plan_report(plan_payload(), generated_at="2026-08-28T09:00:00Z", **kw)


def live(**kw):
    return render_live_report(live_payload(), generated_at="2026-08-28T09:00:00Z", **kw)


class TestTheHeadlineIsTheWalkNotAConclusion:
    """The one thing this report must never do is let a blocked investigation look
    finished. OEE puts coverage before the number for the same reason.

    The first version of these tests asserted that "2" and "8" appeared near the
    top — which every step number and every sentence also satisfies. Deleting the
    progress figure outright left all of them green.
    """

    def test_the_progress_figure_is_on_the_page(self):
        assert '<p class="reach">2 / 8</p>' in plan()
        assert '<p class="reach">2 / 8</p>' in live()

    def test_a_walk_that_never_starts_says_zero_rather_than_omitting_it(self):
        html = render_plan_report(
            plan_payload(reachable_through=0), generated_at="2026-08-28T09:00:00Z"
        )
        assert '<p class="reach">0 / 8</p>' in html

    def test_the_progress_comes_before_the_steps(self):
        for html in (plan(), live()):
            assert html.index('class="reach"') < html.index('class="scroll"')

    def test_no_step_text_appears_above_the_progress(self):
        """The real invariant. A renderer that promoted a step's own words into
        the headline would read as a finding rather than as how far it got."""
        html = live()
        above = html[: html.index('class="reach"')]
        for step in live_payload()["steps"]:
            assert step["summary"] not in above, step["summary"]

    def test_the_same_holds_for_the_plan(self):
        html = plan()
        above = html[: html.index('class="reach"')]
        for step in plan_payload()["steps"]:
            assert step["headline"] not in above, step["headline"]


class TestABlockedInvestigationIsStillWorthForwarding:
    """Deliberately unlike `oee measure --report`, which refuses. Here the gaps
    ARE the deliverable — this is the report for a site nobody has instrumented."""

    def test_a_plan_that_reaches_nothing_still_renders(self):
        html = render_plan_report(
            plan_payload(reachable_through=0), generated_at="2026-08-28T09:00:00Z"
        )
        assert html.startswith("<!doctype html>")

    def test_it_names_what_to_supply_next(self):
        assert "Add `role:` to the tags in config.yaml." in plan() or ("role:" in plan()), (
            "the fix for the first blocking gap has to be on the page"
        )


class TestUnmetAndInexpressibleAreNotTheSame:
    """The honesty flag. "You have not supplied it" sends someone to config.yaml;
    "this product cannot accept it" sends them to the issue tracker. Rendering
    both as "missing" sends half of them to look for a setting that is not there."""

    def test_an_inexpressible_gap_is_marked_as_such(self):
        html = plan()
        assert "no way to supply" in html.lower() or "尚无" in html

    def test_an_ordinary_unmet_gap_is_not_marked_that_way(self):
        """The complement: a renderer that stamped every gap with the honesty
        note would pass the test above and destroy the distinction."""
        only_unmet = plan_payload()
        only_unmet["steps"] = [only_unmet["steps"][2]]
        html = render_plan_report(only_unmet, generated_at="x")
        assert "no way to supply" not in html.lower()

    def test_not_possible_reads_differently_from_refused(self):
        """Same distinction on the live side. `refused` means this SITE could not
        satisfy the step; `not_possible` means the PRODUCT cannot do it at all.
        Collapsing them into one shade of "not done" is the failure — the two send
        a reader to two entirely different places."""
        html = live()
        assert "refused" in html and "not_possible" in html

    def test_the_two_live_failures_do_not_share_a_colour(self):
        """The complement. Both words can be present and still read as the same
        thing if they are drawn identically."""
        import re as _re

        html = live()
        tone = {
            state: _re.search(rf'class="badge (\w+) {state}"', html).group(1)
            for state in ("refused", "not_possible")
        }
        assert tone["refused"] != tone["not_possible"], tone


class TestEverythingTheSiteTypedIsEscaped:
    """A tag label is whatever the site typed and a summary quotes device text.
    Unescaped, a report about a hostile network becomes script on the reader's
    laptop."""

    def test_a_hostile_site_name_is_escaped(self):
        assert HOSTILE not in render_plan_report(plan_payload(site=HOSTILE), generated_at="x")

    def test_a_hostile_step_summary_is_escaped(self):
        data = live_payload()
        data["steps"][0]["summary"] = HOSTILE
        assert HOSTILE not in render_live_report(data, generated_at="x")

    def test_a_hostile_requirement_fix_is_escaped(self):
        data = plan_payload()
        data["steps"][2]["requirements"][0]["fix"] = HOSTILE
        assert HOSTILE not in render_plan_report(data, generated_at="x")

    def test_a_hostile_endpoint_is_escaped(self):
        data = live_payload()
        data["scope"]["endpoint"] = HOSTILE
        assert HOSTILE not in render_live_report(data, generated_at="x")


class TestItMakesNoNetworkRequest:
    def test_nothing_is_loaded_from_anywhere(self):
        for html in (plan(), live()):
            for pattern in ("http://", "https://", "//cdn", "@import", "url(http"):
                assert pattern not in html, f"the report references {pattern!r}"

    def test_there_are_no_external_resource_elements(self):
        for html in (plan().lower(), live().lower()):
            for tag in ("<link", "<img", "<iframe", "<object", "<embed", "<source"):
                assert tag not in html, f"the report contains {tag}"

    def test_it_ships_no_script_at_all(self):
        """No sortable table here, so "this file runs nothing" is true by
        construction rather than by policy."""
        assert "<script" not in plan() and "<script" not in live()


class TestStructure:
    def test_it_is_a_complete_standalone_document(self):
        for html in (plan(), live()):
            assert html.startswith("<!doctype html>")
            assert "<title>" in html and html.rstrip().endswith("</html>")
            assert 'charset="utf-8"' in html

    def test_it_renders_in_both_colour_schemes(self):
        html = plan()
        assert "prefers-color-scheme: dark" in html
        assert re.search(r":root\s*\{", html)

    def test_the_same_payload_renders_the_same_bytes(self):
        """No clock inside — `generated_at` is the caller's. Two investigations
        of the same incident have to be diffable."""
        assert plan() == plan() and live() == live()

    def test_wide_content_scrolls_inside_its_own_container(self):
        assert 'class="scroll"' in plan() and 'class="scroll"' in live()


class TestBothLanguages:
    def test_an_unknown_language_raises_rather_than_falling_back(self):
        """A silent fallback is how a Chinese page ends up half English, and the
        strings added late are the honesty caveats."""
        with pytest.raises(ValueError, match="fr"):
            plan(lang="fr")

    def test_the_chinese_page_declares_itself_chinese(self):
        assert 'lang="zh"' in plan(lang="zh")

    def test_the_chinese_page_carries_the_honesty_section_too(self):
        zh = plan(lang="zh")
        en = plan(lang="en")
        assert zh != en
        assert "尚无" in zh or "无法" in zh

    def test_the_two_tables_have_the_same_keys(self):
        from iaiops.core.investigate.report import EN, ZH

        assert set(EN) == set(ZH)


class TestTheRealEngineOutputRenders:
    """Hand-built payloads can drift from the engine. This one cannot."""

    def test_a_real_plan_renders(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        from iaiops.core.investigate import assess_investigation

        html = render_plan_report(assess_investigation().as_dict(), generated_at="x")
        assert html.startswith("<!doctype html>")

    def test_a_real_investigation_renders(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        from iaiops.core.investigate.live import advance, open_investigation

        inv = advance(
            open_investigation(
                endpoint="line1", start="2026-08-26T10:00:00Z", end="2026-08-26T10:10:00Z"
            )
        )
        assert render_live_report(inv.as_dict(), generated_at="x").startswith("<!doctype html>")


class TestTheGapListDoesNotRepeatItself:
    """Found by reading the rendered page, not by a failing assertion.

    On a bare site the same action — `collect run` — appeared four times under
    four different step numbers, in a list whose own lead sentence says it is
    ranked by where the walk stops. `readiness` already solved this: dedupe by
    requirement key, keep first-appearance order, and say what each one unlocks.
    A list that repeats one action four times reads as four problems.
    """

    def _repeated(self):
        data = plan_payload()
        same = {
            "key": "samples",
            "label": "collected samples",
            "met": False,
            "detail": "local store is empty",
            "fix": "Collect first.",
            "optional": False,
        }
        data["steps"][2]["requirements"] = [dict(same)]
        data["steps"][3]["requirements"] = [dict(same)]
        return data

    def test_one_requirement_blocking_two_steps_is_listed_once(self):
        html = render_plan_report(self._repeated(), generated_at="x")
        assert html.count("collected samples") == 1, "the gap list repeated itself"

    def test_it_says_which_steps_that_one_gap_unlocks(self):
        """Deduping without saying what was folded in would hide that this single
        gap is holding up two steps — which is the reason to supply it first."""
        html = render_plan_report(self._repeated(), generated_at="x")
        assert "3" in html and "4" in html
        block = html[html.index("collected samples") - 200 : html.index("collected samples") + 200]
        assert "3" in block and "4" in block, block

    def test_two_genuinely_different_gaps_are_both_listed(self):
        """The complement: a renderer that collapsed everything to one entry would
        pass both tests above."""
        html = plan()
        assert "declared tag semantics" in html and "a production schedule" in html

    def test_four_differently_named_gaps_with_one_action_collapse(self):
        """The case that actually occurs. Deduping by requirement key was the
        obvious move and changed nothing: on a bare site four steps want four
        differently named things that one `collect run` supplies."""
        data = plan_payload()
        fix = "Collect first: `iaiops collect run <endpoint> --duration 1h`."
        for i, name in enumerate(["samples in store", "samples to check", "a sampled series"]):
            data["steps"][i]["requirements"] = [
                {"key": f"k{i}", "label": name, "met": False, "detail": "", "fix": fix}
            ]
        html = render_plan_report(data, generated_at="x")
        assert html.count("Collect first") == 1, "one action, one line"

    def test_two_inexpressible_gaps_do_not_collapse_into_one(self):
        """They share an empty fix. Grouping by action would fold every "this
        product cannot accept it" in a report into a single entry."""
        data = plan_payload()
        for i, name in enumerate(["a schedule", "a shift calendar"]):
            data["steps"][i]["requirements"] = [
                {
                    "key": f"x{i}",
                    "label": name,
                    "met": False,
                    "detail": "",
                    "fix": "",
                    "not_yet_expressible": True,
                }
            ]
        html = render_plan_report(data, generated_at="x")
        assert "a schedule" in html and "a shift calendar" in html
