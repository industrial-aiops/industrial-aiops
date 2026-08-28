"""Rung 2a for EtherNet/IP IDENTIFICATION — a stack somebody else wrote.

`tests/eip_plc_harness.py` is a CIP PLC written in this repo, and its own
docstring is clear about the limit: "misread them and harness and expectations
are wrong together". `cpppo` is an independent EtherNet/IP implementation. It
answers ListIdentity as a `1756-L61/B LOGIX5561`, which is exactly the exchange
an inventory sweep is entitled to make.

Running it found the identification probe doing something else entirely: named
`eip_list_identity`, promising "CIP identity object read over explicit
messaging", and calling `eip_controller_info` — a `LogixDriver` open, which
pycomm3 ends with `get_tag_list(program="*")`, the controller's whole symbol
table. Measured against this simulator, the probe went from 6 requests / 324
bytes to 3 / 76.

**What this does NOT cover.** cpppo implements the Identity object and a tag
interface, but none of the Logix objects `LogixDriver` needs: 0x64 returns a
reply pycomm3 cannot parse, 0x6B and 0x6C drop the connection. The Logix tag
layer therefore stays at 2b (`test_eip_live.py`) and a physical ControlLogix
stays rung 3.

Bring the simulator up with `scripts/enip_simulator_harness.sh`.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("pycomm3", reason="pycomm3 not installed — install iaiops[eip]")

from iaiops.core.discovery import identify, wirelog  # noqa: E402

ENIP_HOST = os.environ.get("IAIOPS_ENIP_HOST", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ENIP_HOST,
        reason="set IAIOPS_ENIP_HOST (scripts/enip_simulator_harness.sh)",
    ),
]


class TestIdentificationAgainstAThirdPartyStack:
    def test_the_probe_identifies_the_device(self):
        out = identify._probe_eip(ENIP_HOST, 44818, 5.0, wirelog.WireLog())
        assert out.get("vendor"), "no vendor came back from a device that answers ListIdentity"
        assert out.get("model"), "no product name came back"

    def test_it_records_exactly_the_emission_it_declared(self):
        log = wirelog.WireLog()
        identify._probe_eip(ENIP_HOST, 44818, 5.0, log)
        kinds = set(log.summary())
        assert kinds == {wirelog.EIP_LIST_IDENTITY}, (
            f"the signed artifact would name {kinds}, which is not what ran"
        )

    def test_identification_does_not_upload_the_tag_list(self, monkeypatch):
        """The reason this file exists. Asserted on the real wire, not a mock.

        `eip_list_tags` is the symbol-table upload. An inventory sweep whose
        preview says "one minimal in-spec read per candidate" must not reach it,
        and `LogixDriver.open()` reaches it without being asked.
        """
        from iaiops.connectors.eip import ops

        def _forbidden(*args, **kwargs):
            raise AssertionError("identification uploaded the controller tag list")

        monkeypatch.setattr(ops, "eip_list_tags", _forbidden)
        monkeypatch.setattr(ops, "eip_controller_info", _forbidden)
        assert identify._probe_eip(ENIP_HOST, 44818, 5.0, wirelog.WireLog()).get("vendor")
