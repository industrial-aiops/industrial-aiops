"""How far into an investigation could this site actually get?

`readiness` answers "which SCENARIOS can this site run today". This answers the
next question down: **if something stopped tomorrow, how many of the eight
investigation steps could we actually walk** — and for each one we could not,
what is missing and whether the product even offers a way to supply it.

HLD §13. The eight steps come from a mature IT-side investigation practice
(§10.3④ took the scoring half of the same material; this is the container half).
Three rules from that section are load-bearing here:

* **D33 — dry and live differ only in where `scope` comes from.** This module is
  the dry half: no incident, no device contact, no analysis. It answers the
  capability question only.
* **D36 — a step with no way to supply its inputs reports `expressible=False`,
  it does not silently pass.** A skipped step reads as "checked, nothing wrong",
  which is the worst of the three possible messages.
* **A blocked step does not necessarily block the ones after it.** Knowledge
  check (07) is missing entirely today, and a conclusion (08) is still reachable
  without it — saying otherwise would understate the site.

The whole module touches nothing: no device, no network, no historian. It reads
the config and the local store, exactly as `readiness` does.
"""

from __future__ import annotations

import pytest

from iaiops.core.investigate.assess import assess_investigation
from iaiops.core.investigate.steps import STEP_KEYS

pytestmark = pytest.mark.unit


@pytest.fixture
def bare(tmp_path):
    """A site with nothing: no config, no store. The state a first run is in."""
    return assess_investigation(config=_config([]), db_path=tmp_path / "missing.db")


@pytest.fixture
def collecting(tmp_path):
    """A site that has an endpoint and has collected some history."""
    from iaiops.core.sink.sqlite_local import SQLiteLocalSink

    db = tmp_path / "data.db"
    sink = SQLiteLocalSink(db_path=str(db), endpoint="line1", protocol="modbus")
    sink.write(
        [{"metric": "0", "value": 2.0, "timestamp": f"2026-08-26T07:4{n}:13Z"} for n in range(1, 9)]
    )
    return assess_investigation(config=_config(["line1"]), db_path=db)


def _config(endpoint_names: list[str]):
    """A minimal stand-in for the loaded config — only what the steps read."""

    class _Tag:
        def __init__(self, ref):
            self.ref = ref
            self.role = ""
            self.label = ""

    class _Target:
        def __init__(self, name):
            self.name = name
            self.protocol = "modbus"
            self.tags = (_Tag("0"),)

    class _Config:
        def __init__(self, names):
            self.targets = tuple(_Target(n) for n in names)
            self.historian = None

    return _Config(endpoint_names)


class TestItReportsAllEightSteps:
    def test_every_step_is_present(self, bare):
        assert [s["key"] for s in bare.as_dict()["steps"]] == list(STEP_KEYS)

    def test_they_are_numbered_in_order(self, bare):
        assert [s["number"] for s in bare.as_dict()["steps"]] == list(range(1, 9))

    def test_each_one_says_what_it_would_give_you(self, bare):
        """A blocked row still has to explain what is being missed, or the report
        is a list of complaints rather than a gap analysis."""
        assert all(s["value"] for s in bare.as_dict()["steps"])

    def test_nothing_was_contacted(self, bare, monkeypatch):
        """The whole point of the dry mode: it must be runnable on a site nobody
        has given you permission to probe yet."""
        import socket

        def _forbidden(*_a, **_k):
            raise AssertionError("the dry assessment must not open a socket")

        monkeypatch.setattr(socket.socket, "connect", _forbidden)
        monkeypatch.setattr(socket, "create_connection", _forbidden)
        assess_investigation(config=_config(["line1"]))


class TestHowFarThisSiteCouldGet:
    def test_a_bare_site_stops_at_the_first_step(self, bare):
        """Nothing configured: you cannot even define an incident against an
        endpoint you do not have."""
        assert bare.reachable_through == 0

    def test_a_collecting_site_gets_further(self, collecting):
        assert collecting.reachable_through >= 2, collecting.as_dict()["steps"]

    def test_reachable_through_stops_at_the_first_blocked_step(self, bare):
        """It is a WALK, not a count of unblocked steps: step 5 being fine does
        not help anyone who cannot get past step 2."""
        d = bare.as_dict()
        first_blocked = next(s["number"] for s in d["steps"] if s["status"] == "blocked")
        assert d["reachable_through"] == first_blocked - 1

    def test_the_walk_is_not_a_count_of_unblocked_steps(self, collecting):
        """The mutation that survived the first version of this file.

        Both fixtures happened to make the two formulas agree, and the only test
        that pinned the semantics ran on the bare one — so replacing the walk
        with `sum(1 for s in steps if s.status != BLOCKED)` kept all 13 green.
        A Modbus line distinguishes them: the walk reaches 3, the count says 6,
        and only the walk answers "how far could we actually get".
        """
        d = collecting.as_dict()
        unblocked = sum(1 for s in d["steps"] if s["status"] != "blocked")
        assert d["reachable_through"] == 3, d["steps"]
        assert unblocked != d["reachable_through"], (
            "this fixture must distinguish the two formulas, or it pins nothing"
        )

    def test_steps_blocked_beyond_the_walk_are_reported_separately(self, collecting):
        """A gap at step 7 is real, but it is not why the walk stopped at 3.
        Merging the two would tell an operator to go fix the wrong thing."""
        d = collecting.as_dict()
        assert "knowledge_check" in d["blocked_later"]
        assert "compress_and_rank" not in d["blocked_later"], (
            "the step that STOPPED the walk is not a later blocker"
        )

    def test_a_later_blocked_step_does_not_erase_the_earlier_ones(self, collecting):
        """Knowledge check (07) is missing entirely today. Reporting the site as
        "cannot investigate" because of it would understate what it can do."""
        d = collecting.as_dict()
        assert d["reachable_through"] >= 2
        assert any(s["status"] == "blocked" for s in d["steps"])


