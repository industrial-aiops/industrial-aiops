"""One agent, several machines — the shape a real cppagent actually serves.

`test_mtconnect.py`'s fixture has ONE `DeviceStream` and no `Agent` stream, so
every observation in it belongs to the only device there is. A real MTConnect
agent (verified against `mtconnect/agent:2.7.0.13`, empty configuration) streams
its OWN `Agent` device alongside the machines, and its Availability is
`AVAILABLE` whenever it is answering — which is whenever you are asking.

That made two defects invisible:

* `mtconnect_oee_snapshot` picked data items by TYPE across the whole document,
  keeping whichever came last. With the Agent stream last, a stopped machine
  reports as available — the direction that INFLATES availability.
* `UNAVAILABLE`, MTConnect's own word for "the agent has no valid value here"
  (usually a disconnected adapter), was rendered as `down`. Blindness as
  downtime, the substitution #202 removed from RCA.

The documents below carry the real agent's shape. `test_mtconnect_agent_live.py`
runs the same assertions against the reference implementation itself.
"""

from __future__ import annotations

import pytest

from iaiops.connectors.mtconnect import ops
from iaiops.core.runtime.config import TargetConfig

_NS = "urn:mtconnect.org:MTConnectStreams:2.0"

pytestmark = [pytest.mark.unit]


def _machine(name: str, uuid: str, availability: str, execution: str = "UNAVAILABLE") -> str:
    return f"""
    <DeviceStream name="{name}" uuid="{uuid}">
      <ComponentStream component="Controller" name="controller" componentId="ctrl-{uuid}">
        <Events>
          <Availability dataItemId="avail-{uuid}" sequence="1"
                        timestamp="2026-08-28T16:00:00Z">{availability}</Availability>
          <Execution dataItemId="exec-{uuid}" sequence="2"
                     timestamp="2026-08-28T16:00:00Z">{execution}</Execution>
          <Program dataItemId="prog-{uuid}" sequence="3"
                   timestamp="2026-08-28T16:00:00Z">{name}-PROGRAM</Program>
        </Events>
      </ComponentStream>
    </DeviceStream>"""


#: The agent reporting on ITSELF. Always AVAILABLE while it answers.
_AGENT_STREAM = """
    <DeviceStream name="Agent" uuid="16ac1535-3574-509c-8fb2-c536984015fe">
      <ComponentStream component="Agent" name="Agent" componentId="agent">
        <Events>
          <Availability dataItemId="agent_avail" sequence="24"
                        timestamp="2026-08-28T16:00:00Z">AVAILABLE</Availability>
        </Events>
      </ComponentStream>
    </DeviceStream>"""


def _streams(*device_xml: str) -> str:
    return (
        f'<?xml version="1.0"?>\n<MTConnectStreams xmlns="{_NS}">'
        '<Header creationTime="2026-08-28T16:00:01Z" instanceId="1" sender="agent"'
        ' nextSequence="26" firstSequence="1" lastSequence="25"/>'
        f"<Streams>{''.join(device_xml)}</Streams></MTConnectStreams>"
    )


def _target(monkeypatch, document: str, device: str = "") -> TargetConfig:
    monkeypatch.setattr(ops, "_http_get", lambda url, timeout=10: document)
    return TargetConfig(name="vmc", protocol="mtconnect", agent_url="http://h:5000", device=device)


class TestTheAgentIsNotTheMachine:
    def test_the_agents_own_availability_is_never_reported_as_the_machines(self, monkeypatch):
        """The Agent stream LAST — document order that used to win.

        This is the failing case: `AVAILABLE` from the agent replacing
        `UNAVAILABLE` from the machine reports a stopped machine as available,
        and every availability figure built on it is inflated.
        """
        doc = _streams(_machine("VMC1", "vmc-001", "UNAVAILABLE"), _AGENT_STREAM)
        out = ops.mtconnect_oee_snapshot(_target(monkeypatch, doc))
        assert out["device"] == "VMC1"
        assert out["availability"] == "UNAVAILABLE"
        assert out["available"] is False

    def test_the_machine_is_resolved_whichever_order_the_agent_streams_come_in(self, monkeypatch):
        for doc in (
            _streams(_AGENT_STREAM, _machine("VMC1", "vmc-001", "AVAILABLE", "ACTIVE")),
            _streams(_machine("VMC1", "vmc-001", "AVAILABLE", "ACTIVE"), _AGENT_STREAM),
        ):
            out = ops.mtconnect_oee_snapshot(_target(monkeypatch, doc))
            assert (out["device"], out["verdict"]) == ("VMC1", "running")

    def test_the_agent_is_still_listed_so_the_reader_can_see_it_is_there(self, monkeypatch):
        doc = _streams(_AGENT_STREAM, _machine("VMC1", "vmc-001", "AVAILABLE"))
        assert ops.mtconnect_oee_snapshot(_target(monkeypatch, doc))["devices"] == [
            "Agent",
            "VMC1",
        ]


