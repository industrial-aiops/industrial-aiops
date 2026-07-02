"""Legacy PLC program explainer (A8) — parsers, xref, tools, CLI, hardening.

Covers: SCL/AWL/L5X outline correctness incl. line numbers, call-graph edges,
xref hits with quoted lines, malformed-file graceful degradation, XXE/entity
rejection for L5X, path-validation rejections, and the 3 MCP tools being
governed + bounded.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from iaiops.core.brain import plc_program as ops
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.plc_program_tools import (
    MAX_BLOCKS,
    MAX_VARS_PER_BLOCK,
    plc_program_outline,
    plc_program_section,
    plc_program_xref,
)

SCL_SAMPLE = """\
// Conveyor control exported from TIA Portal
FUNCTION_BLOCK "FB_Conveyor"
VAR_INPUT
    Start : BOOL;   // start command
    Stop  : BOOL;   // stop command
    Speed : REAL := 0.0;  // setpoint m/s
END_VAR
VAR_OUTPUT
    Running : BOOL;
END_VAR
VAR
    RunTimer : TON;  // debounce timer
    Drive : "FB_Drive";
END_VAR
BEGIN
    IF Start AND NOT Stop THEN
        Running := TRUE;
    ELSIF Stop THEN
        Running := FALSE;
    END_IF;
    RunTimer(IN := Running, PT := T#2s);
    Drive(Enable := RunTimer.Q, Setpoint := Speed);
END_FUNCTION_BLOCK

FUNCTION "FC_Scale" : REAL
VAR_INPUT
    Raw : INT;
END_VAR
BEGIN
    CASE Raw OF
        0: FC_Scale := 0.0;
    END_CASE;
END_FUNCTION
"""

AWL_SAMPLE = """\
FUNCTION_BLOCK FB10
NETWORK
TITLE = Motor interlock
      A "Motor_Start"
      AN M 10.0
      = Q 0.0
NETWORK
TITLE = Setpoint transfer
      L DB10.DBW 4
      T MW 20
      CALL "PumpCtl"
      SP T 5
END_FUNCTION_BLOCK
"""

L5X_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<RSLogix5000Content SchemaRevision="1.0" TargetName="Line3">
  <Controller Name="Line3">
    <Tags>
      <Tag Name="Motor_Run" DataType="BOOL"><Description>Main motor run</Description></Tag>
      <Tag Name="Conv_Speed" DataType="REAL"/>
    </Tags>
    <Programs>
      <Program Name="MainProgram">
        <Tags>
          <Tag Name="RunTmr" DataType="TIMER"/>
        </Tags>
        <Routines>
          <Routine Name="MainRoutine" Type="RLL">
            <RLLContent>
              <Rung Number="0" Type="N">
                <Comment>Start/stop seal-in</Comment>
                <Text>XIC(Start)OTE(Motor_Run);</Text>
              </Rung>
              <Rung Number="1" Type="N">
                <Text>XIC(Motor_Run)TON(RunTmr,?,?)JSR(SpeedCalc,0);</Text>
              </Rung>
            </RLLContent>
          </Routine>
          <Routine Name="SpeedCalc" Type="ST">
            <STContent>
              <Line Number="0">Conv_Speed := 2.0;</Line>
            </STContent>
          </Routine>
        </Routines>
      </Program>
    </Programs>
    <AddOnInstructionDefinitions>
      <AddOnInstructionDefinition Name="ScaleAOI">
        <Parameters>
          <Parameter Name="Raw" DataType="INT"/>
        </Parameters>
      </AddOnInstructionDefinition>
    </AddOnInstructionDefinitions>
  </Controller>
</RSLogix5000Content>
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path / "iaiops-home"))
    return tmp_path


def _write(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ─── SCL / ST ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_scl_outline_blocks_vars_and_lines(tmp_path):
    outline = ops.outline_program(_write(tmp_path, "conveyor.scl", SCL_SAMPLE))
    assert outline.fmt == "scl"
    assert outline.parse_errors == ()
    assert [b.name for b in outline.blocks] == ["FB_Conveyor", "FC_Scale"]
    fb = outline.blocks[0]
    assert fb.kind == "FUNCTION_BLOCK"
    assert (fb.line, fb.end_line) == (2, 23)  # header .. END_FUNCTION_BLOCK
    start = next(v for v in fb.variables if v.name == "Start")
    assert start.section == "VAR_INPUT"
    assert start.var_type == "BOOL"
    assert start.comment == "start command"
    assert start.line == 4
    running = next(v for v in fb.variables if v.name == "Running")
    assert running.section == "VAR_OUTPUT"
    assert fb.source_file.endswith("conveyor.scl")


@pytest.mark.unit
def test_scl_call_graph_resolves_fb_instances(tmp_path):
    outline = ops.outline_program(_write(tmp_path, "conveyor.scl", SCL_SAMPLE))
    edges = {(e.caller, e.callee, e.line) for e in outline.call_edges}
    assert ("FB_Conveyor", "FB_Drive", 22) in edges  # Drive → declared type
    assert ("FB_Conveyor", "TON", 21) in edges  # RunTimer → TON
    timers = outline.blocks[0].timers_counters
    assert any(t.name == "RunTimer" and t.kind == "TON" and t.line == 12
               for t in timers)


@pytest.mark.unit
def test_scl_branch_inventory(tmp_path):
    outline = ops.outline_program(_write(tmp_path, "conveyor.scl", SCL_SAMPLE))
    fb_kinds = [(b.kind, b.line) for b in outline.blocks[0].branches]
    assert ("IF", 16) in fb_kinds and ("ELSIF", 18) in fb_kinds
    assert any(b.kind == "CASE" for b in outline.blocks[1].branches)


@pytest.mark.unit
def test_scl_truncated_file_degrades_gracefully(tmp_path):
    truncated = SCL_SAMPLE.split("END_FUNCTION_BLOCK")[0]
    outline = ops.outline_program(_write(tmp_path, "cut.scl", truncated))
    assert outline.blocks and outline.blocks[0].name == "FB_Conveyor"
    assert any("END_FUNCTION_BLOCK" in e for e in outline.parse_errors)


@pytest.mark.unit
def test_scl_xref_read_write_call_declare(tmp_path):
    path = _write(tmp_path, "conveyor.scl", SCL_SAMPLE)
    hits = ops.find_symbol(path, "Running")
    by_line = {h.line: h for h in hits}
    assert by_line[9].access == "declare"
    assert by_line[17].access == "write"
    assert by_line[21].access == "read"
    assert "Running := TRUE;" in by_line[17].source_line
    assert all(h.block == "FB_Conveyor" for h in hits)
    calls = ops.find_symbol(path, "Drive")
    assert any(h.access == "call" and h.line == 22 for h in calls)


# ─── AWL / STL ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_awl_outline_networks_calls_timers(tmp_path):
    outline = ops.outline_program(_write(tmp_path, "fb10.awl", AWL_SAMPLE))
    assert outline.fmt == "awl"
    assert outline.parse_errors == ()
    (fb,) = outline.blocks
    assert (fb.name, fb.kind, fb.line, fb.end_line) == ("FB10", "FUNCTION_BLOCK", 1, 13)
    assert fb.networks == ((2, "Motor interlock"), (7, "Setpoint transfer"))
    assert [(e.callee, e.line) for e in fb.calls] == [("PumpCtl", 11)]
    assert [(t.name, t.kind) for t in fb.timers_counters] == [("T5", "SP")]


@pytest.mark.unit
def test_awl_xref_addresses_and_symbols(tmp_path):
    path = _write(tmp_path, "fb10.awl", AWL_SAMPLE)
    m = ops.find_symbol(path, "M10.0")
    assert [(h.line, h.access) for h in m] == [(5, "read")]
    assert m[0].source_line == "AN M 10.0"
    q = ops.find_symbol(path, "Q0.0")
    assert [(h.line, h.access) for h in q] == [(6, "write")]
    mw = ops.find_symbol(path, "MW20")
    assert [(h.line, h.access) for h in mw] == [(10, "write")]
    db = ops.find_symbol(path, "DB10.DBW4")
    assert [(h.line, h.access) for h in db] == [(9, "read")]
    sym = ops.find_symbol(path, "PumpCtl")
    assert [(h.line, h.access) for h in sym] == [(11, "call")]
    assert all(h.block == "FB10" for h in sym)


# ─── L5X ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_l5x_outline_tags_routines_rungs(tmp_path):
    outline = ops.outline_program(_write(tmp_path, "line3.L5X", L5X_SAMPLE))
    assert outline.fmt == "l5x"
    assert outline.parse_errors == ()
    by_name = {b.name: b for b in outline.blocks}
    ctrl = by_name["Line3"]
    motor = next(v for v in ctrl.variables if v.name == "Motor_Run")
    assert motor.var_type == "BOOL" and motor.comment == "Main motor run"
    assert "ScaleAOI" in by_name and by_name["ScaleAOI"].kind == "AOI"
    prog = by_name["MainProgram"]
    assert [v.name for v in prog.variables] == ["RunTmr"]
    main = by_name["MainProgram.MainRoutine"]
    assert (main.kind, main.language, main.line, main.end_line) == (
        "ROUTINE", "rll", 0, 1)
    assert [(e.callee, e.line) for e in main.calls] == [("SpeedCalc", 1)]
    assert [(t.name, t.kind, t.line) for t in main.timers_counters] == [
        ("RunTmr", "TON", 1)]
    assert by_name["MainProgram.SpeedCalc"].language == "st"


@pytest.mark.unit
def test_l5x_xref_rung_numbers_and_write_detection(tmp_path):
    path = _write(tmp_path, "line3.L5X", L5X_SAMPLE)
    hits = ops.find_symbol(path, "Motor_Run")
    assert [(h.line, h.access) for h in hits] == [(0, "write"), (1, "read")]
    assert "OTE(Motor_Run)" in hits[0].source_line
    assert hits[0].block == "MainProgram.MainRoutine"
    st_hits = ops.find_symbol(path, "Conv_Speed")
    assert [(h.block, h.line) for h in st_hits] == [("MainProgram.SpeedCalc", 0)]


@pytest.mark.unit
def test_l5x_rejects_doctype_and_entities(tmp_path):
    evil = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'
    path = _write(tmp_path, "evil.l5x", evil)
    outline = ops.outline_program(path)
    assert outline.blocks == ()
    assert any("DTD/entity" in e for e in outline.parse_errors)
    with pytest.raises(ValueError, match="XXE|DTD"):
        ops.find_symbol(path, "x")


@pytest.mark.unit
def test_l5x_malformed_xml_degrades_gracefully(tmp_path):
    path = _write(tmp_path, "cut.l5x", L5X_SAMPLE[: len(L5X_SAMPLE) // 2])
    outline = ops.outline_program(path)
    assert outline.blocks == ()
    assert any("parse failed" in e for e in outline.parse_errors)


# ─── format sniffing + path validation ───────────────────────────────────────


@pytest.mark.unit
def test_txt_extension_content_sniffing(tmp_path):
    assert ops.outline_program(_write(tmp_path, "a.txt", L5X_SAMPLE)).fmt == "l5x"
    assert ops.outline_program(_write(tmp_path, "b.txt", SCL_SAMPLE)).fmt == "scl"
    assert ops.outline_program(_write(tmp_path, "c.txt", AWL_SAMPLE)).fmt == "awl"


@pytest.mark.unit
def test_path_validation_rejections(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        ops.validate_program_path(str(tmp_path / "missing.scl"))
    with pytest.raises(ValueError, match="not a file"):
        ops.validate_program_path(str(tmp_path))
    bad_ext = tmp_path / "prog.exe"
    bad_ext.write_text("x")
    with pytest.raises(ValueError, match="unsupported extension"):
        ops.validate_program_path(str(bad_ext))
    big = tmp_path / "big.scl"
    big.write_bytes(b"\x00" * (ops.MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        ops.validate_program_path(str(big))
    with pytest.raises(ValueError, match="required"):
        ops.validate_program_path("  ")


# ─── MCP tools: governed + bounded ───────────────────────────────────────────


@pytest.mark.unit
def test_tools_are_governed_low_risk_and_registered():
    for tool in (plc_program_outline, plc_program_xref, plc_program_section):
        assert getattr(tool, "_is_governed_tool", False) is True
        assert getattr(tool, "_risk_level", "") == "low"
    assert "plc_program_tools" in BRAIN_MODULES  # always-on brain module


@pytest.mark.unit
def test_outline_tool_bounded_with_truncation_flags(home, tmp_path):
    many = "\n".join(
        f"FUNCTION_BLOCK FB_{i}\nEND_FUNCTION_BLOCK" for i in range(MAX_BLOCKS + 10)
    )
    result = plc_program_outline(path=_write(tmp_path, "many.scl", many))
    assert "error" not in result
    assert len(result["blocks"]) == MAX_BLOCKS
    assert result["blocks_truncated"] is True
    assert result["stats"]["blocks"] == MAX_BLOCKS + 10

    fat = ("FUNCTION_BLOCK FB_Fat\nVAR_INPUT\n"
           + "\n".join(f"    v{i} : BOOL;" for i in range(MAX_VARS_PER_BLOCK + 5))
           + "\nEND_VAR\nEND_FUNCTION_BLOCK")
    result = plc_program_outline(path=_write(tmp_path, "fat.scl", fat))
    blk = result["blocks"][0]
    assert len(blk["variables"]) == MAX_VARS_PER_BLOCK
    assert blk["variables_truncated"] is True


@pytest.mark.unit
def test_outline_tool_returns_citation_note_and_parse_errors(home, tmp_path):
    result = plc_program_outline(
        path=_write(tmp_path, "cut.scl", SCL_SAMPLE.split("END_FUNCTION_BLOCK")[0])
    )
    assert "source_file" in result["citation_note"] or "cite" in result["citation_note"]
    assert result["parse_errors"]


@pytest.mark.unit
def test_xref_tool_bounded_and_counted(home, tmp_path):
    path = _write(tmp_path, "conveyor.scl", SCL_SAMPLE)
    result = plc_program_xref(path=path, symbol="Running")
    assert "error" not in result
    assert result["hit_count"] == len(result["hits"]) == 4
    assert result["hits_truncated"] is False
    assert result["by_access"]["write"] == 2  # := TRUE and := FALSE
    assert all(h["source_line"] for h in result["hits"])


@pytest.mark.unit
def test_section_tool_returns_named_block_capped(home, tmp_path):
    path = _write(tmp_path, "conveyor.scl", SCL_SAMPLE)
    result = plc_program_section(path=path, block="FB_Conveyor")
    assert "error" not in result
    assert result["block"] == "FB_Conveyor"
    assert result["start_line"] == 2 and result["end_line"] == 23
    assert 'FUNCTION_BLOCK "FB_Conveyor"' in result["source"]
    assert result["truncated"] is False
    missing = plc_program_section(path=path, block="FB_Nope")
    assert "FB_Nope" in missing["error"]  # ValueError → sanitized error dict


@pytest.mark.unit
def test_section_tool_l5x_rungs(home, tmp_path):
    path = _write(tmp_path, "line3.L5X", L5X_SAMPLE)
    result = plc_program_section(path=path, block="MainRoutine")
    assert result["block"] == "MainProgram.MainRoutine"
    assert "[rung 0]" in result["source"]
    assert "Start/stop seal-in" in result["source"]


@pytest.mark.unit
def test_tools_reject_bad_paths_as_error_dict(home, tmp_path):
    result = plc_program_outline(path=str(tmp_path / "missing.scl"))
    assert "error" in result and "not found" in result["error"]
    result = plc_program_xref(path=str(tmp_path), symbol="X")
    assert "error" in result


# ─── CLI ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cli_program_commands(home, tmp_path):
    from iaiops.cli._root import app

    runner = CliRunner()
    path = _write(tmp_path, "conveyor.scl", SCL_SAMPLE)
    for args in (
        ["program", "outline", path],
        ["program", "xref", path, "Running"],
        ["program", "section", path, "FB_Conveyor"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    bad = runner.invoke(app, ["program", "outline", str(tmp_path / "nope.scl")])
    assert bad.exit_code == 1
