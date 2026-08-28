"""`readiness` through the MCP front end — the last CLI-only command.

HLD §3.1: **two front-ends, one engine**. `iaiops readiness --json` and the
`site_readiness` tool must be the same answer computed once, differing only in
how it is drawn.

`readiness` (#166) predates the investigation layer and outlived every other
CLI-only gap: PR #205 gave `investigate` / `relations` / `knowledge` their tools
and deliberately left this one out rather than smuggling it in. Its own engine
test has carried `test_the_report_serializes_for_a_second_front_end` since the
day it was written — the second front end just did not exist.

What is actually at risk here is not the happy path. `readiness` is a machine for
reporting gaps, so the failure that would matter is a front end that reports
*fewer* gaps than the other, or reports them less honestly — a tool that returned
the capability list but dropped `blocked_on`, or quietly ignored the `db` it was
handed and answered about a different site.
"""

from __future__ import annotations

import pytest
from test_readiness import store_with

from iaiops.core.readiness import assess

pytestmark = pytest.mark.unit


@pytest.fixture
def tools():
    from mcp_server.tools import overview_tools

    return overview_tools


@pytest.fixture
def unconfigured(tmp_path, monkeypatch):
    """A site with no config at all — the state a first-time caller is in."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from iaiops.core.runtime import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".iaiops", raising=False)
    return tmp_path


class TestItIsGoverned:
    def test_the_tool_carries_the_governance_marker(self, tools):
        """An ungoverned tool is an unaudited path into the same engine."""
        assert getattr(tools.site_readiness, "_is_governed_tool", False)

    def test_it_is_declared_read_only(self, tools):
        doc = tools.site_readiness.__doc__ or ""
        assert doc.startswith("[READ][risk=low]"), doc[:80]


class TestTheTwoFrontEndsAgree:
    def test_it_is_the_engine_answer_verbatim(self, unconfigured, tools):
        """Not "equivalent" — identical. The tool recomputes nothing, so any
        divergence at all is the tool having formed an opinion of its own."""
        db = unconfigured / "none.db"
        assert tools.site_readiness(db=str(db)) == assess(db_path=db).as_dict()

    def test_the_ranked_gap_list_survives(self, unconfigured, tools):
        """`blocked_on` is the actionable half — one missing thing usually
        unlocks several scenarios, and it names that thing. A tool that returned
        the capability rows without it would look complete and be useless."""
        out = tools.site_readiness(db=str(unconfigured / "none.db"))
        assert out["blocked_on"], out.keys()

    def test_a_blocked_site_is_reported_blocked(self, unconfigured, tools):
        out = tools.site_readiness(db=str(unconfigured / "none.db"))
        assert out["summary"]["blocked"] > 0

    def test_the_notes_that_say_nothing_was_contacted_survive(self, unconfigured, tools):
        """The posture claim is part of the answer: it is what makes the report
        safe to run against a site nobody has been authorised to probe."""
        out = tools.site_readiness(db=str(unconfigured / "none.db"))
        assert any("Nothing was contacted" in n for n in out["notes"])


class TestTheDbArgumentActuallyRoutes:
    """The likeliest real bug: accepting `db` and ignoring it. Every assertion
    above would still pass while the tool answered about a different site."""

    def test_a_store_with_history_is_seen_through_the_tool(self, unconfigured, tools):
        out = tools.site_readiness(db=str(store_with(unconfigured)))
        assert out["facts"]["store"]["samples"] == 160
        assert out["facts"]["store"]["exists"] is True

    def test_a_different_path_gives_a_different_answer(self, unconfigured, tools):
        """The complement. Without it, a tool hardcoding one store passes above."""
        with_history = tools.site_readiness(db=str(store_with(unconfigured)))
        without = tools.site_readiness(db=str(unconfigured / "nowhere.db"))
        assert without["facts"]["store"]["exists"] is False
        assert with_history["facts"]["store"] != without["facts"]["store"]

    def test_omitting_db_falls_back_to_the_default_store(self, unconfigured, tools):
        """An empty string must mean "the iaiops store", not a file called ""."""
        out = tools.site_readiness()
        assert "error" not in out
        assert out["facts"]["store"]["exists"] is False


class TestHistoryChangesTheVerdict:
    def test_samples_unblock_the_capabilities_that_only_needed_them(self, unconfigured, tools):
        """The complement to `test_a_blocked_site_is_reported_blocked`: a tool
        that always answered "blocked" would satisfy every refusal test here."""
        empty = tools.site_readiness(db=str(unconfigured / "none.db"))
        loaded = tools.site_readiness(db=str(store_with(unconfigured)))
        assert loaded["summary"]["ready"] > empty["summary"]["ready"]