class TestUnavailableIsNotDown:
    def test_unavailable_has_its_own_verdict(self, monkeypatch):
        doc = _streams(_AGENT_STREAM, _machine("VMC1", "vmc-001", "UNAVAILABLE"))
        out = ops.mtconnect_oee_snapshot(_target(monkeypatch, doc))
        assert out["verdict"] == "unavailable"
        assert "not the same as the machine being down" in out["note"]

    def test_a_device_with_no_availability_item_is_unknown_not_down(self, monkeypatch):
        bare = """
    <DeviceStream name="VMC1" uuid="vmc-001">
      <ComponentStream component="Controller" name="controller" componentId="c">
        <Events><Program dataItemId="p" sequence="1"
                         timestamp="2026-08-28T16:00:00Z">O1</Program></Events>
      </ComponentStream>
    </DeviceStream>"""
        out = ops.mtconnect_oee_snapshot(_target(monkeypatch, _streams(bare)))
        assert out["verdict"] == "unknown"
        assert "not observable" in out["note"]

    def test_down_is_no_longer_a_verdict_this_function_can_produce(self, monkeypatch):
        """`down` asserted a physical state from an absence of data."""
        for availability in ("AVAILABLE", "UNAVAILABLE", ""):
            doc = _streams(_machine("VMC1", "vmc-001", availability))
            assert ops.mtconnect_oee_snapshot(_target(monkeypatch, doc))["verdict"] != "down"


class TestTwoMachinesAreRefusedNotResolved:
    def _two(self) -> str:
        return _streams(
            _AGENT_STREAM,
            _machine("VMC1", "vmc-001", "AVAILABLE", "ACTIVE"),
            _machine("VMC2", "vmc-002", "UNAVAILABLE"),
        )

    def test_an_undeclared_endpoint_refuses(self, monkeypatch):
        out = ops.mtconnect_oee_snapshot(_target(monkeypatch, self._two()))
        assert out["verdict"] == "unknown" and out["device"] == ""
        assert "VMC1" in out["note"] and "VMC2" in out["note"]
        assert "device:" in out["note"]

    def test_a_declared_device_is_scoped_to_its_own_values(self, monkeypatch):
        out = ops.mtconnect_oee_snapshot(_target(monkeypatch, self._two(), device="VMC2"))
        assert (out["device"], out["availability"]) == ("VMC2", "UNAVAILABLE")
        assert out["program"] == "VMC2-PROGRAM", "picked another machine's program"

    def test_a_device_can_be_named_by_uuid(self, monkeypatch):
        out = ops.mtconnect_oee_snapshot(_target(monkeypatch, self._two(), device="vmc-001"))
        assert out["program"] == "VMC1-PROGRAM"

    def test_a_name_that_is_not_there_refuses_and_says_what_is(self, monkeypatch):
        out = ops.mtconnect_oee_snapshot(_target(monkeypatch, self._two(), device="VMC9"))
        assert out["verdict"] == "unknown"
        assert "VMC9" in out["note"] and "VMC1" in out["note"]


class TestObservationsCarryTheirDevice:
    def test_current_attributes_every_observation(self, monkeypatch):
        doc = _streams(_AGENT_STREAM, _machine("VMC1", "vmc-001", "AVAILABLE"))
        obs = ops.mtconnect_current(_target(monkeypatch, doc))["observations"]
        by_device = {o["device"] for o in obs}
        assert by_device == {"Agent", "VMC1"}, (
            "without this the agent's own housekeeping is indistinguishable from the machine's data"
        )

    def test_the_uuid_travels_with_the_name(self, monkeypatch):
        doc = _streams(_machine("VMC1", "vmc-001", "AVAILABLE"))
        obs = ops.mtconnect_current(_target(monkeypatch, doc))["observations"]
        assert all(o["device_uuid"] == "vmc-001" for o in obs)
