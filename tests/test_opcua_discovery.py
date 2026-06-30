"""OPC-UA tag auto-discovery + semantic modeling.

Pure-function tests (classify / alias / model) run everywhere; the discovery
sweep runs against a REAL in-process asyncua server (a Line1 asset with units +
a nested Mixer object) so the address-space walk, unit read, and asset grouping
are exercised for real, not mocked.
"""

from __future__ import annotations

import socket

import pytest

from iaiops.connectors.opcua import discovery as disc
from iaiops.core.runtime.config import TargetConfig

# ── pure unit tests ───────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Temperature", "temperature"),
        ("Inlet_Pressure", "pressure"),
        ("MotorFault", "alarm"),
        ("SpeedSetpoint", "setpoint"),  # setpoint precedes speed
        ("RunState", "state"),
        ("FlowRate", "flow"),
        ("kWh_Total", "energy"),  # energy precedes counter
        ("Xy", "other"),
    ],
)
def test_classify_tag(name, expected):
    assert disc.classify_tag(name) == expected


@pytest.mark.unit
def test_suggest_alias_path_and_sanitization():
    assert disc.suggest_alias("Line1/Mixer", "Temperature") == "line1.mixer.temperature"
    assert disc.suggest_alias("", "Flow Rate!") == "flow_rate"
    assert disc.suggest_alias("Cell A", "T") == "cell_a.t"


@pytest.mark.unit
def test_build_tag_model_groups_and_flags():
    tags = [
        {"asset": "Line1", "browse_name": "Temperature", "browse_path": "Line1/Temperature",
         "class": "temperature", "suggested_alias": "line1.temperature"},
        {"asset": "Line1", "browse_name": "Pressure", "browse_path": "Line1/Pressure",
         "class": "pressure", "suggested_alias": "line1.pressure"},
        {"asset": "Line2", "browse_name": "Temperature", "browse_path": "Line2/Temperature",
         "class": "temperature", "suggested_alias": "line2.temperature"},
    ]
    model = disc.build_tag_model(tags)
    assert model["tag_count"] == 3
    assert model["asset_count"] == 2
    line1 = next(a for a in model["assets"] if a["asset"] == "Line1")
    assert line1["tag_count"] == 2
    assert line1["classes"] == {"pressure": 1, "temperature": 1}
    assert model["naming_quality"]["verdict"] == "clean"


@pytest.mark.unit
def test_build_tag_model_detects_alias_collision_and_cryptic():
    tags = [
        {"asset": "L1", "browse_name": "T", "browse_path": "L1/T", "class": "other",
         "suggested_alias": "l1.t"},
        {"asset": "L1", "browse_name": "T", "browse_path": "L1/T", "class": "other",
         "suggested_alias": "l1.t"},  # collision
    ]
    model = disc.build_tag_model(tags)
    assert "l1.t" in model["naming_quality"]["alias_collisions"]
    assert "L1/T" in model["naming_quality"]["cryptic_names"]
    assert model["naming_quality"]["verdict"] == "review"


# ── integration against a real asyncua server ─────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def disco_server():
    """Real asyncua server: Line1 {Temperature(°C), Pressure, Mixer{Speed}}."""
    from asyncua import ua
    from asyncua.sync import Server

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/disco"
    srv = Server()
    srv.set_endpoint(url)
    idx = srv.register_namespace("http://aiops.test/disco")
    line = srv.nodes.objects.add_folder(idx, "Line1")
    temp = line.add_variable(idx, "Temperature", 85.0)
    eu = ua.EUInformation()
    eu.DisplayName = ua.LocalizedText("degC")
    temp.add_property(idx, "EngineeringUnits", eu)
    line.add_variable(idx, "Pressure", 4.2)
    mixer = line.add_object(idx, "Mixer")
    sp = mixer.add_variable(idx, "SpeedSetpoint", 1500.0)
    sp.set_writable(True)  # so the discovery 'writable' flag is exercised both ways
    srv.start()
    try:
        yield url
    finally:
        srv.stop()


def _target(url: str) -> TargetConfig:
    return TargetConfig(name="disco", protocol="opcua", endpoint_url=url)


@pytest.mark.integration
def test_discover_tags_real(disco_server):
    tags = disc.discover_tags(_target(disco_server), max_depth=6)
    by_name = {t["browse_name"]: t for t in tags}
    # all three Variables found; the EngineeringUnits property is NOT a tag itself
    assert {"Temperature", "Pressure", "SpeedSetpoint"} <= set(by_name)
    assert "EngineeringUnits" not in by_name
    temp = by_name["Temperature"]
    assert temp["class"] == "temperature"
    assert temp["datatype"] == "Double"
    assert temp["unit"] == "degC"
    assert temp["asset"] == "Line1"
    assert temp["suggested_alias"] == "line1.temperature"
    assert temp["writable"] is False  # read-only variable
    # nested object → deeper asset path; writable flag reads the real access level
    assert by_name["SpeedSetpoint"]["asset"] == "Line1/Mixer"
    assert by_name["SpeedSetpoint"]["class"] == "setpoint"
    assert by_name["SpeedSetpoint"]["writable"] is True


@pytest.mark.integration
def test_tag_discovery_model_real(disco_server):
    model = disc.tag_discovery(_target(disco_server), max_depth=6)
    assert model["endpoint"] == "disco"
    assert model["tag_count"] == 3
    assets = {a["asset"] for a in model["assets"]}
    assert {"Line1", "Line1/Mixer"} <= assets
    assert model["naming_quality"]["verdict"] == "clean"
