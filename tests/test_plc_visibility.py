"""Legacy-PLC visibility profile — maintainability/risk read over a parsed outline."""

import pytest

from iaiops.core.brain.plc_program.model import (
    Block,
    Branch,
    CallEdge,
    ProgramOutline,
    TimerCounter,
)
from iaiops.core.brain.plc_visibility import plc_visibility
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.plc_program_tools import plc_program_visibility


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


def _outline() -> ProgramOutline:
    """An OB1 that calls FB_Conveyor; FB_Dead is referenced by nothing."""
    ob1 = Block(
        name="OB1",
        kind="ORGANIZATION_BLOCK",
        language="scl",
        source_file="prog.scl",
        line=1,
        end_line=10,
        calls=(CallEdge("OB1", "FB_Conveyor", "prog.scl", 5),),
        comment="Main cyclic OB",
    )
    conveyor = Block(
        name="FB_Conveyor",
        kind="FUNCTION_BLOCK",
        language="scl",
        source_file="prog.scl",
        line=20,
        end_line=80,
        branches=(
            Branch("IF", "Run", "prog.scl", 30),
            Branch("FOR", "i:=1..10", "prog.scl", 40),
            Branch("JMP", "", "prog.scl", 55),
        ),
        timers_counters=(TimerCounter("T_run", "RTO", "prog.scl", 60),),
        comment="",  # uncommented → maintainer lands blind
    )
    dead = Block(
        name="FB_Dead",
        kind="FUNCTION_BLOCK",
        language="scl",
        source_file="prog.scl",
        line=90,
        end_line=95,
        comment="",
    )
    return ProgramOutline(
        source_file="prog.scl",
        fmt="scl",
        blocks=(ob1, conveyor, dead),
        call_edges=(CallEdge("OB1", "FB_Conveyor", "prog.scl", 5),),
        comment_count=2,
        line_count=100,
    )


@pytest.mark.unit
def test_entry_points_and_unreferenced_blocks():
    out = plc_visibility(_outline())
    assert [e["name"] for e in out["entry_points"]] == ["OB1"]
    unref = [b["name"] for b in out["unreferenced_blocks"]]
    assert unref == ["FB_Dead"]  # OB1 is an entry, FB_Conveyor is called


@pytest.mark.unit
def test_complexity_hotspot_is_the_busy_block():
    out = plc_visibility(_outline())
    top = out["complexity_hotspots"][0]
    assert top["block"] == "FB_Conveyor"
    assert top["score"] == 4  # 3 branches + 0 calls + 1 timer


@pytest.mark.unit
def test_risky_constructs_flag_jmp_rto_and_loop():
    risky = plc_visibility(_outline())["risky_constructs"]
    assert risky["unconditional_jump_count"] == 1
    assert risky["retentive_timer_count"] == 1
    assert risky["loop_count"] == 1 and risky["loops"][0]["kind"] == "FOR"


@pytest.mark.unit
def test_documentation_band_and_uncommented_blocks():
    doc = plc_visibility(_outline())["documentation"]
    assert doc["comment_ratio"] == 0.02  # 2 / 100
    assert doc["band"] == "undocumented"
    assert doc["uncommented_block_count"] == 2  # FB_Conveyor, FB_Dead


@pytest.mark.unit
def test_risk_score_is_transparent_and_cited():
    risk = plc_visibility(_outline())["risk"]
    assert risk["band"] in ("medium", "high")
    assert 0 < risk["score"] <= 100
    # every risk point is explained
    assert risk["reasons"] and all(isinstance(r, str) for r in risk["reasons"])
    joined = " ".join(risk["reasons"])
    assert "undocumented" in joined and "JMP" in joined


@pytest.mark.unit
def test_empty_outline_is_low_risk():
    out = plc_visibility(ProgramOutline(source_file="x.scl", fmt="scl"))
    assert out["risk"]["band"] == "low"
    assert out["unreferenced_blocks"] == [] and out["complexity_hotspots"] == []


@pytest.mark.unit
def test_tool_governed_registered_and_runs(home, tmp_path):
    assert getattr(plc_program_visibility, "_is_governed_tool", False) is True
    assert getattr(plc_program_visibility, "_risk_level", "") == "low"
    assert "plc_program_tools" in BRAIN_MODULES
    prog = tmp_path / "line3.st"
    prog.write_text(
        "FUNCTION_BLOCK FB_Conveyor\n"
        "VAR\n  Run : BOOL;\nEND_VAR\n"
        "  IF Run THEN\n    Motor := TRUE;\n  END_IF;\n"
        "END_FUNCTION_BLOCK\n",
        "utf-8",
    )
    out = plc_program_visibility(path=str(prog))
    assert "error" not in out
    assert out["fmt"] == "scl"
    assert out["stats"]["blocks"] >= 1
    assert out["risk"]["band"] in ("low", "medium", "high")
