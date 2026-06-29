"""MTConnect ops tests against static XML fixtures (no live agent).

The module-level ``_http_get`` is monkeypatched to return realistic MTConnect
Probe / Current / Sample / Assets documents, so the XML parsing, observation
extraction, and OEE snapshot logic are exercised for real.
"""

from __future__ import annotations

import pytest

from iaiops.connectors.mtconnect import ops
from iaiops.core.runtime.config import TargetConfig

_NS_DEV = "urn:mtconnect.org:MTConnectDevices:1.7"
_NS_STREAMS = "urn:mtconnect.org:MTConnectStreams:1.7"
_NS_ASSETS = "urn:mtconnect.org:MTConnectAssets:1.7"

PROBE_XML = f"""<?xml version="1.0"?>
<MTConnectDevices xmlns="{_NS_DEV}">
  <Header creationTime="2026-06-28T10:00:00Z" instanceId="1" sender="agent"/>
  <Devices>
    <Device id="d1" name="VMC1" uuid="VMC1-001">
      <Components>
        <Axes id="ax" name="Axes">
          <Components>
            <Linear id="x" name="X">
              <DataItems>
                <DataItem id="xpos" type="POSITION" category="SAMPLE" name="Xact"
                          units="MILLIMETER"/>
              </DataItems>
            </Linear>
          </Components>
        </Axes>
        <Controller id="ctrl" name="Controller">
          <DataItems>
            <DataItem id="avail" type="AVAILABILITY" category="EVENT"/>
            <DataItem id="exec" type="EXECUTION" category="EVENT"/>
            <DataItem id="mode" type="CONTROLLER_MODE" category="EVENT"/>
            <DataItem id="prog" type="PROGRAM" category="EVENT"/>
          </DataItems>
        </Controller>
      </Components>
    </Device>
  </Devices>
</MTConnectDevices>"""

CURRENT_XML = f"""<?xml version="1.0"?>
<MTConnectStreams xmlns="{_NS_STREAMS}">
  <Header creationTime="2026-06-28T10:00:01Z" instanceId="1" sender="agent"/>
  <Streams>
    <DeviceStream name="VMC1" uuid="VMC1-001">
      <ComponentStream component="Controller" name="Controller" componentId="ctrl">
        <Events>
          <Availability dataItemId="avail" timestamp="2026-06-28T10:00:00Z"
                        sequence="1">AVAILABLE</Availability>
          <Execution dataItemId="exec" timestamp="2026-06-28T10:00:00Z"
                     sequence="2">ACTIVE</Execution>
          <ControllerMode dataItemId="mode" timestamp="2026-06-28T10:00:00Z"
                          sequence="3">AUTOMATIC</ControllerMode>
          <Program dataItemId="prog" timestamp="2026-06-28T10:00:00Z"
                   sequence="4">O1234</Program>
        </Events>
      </ComponentStream>
      <ComponentStream component="Linear" name="X" componentId="x">
        <Samples>
          <Position dataItemId="xpos" timestamp="2026-06-28T10:00:00Z"
                    sequence="5">12.5</Position>
        </Samples>
      </ComponentStream>
    </DeviceStream>
  </Streams>
</MTConnectStreams>"""

ASSETS_XML = f"""<?xml version="1.0"?>
<MTConnectAssets xmlns="{_NS_ASSETS}">
  <Header creationTime="2026-06-28T10:00:02Z" instanceId="1" sender="agent"/>
  <Assets>
    <CuttingTool assetId="T1" timestamp="2026-06-28T09:00:00Z"/>
    <CuttingTool assetId="T2" timestamp="2026-06-28T09:30:00Z"/>
  </Assets>
</MTConnectAssets>"""


@pytest.fixture
def cnc_target(monkeypatch):
    def _fake_get(url, timeout=10):
        if url.endswith("/probe"):
            return PROBE_XML
        if "/sample" in url:
            return CURRENT_XML  # same stream shape suffices for the test
        if url.endswith("/current"):
            return CURRENT_XML
        if url.endswith("/assets"):
            return ASSETS_XML
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(ops, "_http_get", _fake_get)
    return TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")


@pytest.mark.unit
def test_probe_models_device(cnc_target):
    out = ops.mtconnect_probe(cnc_target)
    assert out["device_count"] == 1
    dev = out["devices"][0]
    assert dev["name"] == "VMC1" and dev["uuid"] == "VMC1-001"
    ids = {di["id"] for comp in dev["components"] for di in comp["data_items"]}
    assert {"xpos", "avail", "exec", "prog"} <= ids


@pytest.mark.unit
def test_current_observations(cnc_target):
    out = ops.mtconnect_current(cnc_target)
    by_id = {o["data_item_id"]: o for o in out["observations"]}
    assert by_id["avail"]["value"] == "AVAILABLE"
    assert by_id["xpos"]["value"] == "12.5"
    assert by_id["exec"]["timestamp"].startswith("2026-06-28")


@pytest.mark.unit
def test_sample_is_bounded(cnc_target):
    out = ops.mtconnect_sample(cnc_target, count=10000)
    assert out["requested_count"] <= ops.MAX_SAMPLE_COUNT


@pytest.mark.unit
def test_assets(cnc_target):
    out = ops.mtconnect_assets(cnc_target)
    assert out["asset_count"] == 2
    assert {a["asset_id"] for a in out["assets"]} == {"T1", "T2"}


@pytest.mark.unit
def test_xml_with_dtd_is_rejected(monkeypatch):
    evil = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]>'
            '<MTConnectStreams><Streams/></MTConnectStreams>')
    monkeypatch.setattr(ops, "_http_get", lambda url, timeout=10: evil)
    target = TargetConfig(name="vmc1", protocol="mtconnect", agent_url="http://h:5000")
    with pytest.raises(ValueError, match="DTD/entity"):
        ops.mtconnect_current(target)


@pytest.mark.unit
def test_oee_snapshot_running(cnc_target):
    out = ops.mtconnect_oee_snapshot(cnc_target)
    assert out["availability"] == "AVAILABLE"
    assert out["execution"] == "ACTIVE"
    assert out["controller_mode"] == "AUTOMATIC"
    assert out["program"] == "O1234"
    assert out["available"] is True and out["running"] is True
    assert out["verdict"] == "running"
