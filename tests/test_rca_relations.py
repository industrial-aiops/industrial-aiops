"""Telling the stoppage that started it from the ones that merely followed.

`_proximity_scale` weights evidence by time alone, which is the honest half of
the axis. After one upstream stop, `downtime_rca` run per asset returns a
confident local root cause for every downstream machine — each internally
consistent, each citing real signals, and all but one about a machine that
stopped because it was starved. The distinguishing fact is not in the evidence;
it is the line's topology.

The guards below are mostly about the two ways this could quietly go wrong:
inferring topology from co-occurrence (which on a production line is guaranteed,
so it would manufacture causality), and ignoring time (an upstream asset that
stopped later cannot have caused an earlier stop).
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.rca_relations import (
    CONSEQUENCE,
    NOT_EVALUABLE,
    ORIGIN,
    UNATTRIBUTED,
    attribute_downtime,
)
from iaiops.core.knowledge.relations import declare_relation

pytestmark = pytest.mark.unit


@pytest.fixture
def home(tmp_path):
    """The knowledge store resolves through CONFIG_DIR, not IAIOPS_HOME.

    Setting the env var did NOT isolate it: the first run of this file read the
    developer's own declared relations and "passed" the no-relations case for the
    wrong reason. Pass base_dir explicitly, as tests/test_line_relations.py does.
    """
    return tmp_path


def _line(site):
    """filler → capper → labeller → palletiser"""
    for up, down in (("filler", "capper"), ("capper", "labeller"), ("labeller", "palletiser")):
        declare_relation(up, down, by="test", base_dir=site)


def _stops(*pairs):
    return [{"asset": a, "start": f"2026-01-05T06:{m:02d}:00Z"} for a, m in pairs]


# ─── no declared topology: refuse, do not infer ──────────────────────────────


def test_without_declared_relations_nothing_is_attributed(home):
    out = attribute_downtime(_stops(("filler", 0), ("capper", 1), ("labeller", 2)), base_dir=home)
    assert out["verdict"] == NOT_EVALUABLE
    assert {a["status"] for a in out["attributions"]} == {NOT_EVALUABLE}
    assert "Co-occurrence is NOT used" in out["reason"]
    assert "relations declare" in out["reason"]


def test_co_occurrence_alone_never_creates_an_edge(home):
    """Three assets stopping in sequence is a line running normally, not evidence."""
    out = attribute_downtime(_stops(("a", 0), ("b", 1), ("c", 2)), base_dir=home)
    assert out["relations_declared"] == 0
    assert not out.get("origins")


# ─── the ordinary case ───────────────────────────────────────────────────────


def test_the_upstream_stop_is_the_origin_and_the_rest_are_consequences(home):
    _line(home)
    out = attribute_downtime(_stops(("filler", 0), ("capper", 1), ("labeller", 2)), base_dir=home)

    assert out["verdict"] == ORIGIN
    assert out["origins"] == ["filler"]
    assert out["consequence_count"] == 2
    by = {a["asset"]: a for a in out["attributions"]}
    assert by["capper"]["status"] == CONSEQUENCE
    assert by["capper"]["origin_asset"] == "filler"
    assert by["capper"]["hops_upstream"] == 1
    # The chain is preserved rather than flattened: labeller was starved by the
    # capper next to it, which was starved by the filler. Attributing every row
    # straight to the far end would lose which link actually stopped feeding it.
    assert by["labeller"]["origin_asset"] == "capper"
    assert by["labeller"]["hops_upstream"] == 1
    assert by["filler"]["explains"] == ["capper", "labeller"]


def test_the_nearest_upstream_that_stopped_first_wins(home):
    """Two valid candidates upstream — attribute to the closer link, not the far end."""
    _line(home)
    out = attribute_downtime(_stops(("filler", 0), ("capper", 1), ("labeller", 2)), base_dir=home)
    by = {a["asset"]: a for a in out["attributions"]}
    assert by["labeller"]["origin_asset"] == "capper", "flattened the chain to the far end"
    assert by["capper"]["origin_asset"] == "filler"
    assert out["origins"] == ["filler"], "only the asset nothing fed is the origin"


# ─── time still has to hold ──────────────────────────────────────────────────


def test_an_upstream_asset_that_stopped_later_explains_nothing(home):
    _line(home)
    out = attribute_downtime(_stops(("capper", 0), ("filler", 5)), base_dir=home)
    by = {a["asset"]: a for a in out["attributions"]}
    assert by["capper"]["status"] != CONSEQUENCE, "attributed to a stop that came after it"
    assert by["filler"]["status"] in (ORIGIN, UNATTRIBUTED)


def test_a_stop_far_outside_the_window_is_not_attributed(home):
    _line(home)
    out = attribute_downtime(
        [
            {"asset": "filler", "start": "2026-01-05T06:00:00Z"},
            {"asset": "capper", "start": "2026-01-05T09:00:00Z"},
        ],
        base_dir=home,
    )
    by = {a["asset"]: a for a in out["attributions"]}
    assert by["capper"]["status"] == UNATTRIBUTED
    assert "no declared upstream asset stopped before it" in by["capper"]["detail"]


def test_the_window_is_adjustable(home):
    _line(home)
    out = attribute_downtime(
        [
            {"asset": "filler", "start": "2026-01-05T06:00:00Z"},
            {"asset": "capper", "start": "2026-01-05T09:00:00Z"},
        ],
        max_lead_s=4 * 3600,
        base_dir=home,
    )
    by = {a["asset"]: a for a in out["attributions"]}
    assert by["capper"]["status"] == CONSEQUENCE


# ─── direction is not symmetric ──────────────────────────────────────────────


def test_a_downstream_stop_never_explains_an_upstream_one(home):
    """The direction IS the content of the fact."""
    _line(home)
    out = attribute_downtime(_stops(("palletiser", 0), ("filler", 1)), base_dir=home)
    by = {a["asset"]: a for a in out["attributions"]}
    assert by["filler"]["status"] != CONSEQUENCE


def test_an_unrelated_asset_is_left_unattributed_not_folded_in(home):
    _line(home)
    out = attribute_downtime(_stops(("filler", 0), ("capper", 1), ("boiler", 1)), base_dir=home)
    by = {a["asset"]: a for a in out["attributions"]}
    assert by["boiler"]["status"] == UNATTRIBUTED
    assert "boiler" not in by["filler"]["explains"]


def test_rows_without_an_asset_or_a_timestamp_are_dropped(home):
    _line(home)
    out = attribute_downtime(
        [{"asset": "filler"}, {"start": "2026-01-05T06:00:00Z"}, "nope"], base_dir=home
    )
    assert out["stoppages_evaluated"] == 0


def test_the_tool_is_governed_and_read_only():
    import mcp_server.tools.diagnostics_tools as mod

    fn = mod.downtime_attribution
    assert getattr(fn, "_is_governed_tool", False)
    assert (fn.__doc__ or "").startswith("[READ]")
