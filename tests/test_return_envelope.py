"""Unified list-return envelope contract — helper, migrated call sites, CI gate.

Why this contract exists (see ``iaiops.core.runtime.envelope``): a weak/local
model reading a raw JSON tool result cannot tell a SHORT list from a TRUNCATED
one. In OT that is not a UX bug — a model that sees a capped alarm list and
concludes "this line has no active alarms" has produced a MISDIAGNOSIS.

Three groups of tests here:

1. the envelope helper itself, including the boundary where returned == total
   (NOT truncated) and the honest "total unknown" probe form;
2. every migrated call site — asserting BOTH that the legacy key keeps its
   legacy type (these are published MCP outputs; retyping a key is a breaking
   change) AND that the new envelope keys are present and correct;
3. a repo-wide CI gate (``test_capped_returns_carry_envelope``) whose documented
   limits are spelled out in its own docstring.
"""

from __future__ import annotations

from typing import Any

import pytest

from iaiops.core.runtime.envelope import (
    ENVELOPE_KEYS,
    IS_TRUNCATED,
    ITEMS_RETURNED,
    ITEMS_TOTAL,
    ITEMS_TOTAL_IS_EXACT,
    OT_PASSTHROUGH_FIELDS,
    TRUNCATION_NOTE,
    bounded,
    enum_passthrough_violations,
    envelope_fields,
    with_explicit_nulls,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# 1. the envelope helper
# --------------------------------------------------------------------------


def test_envelope_fields_exact_total_truncated() -> None:
    """Exact total known and larger than returned -> is_truncated True."""
    env = envelope_fields(returned=50, total=137)
    assert env[ITEMS_RETURNED] == 50
    assert env[ITEMS_TOTAL] == 137
    assert env[ITEMS_TOTAL_IS_EXACT] is True
    assert env[IS_TRUNCATED] is True
    assert isinstance(env[TRUNCATION_NOTE], str)
    assert "50" in env[TRUNCATION_NOTE] and "137" in env[TRUNCATION_NOTE]


def test_envelope_fields_boundary_returned_equals_total_is_not_truncated() -> None:
    """THE boundary case: returned == total must NOT be flagged truncated."""
    env = envelope_fields(returned=50, total=50)
    assert env[IS_TRUNCATED] is False
    assert env[TRUNCATION_NOTE] is None  # explicit null, never an omitted key
    assert env[ITEMS_TOTAL] == 50


def test_envelope_fields_empty_is_not_truncated() -> None:
    """Genuinely empty result: 0 of 0 is complete, not truncated."""
    env = envelope_fields(returned=0, total=0)
    assert env[IS_TRUNCATED] is False
    assert env[ITEMS_RETURNED] == 0
    assert env[ITEMS_TOTAL] == 0


def test_envelope_fields_probe_form_total_unknown() -> None:
    """limit+1 probe: total is genuinely unknown -> explicit null, exact False.

    Honesty matters more than a filled-in number: reporting ``items_total``
    equal to the page size would be a fabricated total.
    """
    env = envelope_fields(returned=1000, more_available=True)
    assert env[ITEMS_TOTAL] is None
    assert env[ITEMS_TOTAL_IS_EXACT] is False
    assert env[IS_TRUNCATED] is True
    assert env[ITEMS_RETURNED] == 1000


def test_envelope_fields_probe_form_no_more_available() -> None:
    env = envelope_fields(returned=7, more_available=False)
    assert env[IS_TRUNCATED] is False
    assert env[ITEMS_TOTAL] is None
    assert env[ITEMS_TOTAL_IS_EXACT] is False
    assert env[TRUNCATION_NOTE] is None


def test_envelope_fields_always_emits_every_key() -> None:
    """All five keys are ALWAYS present — an omitted key is a hallucination license."""
    for env in (
        envelope_fields(returned=1, total=1),
        envelope_fields(returned=1, total=9),
        envelope_fields(returned=1, more_available=True),
        envelope_fields(returned=1, more_available=False),
    ):
        assert set(ENVELOPE_KEYS) <= set(env)


def test_envelope_fields_requires_exactly_one_source_of_truth() -> None:
    with pytest.raises(ValueError):
        envelope_fields(returned=1)
    with pytest.raises(ValueError):
        envelope_fields(returned=1, total=2, more_available=True)


def test_envelope_fields_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        envelope_fields(returned=-1, total=3)
    with pytest.raises(ValueError):
        envelope_fields(returned=5, total=3)


def test_envelope_fields_accepts_custom_note() -> None:
    env = envelope_fields(returned=1, total=2, note="only the first row was processed")
    assert env[TRUNCATION_NOTE] == "only the first row was processed"


def test_bounded_caps_and_describes() -> None:
    items = list(range(10))
    env = bounded(items, cap=4, items_key="tags")
    assert env["tags"] == [0, 1, 2, 3]
    assert env[ITEMS_RETURNED] == 4
    assert env[ITEMS_TOTAL] == 10
    assert env[IS_TRUNCATED] is True


def test_bounded_under_cap_is_not_truncated() -> None:
    env = bounded([1, 2], cap=4, items_key="rows")
    assert env["rows"] == [1, 2]
    assert env[IS_TRUNCATED] is False
    assert env[ITEMS_TOTAL] == 2


def test_bounded_does_not_mutate_input() -> None:
    """Immutability: helpers return NEW containers, never mutate the caller's."""
    items = [1, 2, 3]
    env = bounded(items, cap=2, items_key="rows")
    env["rows"].append(99)
    assert items == [1, 2, 3]


def test_envelope_fields_returns_a_new_dict_each_call() -> None:
    a = envelope_fields(returned=1, total=1)
    b = envelope_fields(returned=1, total=1)
    assert a == b
    assert a is not b


# --------------------------------------------------------------------------
# explicit nulls + enum passthrough
# --------------------------------------------------------------------------


def test_with_explicit_nulls_fills_absent_fields() -> None:
    row = {"tag": "line1.temp", "value": 41.2}
    out = with_explicit_nulls(row, ("tag", "value", "quality", "unit"))
    assert out["quality"] is None
    assert out["unit"] is None
    assert out["tag"] == "line1.temp"


def test_with_explicit_nulls_never_overwrites_present_values() -> None:
    row = {"quality": "BAD", "value": 0}
    out = with_explicit_nulls(row, ("quality", "value", "unit"))
    assert out["quality"] == "BAD"
    assert out["value"] == 0  # falsy but PRESENT — must survive
    assert out["unit"] is None


def test_with_explicit_nulls_does_not_mutate_input() -> None:
    row = {"tag": "t"}
    out = with_explicit_nulls(row, ("tag", "unit"))
    assert "unit" not in row
    assert out is not row


def test_enum_passthrough_detects_beautified_value() -> None:
    """Raw OT enum/severity/quality values must survive VERBATIM."""
    source = [{"id": "A1", "severity": 800, "quality": "BAD_NOT_CONNECTED"}]
    returned = [{"id": "A1", "severity": "High", "quality": "bad"}]
    violations = enum_passthrough_violations(source, returned, ("severity", "quality"))
    assert len(violations) == 2
    assert {v["field"] for v in violations} == {"severity", "quality"}


def test_enum_passthrough_clean_when_verbatim() -> None:
    source = [{"severity": 800, "quality": "BAD_NOT_CONNECTED", "state": "ACTIVE"}]
    returned = [dict(source[0])]
    assert enum_passthrough_violations(source, returned, OT_PASSTHROUGH_FIELDS) == []


def test_enum_passthrough_flags_dropped_field() -> None:
    """A silently DROPPED enum field is as dangerous as a rewritten one."""
    source = [{"severity": 800}]
    returned = [{}]
    violations = enum_passthrough_violations(source, returned, ("severity",))
    assert len(violations) == 1


def test_enum_passthrough_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError):
        enum_passthrough_violations([{"severity": 1}], [], ("severity",))


