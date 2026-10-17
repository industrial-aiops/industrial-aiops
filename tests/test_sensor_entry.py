"""E2 (HLD §17.2): the sensor entry — menu, extra, MCP tools, CLI read.

One engine, two front-ends (HLD §3.1): `sensor_read_channel` (MCP) and
`iaiops sensor read` (CLI) both call `iaiops.core.runtime.sensor.probe.read_channel`.
Every tool is read-only and governed; none writes config (D51).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from iaiops.core.runtime.sensor import parse_profile
from iaiops.core.runtime.sensor.probe import read_channel

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
IODD = ROOT / "tests" / "fixtures" / "iodd" / "distance_sensor.xml"

PROFILE = parse_profile(
    {
        "id": "force",
        "protocol": "modbus",
        "source": "manual",
        "verified": "待核实",
        "channels": [
            {
                "name": "fz",
                "layout": {"table": "input", "address": 0, "type": "int16"},
                "unit": "N",
                "range": [-300, 300],
                "accuracy": {"full_scale": 300, "linearity_pct": 3.0},
                "signal": "level",
            }
        ],
    }
)


# ── packaging ────────────────────────────────────────────────────────────────


def test_sensor_menu_and_edition_module():
    from mcp_server import profiles

    assert set(profiles.NAMED_PROFILES["sensor"]) >= {"modbus", "iolink", "sparkplug"}
    assert profiles.EDITION_MODULES["sensor"] == ("sensor_tools",)
    assert "sensor_tools" in profiles.selected_tool_modules("sensor")
    assert "sensor_tools" not in profiles.selected_tool_modules("modbus")
    assert "sensor_tools" not in profiles.BRAIN_MODULES


def test_sensor_extra_and_console_script():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    extra = " ".join(project["optional-dependencies"]["sensor"])
    for wanted in ("modbus", "iolink", "sparkplug"):
        assert wanted in extra
    assert project["scripts"]["iaiops-mcp-sensor"] == "mcp_server.entrypoints:main_sensor"


def test_every_sensor_tool_is_governed_and_read_only():
    import mcp_server.tools.sensor_tools as tools

    for name in ("sensor_profile_check", "sensor_import_iodd", "sensor_read_channel"):
        fn = getattr(tools, name)
        assert getattr(fn, "_is_governed_tool", False), name
    source = (ROOT / "mcp_server" / "tools" / "sensor_tools.py").read_text()
    assert 'risk_level="high"' not in source and 'risk_level="medium"' not in source


# ── MCP tools over local files ───────────────────────────────────────────────


def test_profile_check_tool(tmp_path):
    from mcp_server.tools.sensor_tools import sensor_import_iodd, sensor_profile_check

    draft = sensor_import_iodd(str(IODD))
    assert "待核实" in draft["draft"] and any("Label" in n for n in draft["notes"])
    path = tmp_path / "tof.yaml"
    path.write_text(draft["draft"], "utf-8")
    out = sensor_profile_check(str(path))
    assert out["verified"] == "待核实" and {c["channel"] for c in out["channels"]} >= {"distance"}


def test_import_iodd_tool_writes_nothing(tmp_path, monkeypatch):
    from mcp_server.tools.sensor_tools import sensor_import_iodd

    monkeypatch.chdir(tmp_path)
    sensor_import_iodd(str(IODD))
    # The governed call is audited (audit.db*); no profile or config is written.
    written = [p.name for p in tmp_path.iterdir() if not p.name.startswith("audit.db")]
    assert written == []


def test_tools_refuse_the_wrong_file_kind_with_a_clear_reason(tmp_path):
    """Real files of the wrong kind: the refusal names the kind expected, rather
    than surfacing a parser error from feeding YAML to the XML importer."""
    import mcp_server.tools.sensor_tools as tools

    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text("id: x\n", "utf-8")
    assert "Expected a .xml" in tools.sensor_import_iodd(str(yaml_file))["error"]
    assert "Expected a .yaml/.yml" in tools.sensor_profile_check(str(IODD))["error"]


# ── the shared engine: three levels, never upgraded ──────────────────────────


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: PROFILE)
    return SimpleNamespace(
        name="cell", protocol="modbus", sensor_profile="force.yaml", port_profiles=()
    )


def _read_ref(result):
    def read_ref(target, ref):
        if isinstance(result, Exception):
            raise result
        return result

    return read_ref


def _caps(monkeypatch, result):
    from iaiops.core.runtime import capabilities

    cap = capabilities.REGISTRY["modbus"]
    monkeypatch.setitem(
        capabilities.REGISTRY,
        "modbus",
        type(cap)(**{**cap.__dict__, "read_ref": _read_ref(result)}),
    )


def test_a_good_read_reports_value_unit_band_and_verification(monkeypatch, bound):
    _caps(monkeypatch, {"value": 12.5, "good": True})
    out = read_channel(bound, "ch:fz")
    assert out["levels"] == {"reachable": True, "decodable": True}
    assert (out["value"], out["unit"], out["band"], out["verified"]) == (12.5, "N", 9.0, "待核实")
    assert out["profile"] == "force"


def test_a_refused_reading_is_reachable_but_not_decodable(monkeypatch, bound):
    _caps(
        monkeypatch,
        {"value": None, "good": False, "reason": "fz: 999 N is outside the sensor's range"},
    )
    out = read_channel(bound, "ch:fz")
    assert out["levels"] == {"reachable": True, "decodable": False}
    assert out["value"] is None and "range" in out["reason"]


def test_a_connection_failure_is_not_reachable_and_says_nothing_about_decoding(monkeypatch, bound):
    from iaiops.core.runtime.session_factory import OTConnectionError

    _caps(monkeypatch, OTConnectionError("timed out", protocol="modbus"))
    out = read_channel(bound, "ch:fz")
    assert out["levels"] == {"reachable": False, "decodable": None}
    assert "timed out" in out["reason"]


def test_a_ref_the_endpoint_cannot_read_is_refused_without_contacting(monkeypatch, bound):
    _caps(monkeypatch, AssertionError("must not be contacted"))
    out = read_channel(bound, "ch:nope")
    assert out["levels"] == {"reachable": None, "decodable": False}
    assert "nope" in out["reason"] and out["contacted"] is False


def test_other_protocols_are_refused():
    out = read_channel(SimpleNamespace(name="u", protocol="opcua"), "ns=2;s=x")
    assert out["levels"] == {"reachable": None, "decodable": None}
    assert "modbus" in out["reason"] and "iolink" in out["reason"]


def test_a_bare_modbus_address_is_flagged_untyped(monkeypatch, bound):
    _caps(monkeypatch, {"value": 65421, "good": True})
    out = read_channel(bound, "0")
    assert out["levels"]["decodable"] is True and out["untyped"] is True and out["unit"] == ""


# ── CLI front-end, same engine ───────────────────────────────────────────────


def test_cli_sensor_read_uses_the_same_engine(monkeypatch):
    from typer.testing import CliRunner

    from iaiops.cli.sensor import sensor_app

    seen = {}

    def fake(target, ref):
        seen["ref"] = ref
        return {"levels": {"reachable": True, "decodable": True}, "value": 1.0, "unit": "N"}

    monkeypatch.setattr("iaiops.core.runtime.sensor.probe.read_channel", fake)
    monkeypatch.setattr(
        "iaiops.core.runtime.connection.ConnectionManager.from_config",
        classmethod(
            lambda cls, config=None: SimpleNamespace(target=lambda name: SimpleNamespace(name=name))
        ),
    )
    result = CliRunner().invoke(sensor_app, ["read", "cell", "ch:fz", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["ref"] == "ch:fz" and '"unit": "N"' in result.output
