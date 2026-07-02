"""信创 compliance-mapping + national-TSDB historian-sink tests (no live DB).

The compliance map is pure data. The sink adapters' DB libraries are unverified
and lazy-imported, so the push path is exercised by monkeypatching the sink
factory with a fake adapter — proving normalization, numeric filtering, and the
tally without TDengine/IoTDB installed.
"""

from __future__ import annotations

import pytest

from iaiops.core.brain.compliance import (
    DENGBAO_LEVELS,
    compliance_dengbao_levels,
    compliance_frameworks,
    compliance_mapping,
)
from iaiops.core.sink import base as sink_base
from iaiops.core.sink import push as sink_push
from iaiops.core.sink.base import normalize_points

# ─── compliance mapping ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_compliance_mapping_shape():
    out = compliance_mapping()
    assert out["control_count"] == len(out["controls"])
    assert set(out["status_summary"]) == {"addressed", "partial", "待核实"}
    # Every control is honest: has a status and a named gap field.
    for c in out["controls"]:
        assert c["status"] in ("addressed", "partial", "待核实")
        assert "gap" in c and "iaiops" in c


@pytest.mark.unit
def test_compliance_sorted_addressed_first():
    statuses = [c["status"] for c in compliance_mapping()["controls"]]
    # addressed rows come before partial/待核实 rows.
    assert statuses.index("addressed") < statuses.index("待核实")


@pytest.mark.unit
def test_compliance_mapping_carries_crosswalk():
    # Expansion: every control also maps to 等保 2.0 + IEC 62443.
    out = compliance_mapping()
    assert set(out["frameworks"]) == {"gjzn", "dengbao", "iec62443"}
    for c in out["controls"]:
        xw = c["crosswalk"]
        assert xw["dengbao"] and xw["iec62443"]


@pytest.mark.unit
def test_compliance_frameworks_crosswalk_complete():
    out = compliance_frameworks()
    assert out["framework_count"] == 3
    assert out["pillar_count"] == len(out["crosswalk"])
    assert {f["id"] for f in out["frameworks"]} == {"gjzn", "dengbao", "iec62443"}
    # Every pillar has a concrete (non-待核实) 等保 + 62443 clause mapped.
    for row in out["crosswalk"]:
        for key in ("gjzn", "dengbao", "iec62443", "iaiops_status"):
            assert row[key]
        assert row["dengbao"] != "待核实"
        assert "FR" in row["iec62443"]


@pytest.mark.unit
def test_compliance_frameworks_tool_governed():
    from mcp_server.tools.compliance_tools import compliance_frameworks as tool

    assert getattr(tool, "_is_governed_tool", False) is True
    assert getattr(tool, "_risk_level", "") == "low"


# ─── 等保 2.0 per-level deltas ─────────────────────────────────────────────────


@pytest.mark.unit
def test_dengbao_levels_both_shape():
    out = compliance_dengbao_levels()
    assert out["selected_level"] is None
    assert out["pillar_count"] == len(DENGBAO_LEVELS)
    assert {m["id"] for m in out["levels"]} == {"l2", "l3"}
    # Both levels present → each delta carries the 二级 baseline and 三级 增量.
    for d in out["deltas"]:
        assert d["l2_requires"] and d["l3_adds"]
        assert d["iaiops"] and d["iaiops_status"]
        assert "gap" in d


@pytest.mark.unit
@pytest.mark.parametrize(
    "given,expected,present,absent",
    [
        ("l2", "l2", "l2_requires", "l3_adds"),
        ("三级", "l3", "l3_adds", "l2_requires"),
        ("2", "l2", "l2_requires", "l3_adds"),
        ("3", "l3", "l3_adds", "l2_requires"),
    ],
)
def test_dengbao_levels_focus_one_level(given, expected, present, absent):
    out = compliance_dengbao_levels(given)
    assert out["selected_level"] == expected
    assert {m["id"] for m in out["levels"]} == {expected}
    for d in out["deltas"]:
        assert present in d
        assert absent not in d


@pytest.mark.unit
def test_dengbao_levels_status_matches_controls():
    """The per-level view reuses the honest CONTROLS status (no fabricated claim)."""
    from iaiops.core.brain.compliance import CONTROLS

    status_by_pillar = {c["pillar"]: c["status"] for c in CONTROLS}
    for d in compliance_dengbao_levels()["deltas"]:
        assert d["iaiops_status"] == status_by_pillar[d["pillar"]]


@pytest.mark.unit
def test_dengbao_levels_unknown_level_raises():
    with pytest.raises(ValueError, match="Unknown 等保 level"):
        compliance_dengbao_levels("level9")


@pytest.mark.unit
def test_dengbao_levels_tool_governed_low():
    from mcp_server.tools.compliance_tools import compliance_dengbao_levels as tool

    assert getattr(tool, "_is_governed_tool", False) is True
    assert getattr(tool, "_risk_level", "") == "low"


