"""A live investigation: stateful, resumable, and honest about each step.

HLD §13, delivery step 2. `investigate plan` answers "how far COULD we get";
this walks the eight steps over a real window and records what each one actually
produced — wiring the capabilities that already exist (`query_samples`,
`historian_health`, `alarm_flood_report`, `downtime_rca`, `case`) rather than
adding analysis.

The three properties that make it an object rather than a command (D31):

* **It survives the process.** Opened once, advanced later, read by somebody
  else. Same shape as a collection `Session`, and for the same reason.
* **Every step records its own outcome**, including refusals. A step that could
  not run says why; a step the product cannot do at all says *that*, which is a
  different sentence (D36).
* **It carries its scope.** Every step is judged against the same window and
  asset, so two steps cannot quietly disagree about which incident this is.

One correction from writing it: HLD §13.9 said persistence would go through the
site knowledge base. That was wrong on contact with the code — a `KnowledgeBase`
is an append-only set of FACTS, and an investigation is a mutable record of an
ACTIVITY. `sessions/` is the precedent that fits. The knowledge base is still
where the *conclusion* lands, through `case confirm`, exactly as before.
"""

from __future__ import annotations

import pytest

from iaiops.core.investigate.live import (
    advance,
    load_investigation,
    open_investigation,
    save_investigation,
)

pytestmark = pytest.mark.unit

WINDOW = ("2026-08-26T07:47:13Z", "2026-08-26T07:48:43Z")


@pytest.fixture
def store(tmp_path):
    """A store holding a window's worth of run-state samples."""
    db = tmp_path / "data.db"
    _write(
        db,
        [
            {"metric": "0", "value": 2.0, "timestamp": f"2026-08-26T07:47:{s:02d}Z"}
            for s in range(13, 53, 2)
        ],
    )
    return db


def _write(db, points: list[dict]) -> None:
    """Through the REAL write path.

    `SQLiteLocalSink.write` expects points that `normalize_points` has already
    shaped — a raw dict loses `quality` (it lives under `tags`) and stores the
    value as TEXT because `numeric` is unset. Fixtures that call the sink
    directly therefore hold data the product never produces, which is how the
    quality column looked broken until this was checked.
    """
    from iaiops.core.sink.push import historian_push

    result = historian_push(points, "sqlite", db_path=str(db), endpoint="line1", protocol="modbus")
    assert "error" not in result, result


@pytest.fixture
def opened(tmp_path, store):
    inv = open_investigation(
        endpoint="line1", start=WINDOW[0], end=WINDOW[1], asset="Line 1", site="default"
    )
    save_investigation(inv, base_dir=tmp_path)
    return inv


