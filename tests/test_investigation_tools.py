"""The investigation layer through the OTHER front end.

HLD §3.1 states the core invariant: **two front-ends, one engine**. `iaiops
investigate plan` and the `investigation_readiness` tool must be the same answer
computed once, differing only in how it is drawn.

Everything built this week — `readiness` before it, then `investigate`,
`relations` and `knowledge` — shipped **CLI-only**. The claim was in the HLD and
in the README the whole time; nothing checked it. A front-end that exists in the
architecture diagram and not in the code is the same shape as every other defect
this repo keeps finding: the capability is there, one of the two ways in is not.

So these tests are mostly about **agreement**. A tool that returns a plausible
answer of its own is worse than a missing tool: it makes the two front-ends drift
apart while both look healthy, and nothing marks where they diverged.

Governance is the other half. Every MCP tool in this repo carries
`@governed_tool` — audit, budget, risk tier — and a tool that skipped it would be
an unaudited path into the same engine.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def tools():
    from mcp_server.tools import investigation_tools

    return investigation_tools


@pytest.fixture
def site(tmp_path, monkeypatch):
    """An isolated site: config dir, knowledge base and store all under tmp."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from iaiops.core.runtime import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".iaiops", raising=False)
    return tmp_path


class TestEveryToolIsGoverned:
    """A tool that skipped the harness would be an unaudited path into the same
    engine — the one thing the governance spine exists to prevent."""

    @pytest.mark.parametrize(
        "name",
        [
            "investigation_readiness",
            "investigation_open",
            "investigation_show",
            "line_relation_declare",
            "line_relations_list",
            "mechanism_library_check",
        ],
    )
    def test_it_carries_the_governance_marker(self, tools, name):
        fn = getattr(tools, name)
        assert getattr(fn, "_is_governed_tool", False), f"{name} is not governed"

    def test_the_declaring_tool_follows_the_local_write_convention(self, tools):
        """`[READ]` in this repo means "does not write to a DEVICE" — the hint
        module derives `readOnlyHint` from risk level, preview mode and egress,
        not from local writes, and `baseline_record_change` / `adopt_alias_map`
        are the same shape.

        The first version of this test asserted the opposite from first
        principles and made the tag contradict the derived hint, which
        `test_mcp_tool_hints` caught. The convention is the repo's, not mine.
        """
        doc = tools.line_relation_declare.__doc__ or ""
        assert doc.startswith("[READ][risk=low]"), doc[:80]
        assert "into the site knowledge base" in doc, "it must still say that it writes"


class TestTheTwoFrontEndsAgree:
    """§3.1. The engine answers once; each front-end draws it."""

    def test_readiness_matches_the_cli_engine(self, site):
        from iaiops.core.investigate import assess_investigation
        from mcp_server.tools import investigation_tools

        engine = assess_investigation().as_dict()
        tool = investigation_tools.investigation_readiness()
        assert tool["reachable_through"] == engine["reachable_through"]
        assert [s["key"] for s in tool["steps"]] == [s["key"] for s in engine["steps"]]

    def test_step_states_agree_too(self, site):
        """Not just the shape — the verdicts. Two front-ends that agree on the
        list of steps and disagree on which are blocked have drifted in the way
        that matters."""
        from iaiops.core.investigate import assess_investigation
        from mcp_server.tools import investigation_tools

        engine = assess_investigation().as_dict()
        tool = investigation_tools.investigation_readiness()
        assert [s["status"] for s in tool["steps"]] == [s["status"] for s in engine["steps"]]

    def test_relations_round_trip_through_the_tool(self, site, tools):
        tools.line_relation_declare(upstream="press", downstream="oven", by="wei")
        listed = tools.line_relations_list()
        assert [(r["upstream"], r["downstream"]) for r in listed["relations"]] == [
            ("press", "oven")
        ]

    def test_a_relation_declared_by_the_tool_is_visible_to_the_engine(self, site, tools):
        """The proof that it is one engine and not two stores."""
        from iaiops.core.knowledge.relations import line_relations

        tools.line_relation_declare(upstream="press", downstream="oven", by="wei")
        assert [r.downstream for r in line_relations()] == ["oven"]


class TestTheToolsRefuseTheSameThings:
    """A front-end that is more permissive than the other is a way around the
    refusals, and the refusals are the product."""

    def test_declaring_a_cycle_is_refused(self, site, tools):
        tools.line_relation_declare(upstream="press", downstream="oven", by="wei")
        out = tools.line_relation_declare(upstream="oven", downstream="press", by="wei")
        assert "error" in out and "cycle" in out["error"].lower()

    def test_declaring_without_an_author_is_refused(self, site, tools):
        out = tools.line_relation_declare(upstream="press", downstream="oven", by="")
        assert "error" in out

    def test_an_unknown_cause_is_nothing_known_not_cleared(self, site, tools):
        """The refusal that matters most, and it has to hold on both sides."""
        out = tools.mechanism_library_check(cause="sensor_fault")
        assert out["status"] == "nothing_known"
        assert out["excluded"] is False


class TestOpeningAnInvestigation:
    def test_it_walks_and_persists(self, site, tools):
        opened = tools.investigation_open(
            endpoint="line1", start="2026-08-26T10:00:00Z", end="2026-08-26T10:10:00Z"
        )
        assert opened["total_steps"] == 8
        again = tools.investigation_show(investigation_id=opened["id"])
        assert again["id"] == opened["id"]

    def test_showing_one_that_does_not_exist_is_an_error_not_a_blank(self, site, tools):
        out = tools.investigation_show(investigation_id="nope")
        assert "error" in out

    def test_a_missing_window_is_refused(self, site, tools):
        out = tools.investigation_open(endpoint="line1", start="", end="")
        assert "error" in out