# ─── point normalization ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_normalize_varied_point_shapes():
    pts = normalize_points([
        {"ref": "line1.temp", "value": 21.5, "timestamp": "2026-06-29T10:00:00"},
        {"object_type": "analogInput", "instance": 3, "present_value": 7.0},
        {"io_address": 1001, "value": 50},
        {"type": "analog_input", "index": 2, "value": "n/a"},  # non-numeric
        "not-a-dict",
    ])
    metrics = [p["metric"] for p in pts]
    assert "line1.temp" in metrics
    assert "analogInput.3" in metrics
    assert "ioa.1001" in metrics
    non_numeric = [p for p in pts if not p["numeric"]]
    assert len(non_numeric) == 1


# ─── historian push ──────────────────────────────────────────────────────────


class _FakeSink:
    def __init__(self):
        self.written: list = []
        self.closed = False

    def write(self, points):
        self.written = list(points)
        return len(points)

    def close(self):
        self.closed = True


@pytest.mark.unit
def test_push_writes_numeric_only(monkeypatch):
    fake = _FakeSink()
    monkeypatch.setattr(sink_push, "get_sink", lambda kind, **o: fake)
    out = sink_push.historian_push(
        [{"ref": "a", "value": 1.0}, {"ref": "b", "value": "bad"}],
        sink="tdengine", host="10.0.0.20", database="iaiops",
    )
    assert out["written"] == 1
    assert out["skipped_non_numeric"] == 1
    assert out["sink"] == "tdengine"
    assert fake.closed is True


@pytest.mark.unit
def test_push_unknown_sink_errors():
    out = sink_push.historian_push([{"ref": "a", "value": 1}], sink="influxdb")
    assert "error" in out


@pytest.mark.unit
def test_push_empty_points_errors(monkeypatch):
    monkeypatch.setattr(sink_push, "get_sink", lambda kind, **o: _FakeSink())
    out = sink_push.historian_push([], sink="iotdb")
    assert "error" in out


@pytest.mark.unit
def test_push_surfaces_sink_error(monkeypatch):
    class _Boom:
        def write(self, points):
            raise sink_base.SinkError("taospy not installed")

        def close(self):
            pass

    monkeypatch.setattr(sink_push, "get_sink", lambda kind, **o: _Boom())
    out = sink_push.historian_push([{"ref": "a", "value": 1}], sink="tdengine")
    assert "error" in out and "taospy" in out["error"]


@pytest.mark.unit
def test_get_sink_unknown_raises():
    with pytest.raises(sink_base.SinkError, match="Unknown historian sink"):
        sink_base.get_sink("redis")


@pytest.mark.unit
def test_push_wraps_unexpected_adapter_error(monkeypatch):
    class _Boom:
        def write(self, points):
            raise RuntimeError("taos.connect refused")  # not a SinkError

        def close(self):
            pass

    monkeypatch.setattr(sink_push, "get_sink", lambda kind, **o: _Boom())
    out = sink_push.historian_push([{"ref": "a", "value": 1}], sink="tdengine")
    assert "error" in out and "refused" in out["error"]  # converted to a tally error, not raised


@pytest.mark.unit
def test_tdengine_escapes_quotes_in_timestamp_and_sanitizes_idents():
    from iaiops.core.sink.tdengine import TDengineSink, _safe_ident, _ts_clause

    # A timestamp carrying a quote is escaped (no SQL break-out).
    assert _ts_clause("x') DROP") == "'x'') DROP'"
    assert _ts_clause("") == "NOW"
    # DB / super-table identifiers are reduced to alnum/underscore.
    assert _safe_ident("ia;DROP", "fb") == "ia_DROP"
    assert _safe_ident("", "fb") == "fb"
    sink = TDengineSink(database="bad;name", stable="bad-stable")
    assert sink._database == "bad_name"
    assert sink._stable == "bad_stable"


@pytest.mark.unit
def test_historian_push_tool_is_low_risk_and_governed():
    # Pin the governance contract: egress write stays at the declared tier.
    from mcp_server.tools.compliance_tools import compliance_mapping, historian_push

    assert getattr(historian_push, "_is_governed_tool", False) is True
    assert getattr(historian_push, "_risk_level", "") == "low"
    assert getattr(compliance_mapping, "_is_governed_tool", False) is True


@pytest.mark.unit
def test_iotdb_missing_timestamp_is_now_not_epoch_zero():
    from datetime import UTC, datetime

    from iaiops.core.sink.iotdb import _ts_millis

    assert _ts_millis("") > 0  # falls back to now(UTC), never 1970
    # A naive stamp and its explicit-UTC form resolve to the SAME epoch (no host-tz drift).
    assert _ts_millis("2026-06-29T10:00:00") == _ts_millis("2026-06-29T10:00:00Z")
    expected = int(datetime(2026, 6, 29, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    assert _ts_millis("2026-06-29T10:00:00Z") == expected