class TestItSurvivesTheProcess:
    def test_an_opened_investigation_can_be_loaded_back(self, tmp_path, opened):
        again = load_investigation(opened.id, base_dir=tmp_path)
        assert again.id == opened.id
        assert again.scope == opened.scope

    def test_the_scope_round_trips_intact(self, tmp_path, opened):
        """Every step is judged against this window. A scope that changed on
        reload would let two steps disagree about which incident this is."""
        again = load_investigation(opened.id, base_dir=tmp_path)
        assert again.scope.endpoint == "line1"
        assert again.scope.start == WINDOW[0] and again.scope.end == WINDOW[1]

    def test_advancing_is_persisted(self, tmp_path, store, opened):
        advanced = advance(opened, db_path=store)
        save_investigation(advanced, base_dir=tmp_path)
        again = load_investigation(opened.id, base_dir=tmp_path)
        assert [s.state for s in again.steps] == [s.state for s in advanced.steps]

    def test_loading_something_that_was_never_opened_says_so(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="line1-nope"):
            load_investigation("line1-nope", base_dir=tmp_path)

    def test_the_file_is_private(self, tmp_path, opened):
        """It carries an operator's incident record. `sessions/` holds this line
        and so must this."""
        import stat

        from iaiops.core.investigate.live import investigation_path

        path = investigation_path(opened.id, base_dir=tmp_path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


class TestEveryStepRecordsItsOwnOutcome:
    def test_all_eight_are_present_after_advancing(self, store, opened):
        assert [s.number for s in advance(opened, db_path=store).steps] == list(range(1, 9))

    def test_a_step_that_ran_carries_a_summary(self, store, opened):
        done = [s for s in advance(opened, db_path=store).steps if s.state == "done"]
        assert done, "a window with samples must complete something"
        assert all(s.summary for s in done)

    def test_evidence_collection_counts_what_the_window_actually_held(self, store, opened):
        step = _step(advance(opened, db_path=store), "collect_evidence")
        assert step.state == "done"
        assert "20" in step.summary, step.summary

    def test_a_step_with_no_input_refuses_rather_than_passing(self, store, opened):
        """Modbus surfaces no alarms, so step 4 has nothing to compress. That is
        a refusal with a reason — not a pass, and not a crash."""
        step = _step(advance(opened, db_path=store), "compress_and_rank")
        assert step.state == "refused"
        assert "alarm" in step.summary.lower()

    def test_the_knowledge_step_says_the_product_cannot_do_it(self, store, opened):
        """D36 — distinct from 'refused'. "We had no input" and "this product has
        no such capability" send a person to two different places."""
        step = _step(advance(opened, db_path=store), "knowledge_check")
        assert step.state == "not_possible"

    def test_refused_and_not_possible_are_different_states(self, store, opened):
        """The complement. Collapsing them would make the flag meaningless, which
        is what `expressible` exists to prevent."""
        states = {s.key: s.state for s in advance(opened, db_path=store).steps}
        assert states["compress_and_rank"] != states["knowledge_check"]


class TestTheDataCheckMeasuresTheRightThing:
    """Both halves of step 3, and my one-tag fixture hid both of them.

    A store INTERLEAVES tags: at 200 ms with three tags the rows land a few
    milliseconds apart in bursts. Judging the mixed series reported a "6 ms
    cadence" for a run that sampled every 200 ms — off by thirty times, in the
    direction that makes the data look finer-grained than it was — and a gap in
    a mixed series is not a gap in anything real. Then the 60 s default
    threshold reported "0 gaps" over a window with a genuine 13 s outage in it.
    """

    @pytest.fixture
    def three_tags_with_an_outage(self, tmp_path):
        """Three interleaved tags at 200 ms, with a 10-second hole in the middle."""
        db = tmp_path / "interleaved.db"
        rows = []
        for step in list(range(0, 50)) + list(range(100, 150)):  # 10s missing at 200ms
            base = 13.0 + step * 0.2
            for offset, tag in enumerate(("0", "10", "11")):
                stamp = base + offset * 0.003
                rows.append(
                    {
                        "metric": tag,
                        "value": 2.0,
                        "timestamp": f"2026-08-26T07:47:{stamp:06.3f}Z",
                    }
                )
        _write(db, rows)
        return db

    def _summary(self, db):
        inv = open_investigation(
            endpoint="line1", start="2026-08-26T07:47:00Z", end="2026-08-26T07:49:00Z"
        )
        return _step(advance(inv, db_path=db), "normalize_and_check").summary

    def test_the_cadence_is_the_sampling_rate_not_the_tag_spacing(self, three_tags_with_an_outage):
        summary = self._summary(three_tags_with_an_outage)
        assert "200ms cadence" in summary, summary

    def test_the_outage_is_found(self, three_tags_with_an_outage):
        """Three tags, one hole — each tag sees it, so three gaps. Zero would mean
        the threshold was judged against the wrong rate."""
        summary = self._summary(three_tags_with_an_outage)
        assert "3 gap(s)" in summary, summary

    def test_it_says_how_many_tags_it_checked(self, three_tags_with_an_outage):
        assert "3 tag(s)" in self._summary(three_tags_with_an_outage)


class TestTheRankingStepDoesNotRunOnNothing:
    """The mutation that survived the first version: turning this refusal into
    `done` kept all 20 tests green, because step 4 already stops the walk and no
    test looked at step 6's state directly.

    It matters because of what `done` would SAY. `downtime_rca` scores alarms, a
    dataflow verdict and per-tag quality flags. Handed a raw series with every
    sample marked good it answers "no candidate cause is supported" — which
    reads as *we looked and found nothing*, when the truth is *we handed it
    nothing to look at*. Same error the RCA copilot made this morning, pointed
    the other way, and worse here because it is silent.
    """

    def test_a_raw_series_is_refused_not_ranked(self, store, opened):
        step = _step(advance(opened, db_path=store), "test_hypotheses")
        assert step.state == "refused", step.summary

    def test_the_refusal_names_what_would_make_it_runnable(self, store, opened):
        """A refusal without that list is just a smaller complaint. Every item
        named is something this site can supply."""
        summary = _step(advance(opened, db_path=store), "test_hypotheses").summary.lower()
        assert "alarm" in summary and "quality" in summary, summary

    def test_a_window_with_quality_flags_is_actually_ranked(self, tmp_path):
        """The complement, and the one that stops the refusal from swallowing the
        step entirely: with something the ranker reads, it ranks."""
        db = tmp_path / "graded.db"
        _write(
            db,
            [
                {
                    "metric": "0",
                    "value": 2.0,
                    "timestamp": f"2026-08-26T07:47:{s:02d}Z",
                    "quality": "bad",
                }
                for s in range(13, 33, 2)
            ],
        )
        inv = open_investigation(endpoint="line1", start=WINDOW[0], end=WINDOW[1])
        step = _step(advance(inv, db_path=db), "test_hypotheses")
        assert step.state == "done", step.summary
        assert "graded sample" in step.summary, step.summary


class TestItNeverClaimsMoreThanItSaw:
    def test_an_empty_window_completes_nothing_and_says_why(self, tmp_path, store):
        """The window is real but holds no samples — the ordinary case when
        somebody guesses the time of the stoppage."""
        inv = open_investigation(
            endpoint="line1", start="2020-01-01T00:00:00Z", end="2020-01-01T01:00:00Z"
        )
        walked = advance(inv, db_path=store)
        evidence = _step(walked, "collect_evidence")
        assert evidence.state == "refused"
        assert "no samples" in evidence.summary.lower(), evidence.summary

    def test_it_does_not_reach_a_conclusion_without_evidence(self, tmp_path, store):
        inv = open_investigation(
            endpoint="line1", start="2020-01-01T00:00:00Z", end="2020-01-01T01:00:00Z"
        )
        assert _step(advance(inv, db_path=store), "conclude_and_close").state != "done"

    def test_a_window_with_evidence_does_reach_one(self, store, opened):
        """The complement: refusing everything would pass the two tests above."""
        assert _step(advance(opened, db_path=store), "conclude_and_close").state == "done"

    def test_the_walk_stops_where_the_evidence_stops(self, tmp_path, store):
        inv = open_investigation(
            endpoint="line1", start="2020-01-01T00:00:00Z", end="2020-01-01T01:00:00Z"
        )
        assert advance(inv, db_path=store).reached == 1


class TestAdvancingIsIdempotent:
    def test_walking_twice_gives_the_same_answer(self, store, opened):
        """A step is a function of the scope and the store, not of how many times
        somebody pressed the button."""
        first = advance(opened, db_path=store)
        second = advance(first, db_path=store)
        assert [(s.key, s.state) for s in first.steps] == [(s.key, s.state) for s in second.steps]

    def test_it_does_not_mutate_what_it_was_given(self, store, opened):
        before = [s.state for s in opened.steps]
        advance(opened, db_path=store)
        assert [s.state for s in opened.steps] == before


def _step(inv, key: str):
    return next(s for s in inv.steps if s.key == key)