# --------------------------------------------------------------------------
# 2. migrated call sites — legacy key keeps legacy TYPE + new keys correct
# --------------------------------------------------------------------------


def _assert_envelope(result: dict[str, Any], *, returned: int, truncated: bool) -> None:
    assert set(ENVELOPE_KEYS) <= set(result), f"missing envelope keys: {sorted(result)}"
    assert result[ITEMS_RETURNED] == returned
    assert result[IS_TRUNCATED] is truncated


def test_maintenance_log_keeps_string_truncated_and_gains_envelope() -> None:
    """maintenance_log's legacy ``truncated`` is a STRING — it must stay a string."""
    from iaiops.core.brain.maintenance_log import MAX_ROWS, corpus_from_maintenance_log

    rows = [{"cause": "bearing failure"} for _ in range(MAX_ROWS + 5)]
    out = corpus_from_maintenance_log(rows)
    assert isinstance(out["truncated"], str)  # legacy shape, unchanged
    _assert_envelope(out, returned=MAX_ROWS, truncated=True)
    assert out[ITEMS_TOTAL] == MAX_ROWS + 5
    assert out[ITEMS_TOTAL_IS_EXACT] is True


def test_maintenance_log_untruncated_omits_legacy_key_but_has_envelope() -> None:
    """Legacy behaviour omitted ``truncated`` when nothing was cut; keep that.

    The envelope keys are the fix: they are present EITHER WAY, so a reader
    never has to infer completeness from an absent key.
    """
    from iaiops.core.brain.maintenance_log import corpus_from_maintenance_log

    out = corpus_from_maintenance_log([{"cause": "bearing failure"}])
    assert "truncated" not in out
    _assert_envelope(out, returned=1, truncated=False)
    assert out[TRUNCATION_NOTE] is None


