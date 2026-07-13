"""``export_data`` MCP tool — governed marker, bounded output, validation.

IAIOPS_HOME is pointed at tmp_path so the tool's default store (data.db) and
default output dir (exports/) never touch the real ~/.iaiops.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iaiops.core.sink.push import historian_push
from mcp_server.profiles import BRAIN_MODULES
from mcp_server.tools.export_tools import MAX_INLINE_ROWS, export_data


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IAIOPS_HOME", str(tmp_path))
    return tmp_path


def _seed(home: Path, n: int) -> None:
    points = [
        {
            "ref": f"tag{i % 7}",
            "value": float(i),
            "timestamp": f"2026-07-01T{i % 24:02d}:{i % 60:02d}:00Z",
        }
        for i in range(n)
    ]
    assert "error" not in historian_push(points, "sqlite", db_path=home / "data.db")


@pytest.mark.unit
def test_export_data_is_governed_low_risk_and_registered():
    assert getattr(export_data, "_is_governed_tool", False) is True
    assert getattr(export_data, "_risk_level", "") == "low"
    assert "export_tools" in BRAIN_MODULES  # always-on brain module


@pytest.mark.unit
def test_export_data_bounded_preview(home):
    _seed(home, 300)
    result = export_data(fmt="csv")
    assert "error" not in result
    assert result["rows"] == 300
    assert len(result["preview_rows"]) == MAX_INLINE_ROWS == 200
    assert result["preview_truncated"] is True
    out = Path(result["path"])
    assert out.exists() and str(home) in str(out)  # defaults under IAIOPS_HOME
    assert out.parent.name == "exports"


@pytest.mark.unit
def test_export_data_small_result_not_truncated(home):
    _seed(home, 5)
    result = export_data(fmt="csv", tag="tag1", out_path=str(home / "t.csv"))
    assert result["rows"] == 1
    assert len(result["preview_rows"]) == 1
    assert result["preview_truncated"] is False
    assert result["path"] == str(home / "t.csv")


@pytest.mark.unit
def test_export_data_invalid_input_returns_teaching_error(home):
    _seed(home, 1)
    assert "Unknown format" in export_data(fmt="xlsx")["error"]
    assert "limit" in export_data(fmt="csv", limit=0)["error"]
    assert "ISO-8601" in export_data(fmt="csv", since="soon")["error"]


@pytest.mark.unit
def test_export_data_missing_store_teaches_collection(home):
    result = export_data(fmt="csv")
    assert "No local store" in result["error"]