class TestTheKnowledgeStepAdmitsThereIsNoWayToSupplyIt:
    """D36. This is the one step where "you have not configured it" is a lie."""

    def test_it_is_marked_not_yet_expressible(self, collecting):
        step = _step(collecting, "knowledge_check")
        unmet = [r for r in step["requirements"] if not r["met"]]
        assert unmet, "the knowledge step cannot be satisfiable today"
        assert any(r.get("not_yet_expressible") for r in unmet), unmet

    def test_it_is_not_silently_skipped(self, collecting):
        """A skipped step reads as 'checked, nothing wrong' — the worst of the
        three possible messages."""
        assert _step(collecting, "knowledge_check")["status"] != "ready"

    def test_the_others_are_not_marked_that_way(self, collecting):
        """The complement: `not_yet_expressible` must mean something. If every
        gap carried it, it would carry no information."""
        flagged = {
            s["key"]
            for s in collecting.as_dict()["steps"]
            for r in s["requirements"]
            if r.get("not_yet_expressible")
        }
        assert "collect_evidence" not in flagged and "define_incident" not in flagged


class TestClosingAGapTurnsTheFlagOff:
    """`expressible` has to stop being set the moment a command can supply it.

    Cross-asset propagation reported "this product offers no way to supply it
    yet" until `iaiops relations declare` existed. It was accurate then. A flag
    left True after the gap closed would send somebody to write a feature that is
    already there — and worse, it would make the flag mean nothing (D36).
    """

    def test_propagation_relations_is_now_an_ordinary_unmet_requirement(self, collecting):
        req = _requirement(collecting, "correlate_timeline", "propagation_relations")
        assert not req["met"]
        assert not req.get("not_yet_expressible"), req
        assert "relations declare" in req["fix"], req["fix"]

    def test_declaring_one_satisfies_it(self, tmp_path, monkeypatch):
        """The complement, and the proof the count is read rather than assumed."""
        from iaiops.core.knowledge import relations as rel

        monkeypatch.setattr(
            rel, "line_relations", lambda site="default", base_dir=None: (object(),)
        )
        report = assess_investigation(config=_config(["line1"]), db_path=tmp_path / "none.db")
        assert _requirement(report, "correlate_timeline", "propagation_relations")["met"]

    def test_the_knowledge_step_is_still_flagged(self, collecting):
        """The one gap that is still genuinely impossible must keep the flag, or
        closing one gap would have quietly disarmed the whole mechanism."""
        req = _requirement(collecting, "knowledge_check", "mechanism_library")
        assert req.get("not_yet_expressible") is True


class TestTheGapsAreActionable:
    def test_every_unmet_requirement_carries_a_next_step(self, bare):
        """`fix` is the difference between a gap analysis and a list of
        complaints — except where the product offers no way at all, which is
        what `not_yet_expressible` is for."""
        for step in bare.as_dict()["steps"]:
            for req in step["requirements"]:
                if req["met"] or req.get("not_yet_expressible"):
                    continue
                assert req["fix"], f"{step['key']}/{req['key']} has no next step"

    def test_a_met_requirement_says_what_was_actually_found(self, collecting):
        """Never a guess. `readiness` holds this line and so must this."""
        met = [r for s in collecting.as_dict()["steps"] for r in s["requirements"] if r["met"]]
        assert met, "a collecting site must satisfy something"
        assert all(r["detail"] for r in met)


def _requirement(report, step_key: str, req_key: str) -> dict:
    return next(r for r in _step(report, step_key)["requirements"] if r["key"] == req_key)


def _step(report, key: str) -> dict:
    return next(s for s in report.as_dict()["steps"] if s["key"] == key)