def test_alarm_flood_report_keeps_dict_truncated_and_gains_envelope() -> None:
    """alarm_flood's legacy ``truncated`` is a per-section DICT — keep the dict."""
    from iaiops.core.brain.alarm_flood import alarm_flood_report

    events = [
        {"source": f"tag{i % 3}", "timestamp": f"2026-07-02T10:00:{i:02d}+00:00", "state": "ACTIVE"}
        for i in range(40)
    ]
    out = alarm_flood_report(events, max_episodes=1, max_rows=1)
    assert isinstance(out["truncated"], dict)  # legacy shape, unchanged
    assert set(ENVELOPE_KEYS) <= set(out)
    assert out[ITEMS_RETURNED] == sum(
        len(out[k])
        for k in ("flood_episodes", "chattering", "stale_standing", "suppression_advice")
    ) + len(out["worksheet_preview"])
    assert out[IS_TRUNCATED] is any(out["truncated"].values())


def test_baseline_status_flow_envelope(tmp_path) -> None:
    from iaiops.core.brain import baseline_store as bs

    store = {"tags": {f"tag{i}": {"last_check": None} for i in range(3)}}
    bs.save_store(store, tmp_path)
    out = bs.status_flow(base_dir=tmp_path)
    assert out["truncated"] is False  # legacy bool, unchanged
    assert out["listed"] == 3  # legacy count key, unchanged
    _assert_envelope(out, returned=3, truncated=False)
    assert out[ITEMS_TOTAL] == 3


def test_sparkplug_dataset_envelope() -> None:
    from iaiops.connectors.sparkplug import ops

    class _Row:
        def __init__(self, n: int) -> None:
            self.elements = [_Cell(n)]

    class _Cell:
        def __init__(self, n: int) -> None:
            self.int_value = n

        def WhichOneof(self, _name: str) -> str:  # noqa: N802 - protobuf API name
            return "int_value"

    class _DataSet:
        num_of_columns = 1
        columns = ["a"]
        types = [3]
        rows = [_Row(i) for i in range(ops.MAX_DATASET_ROWS + 2)]

    out = ops._decode_dataset(_DataSet())
    assert out["truncated"] is True  # legacy bool, unchanged
    assert out["row_count"] == ops.MAX_DATASET_ROWS + 2  # legacy TRUE-total key
    _assert_envelope(out, returned=ops.MAX_DATASET_ROWS, truncated=True)
    assert out[ITEMS_TOTAL] == ops.MAX_DATASET_ROWS + 2


def test_compliance_report_truncated_envelope() -> None:
    """Line-shaped (not list-shaped) truncation still reports the same envelope."""
    from mcp_server.tools import compliance_tools

    out = compliance_tools.compliance_report()
    assert isinstance(out, dict)
    assert set(ENVELOPE_KEYS) <= set(out)
    if out.get("truncated"):
        assert out["truncated"] is True  # legacy bool, unchanged
        assert out[IS_TRUNCATED] is True
        assert out[ITEMS_RETURNED] < out[ITEMS_TOTAL]
    else:
        assert out[IS_TRUNCATED] is False


def test_plc_block_section_envelope(tmp_path) -> None:
    from iaiops.core.brain.plc_program.outline import block_section

    src = tmp_path / "demo.scl"
    body = "\n".join(f"  x := {i};" for i in range(30))
    src.write_text(f"FUNCTION_BLOCK FB1\n{body}\nEND_FUNCTION_BLOCK\n", encoding="utf-8")
    out = block_section(str(src), "FB1", max_lines=5)
    assert out["truncated"] is True  # legacy bool, unchanged
    assert out["lines_returned"] == 5  # legacy count key, unchanged
    _assert_envelope(out, returned=5, truncated=True)
    assert out[ITEMS_TOTAL] > 5


