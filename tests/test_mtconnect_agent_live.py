"""Rung 2a — against the REFERENCE MTConnect agent, not a server we wrote.

Every other MTConnect test talks to something in this repo: `test_mtconnect.py`
monkeypatches the HTTP layer, and `test_mtconnect_live.py` runs a real
`ThreadingHTTPServer` that emits XML we compose. Both prove the parser reads
what WE emit. Neither can show what the MTConnect Institute's `cppagent`
actually emits, and the gap was not cosmetic:

* the agent streams its OWN `Agent` device beside the machines, whose
  Availability is `AVAILABLE` whenever it is answering — so a snapshot that
  picked data items by type across the document could report a stopped machine
  as available;
* a machine with no adapter connected is `UNAVAILABLE`, MTConnect's word for
  "the agent has no valid value", which had been rendered as `down`.

Both were found here, by running `mtconnect/agent:2.7.0.13` on an empty
configuration and reading what came back. `test_mtconnect_multi_device.py`
pins the same behaviour on recorded documents; this file is the evidence that
the recording matches the real thing.

Bring the agent up with `scripts/mtconnect_agent_harness.sh` and export the URL
it prints. Skipped when that is unset — and `IAIOPS_REQUIRE_LIVE=1` turns a skip
here into a failure, so a CI step that promises this rung cannot quietly become
a no-op.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("requests", reason="requests not installed — install iaiops[mtconnect]")

from iaiops.connectors.mtconnect import ops  # noqa: E402
from iaiops.core.runtime.config import TargetConfig  # noqa: E402

AGENT_URL = os.environ.get("IAIOPS_MTCONNECT_AGENT_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not AGENT_URL,
        reason="set IAIOPS_MTCONNECT_AGENT_URL (scripts/mtconnect_agent_harness.sh)",
    ),
]


def _target(device: str = "") -> TargetConfig:
    return TargetConfig(name="vmc", protocol="mtconnect", agent_url=AGENT_URL, device=device)


class TestWhatTheReferenceAgentActuallyStreams:
    def test_the_agent_streams_its_own_device_beside_the_machines(self):
        """The premise of the whole file. If this stops being true, say so loudly."""
        devices = ops.mtconnect_current(_target())["observations"]
        names = {o["device"] for o in devices}
        assert "Agent" in names, (
            "the reference agent no longer streams its own device — the fixtures in "
            "test_mtconnect_multi_device.py are modelled on it and need revisiting"
        )
        assert names - {"Agent"}, "no machine device streamed; check the harness config"

    def test_the_agent_reports_itself_available_while_the_machines_are_not(self):
        """This is the trap, verified on the real thing rather than assumed."""
        obs = ops.mtconnect_current(_target())["observations"]
        availability = {o["device"]: o["value"] for o in obs if o["type"].upper() == "AVAILABILITY"}
        assert availability.get("Agent") == "AVAILABLE"
        machines = {d: v for d, v in availability.items() if d != "Agent"}
        assert machines, "no machine publishes AVAILABILITY"
        assert set(machines.values()) == {"UNAVAILABLE"}, (
            "the harness connects no adapter, so every machine should be UNAVAILABLE"
        )


class TestTheSnapshotAgainstTheRealAgent:
    def test_an_agent_serving_two_machines_refuses_rather_than_picking(self):
        out = ops.mtconnect_oee_snapshot(_target())
        assert out["verdict"] == "unknown" and out["device"] == ""
        assert "device:" in out["note"]

    def test_a_named_machine_resolves_to_its_own_values(self):
        out = ops.mtconnect_oee_snapshot(_target(device="VMC1"))
        assert out["device"] == "VMC1"
        assert out["availability"] == "UNAVAILABLE"

    def test_an_unavailable_machine_is_never_called_down(self):
        out = ops.mtconnect_oee_snapshot(_target(device="VMC1"))
        assert out["verdict"] == "unavailable"
        assert out["verdict"] != "down"

    def test_the_probe_model_parses(self):
        """The device model the agent serves is not the XML we handed it."""
        probe = ops.mtconnect_probe(_target())
        assert probe["device_count"] >= 2
        assert {d["name"] for d in probe["devices"]} >= {"VMC1", "VMC2"}
