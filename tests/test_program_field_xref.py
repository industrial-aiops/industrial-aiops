"""Program ↔ configured field point cross-reference (roadmap item A).

The guarantee under test is the one that makes this worth showing to a field
engineer: a program symbol is joined to a configured point **only when both name
the same address in the same address space**. A shared name, a similar name or a
label that reads like the symbol is never a match (HLD D16 — semantics are given
by a person, a guessed mapping is the defect this product refuses).

Every case runs the real parsers over real-shaped exports (the samples from
``test_plc_program`` plus a Step 7 AWL network and a TIA SCL block with absolute
operands).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from test_plc_program import AWL_SAMPLE, L5X_SAMPLE, SCL_SAMPLE
from typer.testing import CliRunner

from iaiops.core.brain.plc_program import field_xref as fx
from iaiops.core.brain.plc_program.addresses import parse_s7_config_ref, parse_s7_program_address
from iaiops.core.runtime.config import MonitorTag

# A Step 7 Classic AWL export: absolute operands, a symbol, a timer, an
# indirect access the extractor must not pretend to resolve.
AWL_LINE = """\
ORGANIZATION_BLOCK OB 1
TITLE = Line 3 main cycle
NETWORK
TITLE = Conveyor run seal-in
      A     I      0.0      // start button
      O     M     10.0
      AN    I      0.1      // stop button
      =     M     10.0
      =     Q      4.0      // conveyor contactor