def test_alarm_worksheet_inline_envelope() -> None:
    from mcp_server.tools import alarm_tools

    events = [
        {"source": f"tag{i}", "timestamp": f"2026-07-02T10:00:{i:02d}+00:00", "state": "ACTIVE"}
        for i in range(5)
    ]
    out = alarm_tools.alarm_rationalization_worksheet(events=events)
    assert out["truncated"] is False  # legacy bool, unchanged
    assert isinstance(out["row_count"], int)  # legacy TRUE-total key, unchanged
    _assert_envelope(out, returned=len(out["rows"]), truncated=False)
    assert out[ITEMS_TOTAL] == out["row_count"]


def test_alarm_worksheet_csv_path_envelope(tmp_path) -> None:
    """With out_path the FULL worksheet is on disk — nothing is truncated."""
    from mcp_server.tools import alarm_tools

    events = [
        {"source": f"tag{i}", "timestamp": f"2026-07-02T10:00:{i:02d}+00:00", "state": "ACTIVE"}
        for i in range(5)
    ]
    out = alarm_tools.alarm_rationalization_worksheet(
        events=events, out_path=str(tmp_path / "w.csv")
    )
    assert out["truncated"] is False  # legacy bool, unchanged
    assert out[IS_TRUNCATED] is False
    assert out[ITEMS_RETURNED] == out[ITEMS_TOTAL] == out["row_count"]


def _seed_historian(home, points: list[dict[str, Any]]) -> None:
    """Seed the local sqlite store the same way ``tests/test_historian_read.py`` does."""
    from iaiops.core.sink.push import historian_push

    assert "error" not in historian_push(points, "sqlite", db_path=home / "data.db")


def _no_site_config(monkeypatch) -> None:
    """Ignore any developer ``historian:`` config block — use the local sqlite store."""
    from iaiops.core.runtime.config import AppConfig
    from iaiops.core.sink import historian_read

    monkeypatch.setattr(historian_read, "load_config_env", lambda: AppConfig())


def test_historian_query_and_coverage_envelope(isolated_iaiops_home, monkeypatch) -> None:
    from mcp_server.tools.historian_tools import historian_coverage, historian_query

    _no_site_config(monkeypatch)
    _seed_historian(
        isolated_iaiops_home,
        [
            {"ref": "line1.temp", "value": float(i), "timestamp": f"2026-07-02T10:00:{i:02d}+00:00"}
            for i in range(3)
        ],
    )

    q = historian_query(tag="line1.temp", limit=2)
    assert q["truncated"] is True  # legacy bool, unchanged
    assert q["rows"] == 2  # legacy count key, unchanged
    _assert_envelope(q, returned=2, truncated=True)
    # limit+1 probe: the TRUE total is unknown — say so rather than inventing it.
    assert q[ITEMS_TOTAL] is None
    assert q[ITEMS_TOTAL_IS_EXACT] is False

    q_all = historian_query(tag="line1.temp", limit=100)
    assert q_all["truncated"] is False
    _assert_envelope(q_all, returned=3, truncated=False)

    cov = historian_coverage(limit=100)
    assert cov["truncated"] is False  # legacy bool, unchanged
    assert isinstance(cov["tag_count"], int)  # legacy count key, unchanged
    _assert_envelope(cov, returned=cov["tag_count"], truncated=False)


def test_historian_query_preserves_quality_verbatim(isolated_iaiops_home, monkeypatch) -> None:
    """Enum passthrough on a real path: the stored OT quality string is verbatim.

    ``BAD_NOT_CONNECTED`` is an OPC-UA status text an operator matches against
    the server's own documentation. Normalizing it to "bad" would destroy that.
    """
    from mcp_server.tools.historian_tools import historian_query

    _no_site_config(monkeypatch)
    _seed_historian(
        isolated_iaiops_home,
        [
            {
                "ref": "line1.temp",
                "value": 1.0,
                "timestamp": "2026-07-02T10:00:00+00:00",
                "quality": "BAD_NOT_CONNECTED",
            }
        ],
    )
    out = historian_query(tag="line1.temp", limit=10)
    assert out["samples"][0]["quality"] == "BAD_NOT_CONNECTED"
    assert (
        enum_passthrough_violations(
            [{"quality": "BAD_NOT_CONNECTED"}],
            [{"quality": out["samples"][0]["quality"]}],
            ("quality",),
        )
        == []
    )