NETWORK
TITLE = Counters to DB
      L     DB10.DBW    4
      T     MW    20
      L     DB10.DBD    8
      A     "Motor_Start"
      SP    T      5
      L     DB10.DBW [AR1,P#0.0]
END_ORGANIZATION_BLOCK
"""

# TIA SCL with absolute operands mixed with symbolic ones.
SCL_ABS = """\
FUNCTION_BLOCK "FB_Line"
VAR
    Count : INT;
END_VAR
BEGIN
    IF %I0.0 AND NOT %I0.1 THEN
        %Q4.0 := TRUE;
    END_IF;
    Count := %MW20;
    %DB10.DBW4 := Count;
    "Line_DB".Speed := 1.0;
END_FUNCTION_BLOCK
"""


def _write(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _target(protocol: str, tags: list[dict], *, plctype: str = "Q", name: str = "plc1"):
    return SimpleNamespace(
        name=name,
        protocol=protocol,
        plctype=plctype,
        tags=tuple(MonitorTag(**t) for t in tags),
    )


def _refs(rows: list[dict], key: str = "configured_ref") -> set[str]:
    return {r[key] for r in rows}


# ─── address canonicalisation ────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "ref",
    [
        "DB10,X0.1",
        "DB10,I4",
        "DB10,INT4",
        "DB10,W4",
        "DB10,R8",
        "DB10,REAL8",
        "DB10,DI8",
        "DB10,LR8",
        "DB36,B2",
        "M10.0",
        "MW20",
        "MI20",
        "MD20",
        "MR84",
        "I0.0",
        "E0.0",
        "Q4.0",
        "A4.0",
        "IB3",
        "QW8",
        "AW8",
    ],
)
def test_config_ref_canonical_form_agrees_with_pys7(ref):
    """Our reading of a configured S7 ref is pyS7's own reading of it.

    The connector hands these strings to pyS7, so a canonical form that disagreed
    with pyS7 would join a program operand to a point the connector reads
    somewhere else.
    """
    from pyS7.address_parser import map_address_to_tag
    from pyS7.constants import DataType, MemoryArea

    size = {
        DataType.BIT: 0,
        DataType.BYTE: 1,
        DataType.CHAR: 1,
        DataType.INT: 2,
        DataType.WORD: 2,
        DataType.DINT: 4,
        DataType.DWORD: 4,
        DataType.REAL: 4,
        DataType.LREAL: 8,
    }
    area = {
        MemoryArea.DB: "DB",
        MemoryArea.INPUT: "I",
        MemoryArea.OUTPUT: "Q",
        MemoryArea.MERKER: "M",
    }
    tag = map_address_to_tag(ref)
    ours = parse_s7_config_ref(ref)
    assert ours is not None
    assert (ours.area, ours.db, ours.byte, ours.size) == (
        area[tag.memory_area],
        tag.db_number,
        tag.start,
        size[tag.data_type],
    )
    if ours.size == 0:
        assert ours.bit == tag.bit_offset


@pytest.mark.unit
def test_program_operands_and_config_refs_meet_in_one_form():
    assert parse_s7_program_address("DB10.DBW4") == parse_s7_config_ref("DB10,I4")
    assert parse_s7_program_address("DB10.DBX0.1") == parse_s7_config_ref("DB10,X0.1")
    assert parse_s7_program_address("M10.0") == parse_s7_config_ref("M10.0")
    assert parse_s7_program_address("E0.0") == parse_s7_config_ref("I0.0")
    assert parse_s7_program_address("A4.0") == parse_s7_config_ref("Q4.0")
    assert parse_s7_program_address("%MW20") == parse_s7_config_ref("MW20")
    # Different memory, never the same address.
    assert parse_s7_program_address("PIW256") != parse_s7_config_ref("IW256")
    assert parse_s7_program_address("DB10.DBW4") != parse_s7_config_ref("DB11,I4")
    # A string has no fixed width — not comparable, not guessed.
    assert parse_s7_config_ref("DB102,S10.15") is None
    assert parse_s7_program_address("DB10") is None  # a block, not a data address


# ─── AWL × S7 ────────────────────────────────────────────────────────────────


@pytest.fixture()
def awl_result(tmp_path):
    path = _write(tmp_path, "ob1.awl", AWL_LINE)
    target = _target(
        "s7",
        [
            {"ref": "M10.0", "label": "running", "role": "run_state", "running_when": (True,)},
            {"ref": "DB10,I4", "label": "good parts", "role": "good_count"},
            {"ref": "DB10,X0.1", "label": "spare"},
            {"ref": "MD20", "label": "wide read of MW20"},
            # A label that IS the program's symbol name, on a different address.
            {"ref": "M99.0", "label": "Motor_Start"},
            {"ref": "DB102,S10.15", "label": "batch id"},
        ],
    )
    return fx.xref_program_endpoint(path, target)


@pytest.mark.unit
def test_awl_s7_matches_on_exact_address(awl_result):
    r = awl_result
    assert r["comparable"] is True
    assert r["address_space"] == "s7_absolute"
    matched = {m["address"]: m for m in r["matched"]}
    assert set(matched) == {"M10.0", "DB10.DBW4"}
    run = matched["M10.0"]
    assert run["configured_ref"] == "M10.0"
    assert run["role"] == "run_state"
    assert run["label"] == "running"
    assert run["match"] == "exact_address"
    # Cited sites from the real export, with access from the AWL op.
    accesses = {(s["line"], s["access"]) for s in run["sites"]}
    assert (6, "read") in accesses and (8, "write") in accesses
    assert matched["DB10.DBW4"]["role"] == "good_count"


@pytest.mark.unit
def test_awl_s7_lists_both_sides_of_the_gap(awl_result):
    r = awl_result
    in_prog = {row["address"] for row in r["in_export_not_configured"]}
    assert {"I0.0", "I0.1", "Q4.0", "MW20", "DB10.DBD8", "T5"} <= in_prog
    assert "M10.0" not in in_prog
    timer = next(row for row in r["in_export_not_configured"] if row["address"] == "T5")
    assert "cannot" in timer["note"]  # the S7 connector reads no timers
    assert _refs(r["configured_not_in_export"]) == {"DB10,X0.1", "MD20", "M99.0"}
    # A string ref is not comparable — not "unused by the program".
    assert _refs(r["configured_not_comparable"]) == {"DB102,S10.15"}


@pytest.mark.unit
def test_overlap_of_different_width_is_reported_not_matched(awl_result):
    r = awl_result
    assert "MD20" not in {m["configured_ref"] for m in r["matched"]}
    overlap = [o for o in r["overlaps"] if o["configured_ref"] == "MD20"]
    assert overlap and overlap[0]["program_address"] == "MW20"


@pytest.mark.unit
def test_a_label_equal_to_a_symbol_is_never_a_match(awl_result):
    """The mutation-check anchor: name-only agreement must not produce a match."""
    r = awl_result
    assert all(m["configured_ref"] != "M99.0" for m in r["matched"])
    assert all(m["label"] != "Motor_Start" for m in r["matched"])
    symbolic = {s["symbol"] for s in r["symbolic_only"]}
    assert "Motor_Start" in symbolic
    assert any("tag table" in n or "symbol table" in n for n in r["notes"])


@pytest.mark.unit
def test_indirect_access_is_admitted_not_resolved(awl_result):
    assert any("indirect" in n for n in awl_result["notes"])
    assert awl_result["indirect_access_sites"]


@pytest.mark.unit
def test_original_awl_sample_spaced_operands(tmp_path):
    path = _write(tmp_path, "fb10.awl", AWL_SAMPLE)
    target = _target("s7", [{"ref": "M10.0"}, {"ref": "DB10,W4"}, {"ref": "Q0.0"}])
    r = fx.xref_program_endpoint(path, target)
    assert {m["address"] for m in r["matched"]} == {"M10.0", "DB10.DBW4", "Q0.0"}


# ─── SCL × S7 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_scl_absolute_operands_match_and_symbolic_ones_do_not(tmp_path):
    path = _write(tmp_path, "fb_line.scl", SCL_ABS)
    target = _target(
        "s7",
        [{"ref": "MW20"}, {"ref": "Q4.0"}, {"ref": "DB10,I4"}, {"ref": "M0.0", "label": "Speed"}],
    )
    r = fx.xref_program_endpoint(path, target)
    assert r["comparable"] is True
    matched = {m["address"]: m for m in r["matched"]}
    assert set(matched) == {"MW20", "Q4.0", "DB10.DBW4"}
    assert any(s["access"] == "write" for s in matched["Q4.0"]["sites"])
    assert any(s["access"] == "read" for s in matched["MW20"]["sites"])
    assert _refs(r["configured_not_in_export"]) == {"M0.0"}


@pytest.mark.unit
def test_symbolic_only_scl_matches_nothing_and_says_why(tmp_path):
    path = _write(tmp_path, "conveyor.scl", SCL_SAMPLE)
    target = _target("s7", [{"ref": "M0.0", "label": "Running"}])
    r = fx.xref_program_endpoint(path, target)
    assert r["matched"] == []
    assert any("tag table" in n for n in r["notes"])


@pytest.mark.unit
def test_generic_st_is_not_read_as_siemens(tmp_path):
    """CODESYS %MW10 is word 10; S7 MW10 is byte 10. A .st file is not assumed S7."""
    path = _write(tmp_path, "line.st", SCL_ABS)
    r = fx.xref_program_endpoint(path, _target("s7", [{"ref": "MW20"}]))
    assert r["comparable"] is False
    assert r["matched"] is None
    assert "CODESYS" in r["unmatchable"]["reason"]


# ─── L5X × EtherNet/IP (Logix) ───────────────────────────────────────────────


@pytest.fixture()
def l5x_result(tmp_path):
    path = _write(tmp_path, "line3.L5X", L5X_SAMPLE)
    target = _target(
        "ethernetip",
        [
            {"ref": "Motor_Run", "role": "run_state", "running_when": (1,)},
            {"ref": "Program:MainProgram.RunTmr.ACC", "label": "run time"},
            {"ref": "MotorRun", "label": "near miss"},
            {"ref": "Line_Speed", "label": "Conv_Speed"},
        ],
    )
    return fx.xref_program_endpoint(path, target)


@pytest.mark.unit
def test_l5x_logix_matches_on_tag_path(l5x_result):
    r = l5x_result
    assert r["comparable"] is True
    assert r["address_space"] == "logix_symbolic"
    matched = {m["configured_ref"]: m for m in r["matched"]}
    assert set(matched) == {"Motor_Run", "Program:MainProgram.RunTmr.ACC"}
    assert matched["Motor_Run"]["match"] == "exact_address"
    assert matched["Motor_Run"]["role"] == "run_state"
    assert any(s["access"] == "write" and s["line"] == 0 for s in matched["Motor_Run"]["sites"])
    member = matched["Program:MainProgram.RunTmr.ACC"]
    assert member["match"] == "member_of_tag"
    assert member["address"] == "Program:MainProgram.RunTmr"


@pytest.mark.unit
def test_l5x_similar_names_and_labels_are_not_matches(l5x_result):
    r = l5x_result
    assert _refs(r["configured_not_in_export"]) == {"MotorRun", "Line_Speed"}
    assert {row["address"] for row in r["in_export_not_configured"]} == {"Conv_Speed"}


@pytest.mark.unit
def test_l5x_controller_tag_path_does_not_match_a_program_tag(tmp_path):
    """`RunTmr` (controller scope) and `Program:MainProgram.RunTmr` are different tags."""
    path = _write(tmp_path, "line3.L5X", L5X_SAMPLE)
    r = fx.xref_program_endpoint(path, _target("ethernetip", [{"ref": "RunTmr"}]))
    assert r["matched"] == []


# ─── no shared address space ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "text", "protocol", "plctype", "needle"),
    [
        ("ob1.awl", AWL_LINE, "modbus", "Q", "Modbus"),
        ("ob1.awl", AWL_LINE, "opcua", "Q", "OPC UA"),
        ("ob1.awl", AWL_LINE, "ethernetip", "Q", "address space"),
        ("line3.L5X", L5X_SAMPLE, "s7", "Q", "address space"),
        ("line3.L5X", L5X_SAMPLE, "ethernetip", "slc", "PCCC"),
        ("line3.L5X", L5X_SAMPLE, "ethernetip", "micro800", "Micro800"),
        ("line3.L5X", L5X_SAMPLE, "mc", "Q", "no parser"),
    ],
)
def test_unmatchable_pairs_report_a_reason_and_no_lists(
    tmp_path, name, text, protocol, plctype, needle
):
    path = _write(tmp_path, name, text)
    target = _target(protocol, [{"ref": "40001" if protocol == "modbus" else "X"}], plctype=plctype)
    r = fx.xref_program_endpoint(path, target)
    assert r["comparable"] is False
    assert needle in r["unmatchable"]["reason"]
    # Absent, not empty: "nothing configured is used by the program" would be a
    # finding, and it is not one we can make.
    for key in ("matched", "in_export_not_configured", "configured_not_in_export"):
        assert r[key] is None


@pytest.mark.unit
def test_unmatchable_table_names_every_dialect_protocol_pair():
    table = fx.comparability_table()
    formats = {row["program_format"] for row in table}
    assert formats == {"awl", "scl", "st", "l5x"}
    assert any(row["comparable"] for row in table)
    assert all(row["reason"] for row in table if not row["comparable"])


# ─── live values ─────────────────────────────────────────────────────────────


class _RefusedError(Exception):
    pass


@pytest.mark.unit
def test_live_values_only_when_asked(awl_result):
    assert "live" not in awl_result


@pytest.mark.unit
def test_live_read_marks_freshness_and_gaps(awl_result):
    from iaiops.core.brain.plc_program import field_live

    def reader(target, ref):
        if ref == "M10.0":
            return True
        raise _RefusedError("PUT/GET refused by CPU")

    live = field_live.read_matched(SimpleNamespace(name="plc1"), awl_result, read=reader)
    by_ref = {row["configured_ref"]: row for row in live["points"]}
    good = by_ref["M10.0"]
    assert good["status"] == "read" and good["value"] is True
    assert good["read_at"] and good["freshness"] == "read_now"
    assert good["device_timestamp"] is None
    gap = by_ref["DB10,I4"]
    assert gap["status"] == "gap"
    assert "value" not in gap  # a failed read is a gap, never a value
    assert "PUT/GET" in gap["error"]
    assert live["read_count"] == 1 and live["gap_count"] == 1


@pytest.mark.unit
def test_live_read_none_is_a_gap(awl_result):
    from iaiops.core.brain.plc_program import field_live

    live = field_live.read_matched(
        SimpleNamespace(name="plc1"), awl_result, read=lambda target, ref: None
    )
    assert all(row["status"] == "gap" and "value" not in row for row in live["points"])


@pytest.mark.unit
def test_live_refuses_when_not_comparable(tmp_path):
    from iaiops.core.brain.plc_program import field_live

    path = _write(tmp_path, "ob1.awl", AWL_LINE)
    r = fx.xref_program_endpoint(path, _target("modbus", [{"ref": "40001"}]))
    live = field_live.read_matched(SimpleNamespace(name="plc1"), r, read=lambda t, ref: 1)
    assert live["points"] == [] and "not comparable" in live["note"]


@pytest.mark.unit
def test_eip_reader_turns_a_bad_tag_into_a_gap(monkeypatch):
    from iaiops.connectors.eip import ops as eip_ops
    from iaiops.core.brain.plc_program import field_live

    monkeypatch.setattr(
        eip_ops,
        "eip_read_tag",
        lambda target, ref: {"value": None, "good": False, "error": "Path destination unknown"},
    )
    with pytest.raises(ValueError, match="Path destination unknown"):
        field_live.default_read(SimpleNamespace(protocol="ethernetip"), "Motor_Run")


# ─── MCP + CLI ───────────────────────────────────────────────────────────────


@pytest.fixture()
def configured(tmp_path, monkeypatch):
    import mcp_server._shared as shared

    config = {
        "targets": [
            {
                "name": "line3",
                "protocol": "s7",
                "host": "127.0.0.1",
                "tags": [
                    {"ref": "M10.0", "label": "running"},
                    {"ref": "DB10,X0.1", "label": "spare"},
                ],
            }
        ]
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path / "iaiops-home"))
    monkeypatch.setenv("IAIOPS_AGENT_READ_DIRS", str(tmp_path / "exports"))
    (tmp_path / "cfg").mkdir()
    cfg = tmp_path / "cfg" / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("IAIOPS_CONFIG", str(cfg))
    monkeypatch.setattr(shared, "_conn_mgr", None)
    (tmp_path / "exports").mkdir()
    return tmp_path


@pytest.mark.unit
def test_mcp_tool_is_governed_low_and_confined(configured):
    from mcp_server.tools.plc_program_tools import plc_program_xref_config

    assert plc_program_xref_config._is_governed_tool
    assert plc_program_xref_config._risk_level == "low"
    inside = _write(configured / "exports", "ob1.awl", AWL_LINE)
    result = plc_program_xref_config(path=inside, endpoint="line3")
    assert [m["address"] for m in result["matched"]] == ["M10.0"]
    outside = _write(configured, "ob1.awl", AWL_LINE)
    refused = plc_program_xref_config(path=outside, endpoint="line3")
    assert "error" in refused


@pytest.mark.unit
def test_cli_xref_config_and_live(configured, monkeypatch):
    from iaiops.cli._root import app
    from iaiops.core.brain.plc_program import field_live

    path = _write(configured, "ob1.awl", AWL_LINE)
    runner = CliRunner()
    result = runner.invoke(app, ["program", "xref-config", path, "--endpoint", "line3"])
    assert result.exit_code == 0, result.output
    assert '"matched"' in result.output and '"live"' not in result.output

    monkeypatch.setattr(field_live, "default_read", lambda target, ref: True)
    result = runner.invoke(app, ["program", "xref-config", path, "--endpoint", "line3", "--live"])
    assert result.exit_code == 0, result.output
    assert '"read_now"' in result.output


# ─── adversarial-review regressions: text that is not an operand ─────────────


def _s7_matched(tmp_path, name, text, refs):
    path = _write(tmp_path, name, text)
    r = fx.xref_program_endpoint(path, _target("s7", [{"ref": ref} for ref in refs]))
    return r, {m["configured_ref"] for m in r["matched"]}


@pytest.mark.unit
def test_scl_strings_and_block_comments_are_not_operands(tmp_path):
    text = """\
FUNCTION_BLOCK "FB_Msg"
BEGIN
    #msg := 'check %MW20 and %Q0.0';
    /* old: %M1.0 := TRUE */
    #a := "Tag_%MW4".x;
    (* %M2.0 *)
    #b := %MW30; // %MW40
END_FUNCTION_BLOCK
"""
    r, matched = _s7_matched(
        tmp_path, "msg.scl", text, ["MW20", "Q0.0", "M1.0", "MW4", "M2.0", "MW30", "MW40"]
    )
    assert matched == {"MW30"}
    assert "Tag_%MW4" in {s["symbol"] for s in r["symbolic_only"]}


@pytest.mark.unit
def test_scl_output_parameter_is_a_write(tmp_path):
    text = 'FUNCTION_BLOCK "FB"\nBEGIN\n    #Inst(IN := TRUE, OUT => %MW6);\nEND_FUNCTION_BLOCK\n'
    r, matched = _s7_matched(tmp_path, "out.scl", text, ["MW6"])
    assert matched == {"MW6"}
    assert r["matched"][0]["sites"][0]["access"] == "write"


@pytest.mark.unit
def test_awl_quoted_strings_pointers_and_locals_are_not_operands(tmp_path):
    text = """\
FUNCTION_BLOCK FB 5
VAR
  IW1 : INT ;
  T1 : TIME ;
END_VAR
BEGIN
NETWORK
TITLE =
      A     "Sensor I 0.1"
      =     "Lamp Q 4.0"
      L     'M 1.0'
      L     P#M 10.0
      L     #IW1
      CALL SFC 20 (SRCBLK := P#DB10.DBX 0.0 BYTE 10, RET_VAL := MW 50)
      a     i 0.7
END_FUNCTION_BLOCK
"""
    r, matched = _s7_matched(
        tmp_path,
        "fb5.awl",
        text,
        ["I0.1", "Q4.0", "M1.0", "M10.0", "IW1", "DB10,X0.0", "I0.7", "MW50"],
    )
    assert matched == {"I0.7", "MW50"}  # lowercase AWL is still AWL
    assert "T1" not in {row["address"] for row in r["in_export_not_configured"]}
    pointer_lines = {s["line"] for s in r["indirect_access_sites"]}
    assert {12, 14} <= pointer_lines  # P# takes an address; it is listed, not matched


@pytest.mark.unit
def test_awl_db_relative_access_is_indirect_not_absent(tmp_path):
    text = (
        "FUNCTION FC 1 : VOID\nBEGIN\nNETWORK\n      OPN   DB 10\n      L     DBW 4\nEND_FUNCTION\n"
    )
    r, matched = _s7_matched(tmp_path, "fc1.awl", text, ["DB10,W4"])
    assert matched == set()
    assert any(s["line"] == 5 for s in r["indirect_access_sites"])


@pytest.mark.unit
def test_bits_of_one_byte_do_not_overlap(tmp_path):
    r, _ = _s7_matched(tmp_path, "ob1.awl", AWL_LINE, ["M10.1"])
    assert r["overlaps"] == []


@pytest.mark.unit
def test_a_matched_point_still_reports_a_wider_writer(tmp_path):
    text = (
        "ORGANIZATION_BLOCK OB 1\nNETWORK\n"
        "      L     MW 20\n      T     MD 20\nEND_ORGANIZATION_BLOCK\n"
    )
    r, matched = _s7_matched(tmp_path, "ob1.awl", text, ["MW20"])
    assert matched == {"MW20"}
    assert any(o["program_address"] == "MD20" for o in r["overlaps"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "ref", [" M10.0", "M10", "DB1,X0.8", "DB1,X0", "MW10.1", "DB1,S10", "X10.0"]
)
def test_refs_pys7_refuses_are_not_comparable(ref):
    from pyS7.address_parser import map_address_to_tag

    try:
        map_address_to_tag(ref)
        accepted = True
    except Exception:
        accepted = False
    if not accepted:
        assert parse_s7_config_ref(ref) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        L5X_SAMPLE[: len(L5X_SAMPLE) // 2],
        L5X_SAMPLE.replace("<?xml", '<!DOCTYPE x [<!ENTITY a "b">]><?xml', 1),
        "",
    ],
)
def test_unreadable_l5x_is_refused_not_answered(tmp_path, text):
    path = _write(tmp_path, "bad.L5X", text)
    r = fx.xref_program_endpoint(path, _target("ethernetip", [{"ref": "Motor_Run"}]))
    assert r["refused"]
    assert r["matched"] is None and r["configured_not_in_export"] is None


@pytest.mark.unit
def test_empty_awl_is_refused(tmp_path):
    path = _write(tmp_path, "empty.awl", "   \n")
    r = fx.xref_program_endpoint(path, _target("s7", [{"ref": "M10.0"}]))
    assert r["refused"] and r["configured_not_in_export"] is None


ARRAY_L5X = L5X_SAMPLE.replace(
    '<Tag Name="Conv_Speed" DataType="REAL"/>',
    '<Tag Name="Conv_Speed" DataType="REAL"/><Tag Name="Tank" DataType="DINT" Dimensions="10"/>',
).replace(
    "<Text>XIC(Start)OTE(Motor_Run);</Text>",
    "<Text>XIC(Start)OTE(Motor_Run)OTE(Tank[2]);</Text>",
)


@pytest.mark.unit
def test_logix_element_write_and_scope_of_sites(tmp_path):
    path = _write(tmp_path, "line3.L5X", ARRAY_L5X)
    r = fx.xref_program_endpoint(
        path, _target("ethernetip", [{"ref": "Tank[2]"}, {"ref": "Tank{3}"}])
    )
    row = next(m for m in r["matched"] if m["configured_ref"] == "Tank[2]")
    assert row["match"] == "member_of_tag" and row["sites_scope"] == "whole_tag"
    assert any(s["access"] == "write" for s in row["sites"])  # OTE(Tank[2]) writes Tank
    assert {m["configured_ref"] for m in r["matched"]} == {"Tank[2]", "Tank{3}"}
    assert r["program"]["controller"] == {"name": "Line3", "processor_type": ""}


@pytest.mark.unit
def test_wellformed_l5x_without_tags_is_refused(tmp_path):
    text = (
        '<?xml version="1.0"?><RSLogix5000Content><Controller Name="C"><Programs>'
        '<Program Name="P"><Routines><Routine Name="R" Type="RLL"><RLLContent>'
        '<Rung Number="0"><Text>XIC(Start)OTE(Run);</Text></Rung>'
        "</RLLContent></Routine></Routines></Program></Programs></Controller>"
        "</RSLogix5000Content>"
    )
    path = _write(tmp_path, "notags.L5X", text)
    r = fx.xref_program_endpoint(path, _target("ethernetip", [{"ref": "Run"}]))
    assert r["refused"] and r["configured_not_in_export"] is None
