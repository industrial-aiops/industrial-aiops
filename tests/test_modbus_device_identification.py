"""FC43 / MEI-14 device identification — the safe way to ask a Modbus slave "what are you".

The load-bearing test is not the happy path. It is
``test_a_slave_without_fc43_answers_and_stays_alive``: a great many simple slaves
do not implement FC43, and the product's honesty depends on that being reported
as "alive, could not identify" rather than as an outage or, worse, a guessed
vendor.
"""

from __future__ import annotations

import pytest

from iaiops.connectors.modbus import ops
from iaiops.core.runtime.config import TargetConfig
from iaiops.core.runtime.connection import OTProtocolError

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, information=None, *, error=False, more_follows=False, conformity=0x83):
        self.information = information or {}
        self._error = error
        self.more_follows = more_follows
        self.conformity = conformity

    def isError(self) -> bool:  # noqa: N802 — pymodbus's own spelling
        return self._error


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []
        # A register read here would be the unsafe path; there is no such method
        # on this fake, so a regression that reaches for one fails loudly.

    def read_device_information(self, *, read_code=None, object_id=0, device_id=1, **kw):
        self.calls.append({"read_code": read_code, "device_id": device_id})
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


@pytest.fixture
def target():
    return TargetConfig(name="plc1", protocol="modbus", host="10.0.0.5", port=502, unit_id=3)


def patch_session(monkeypatch, client):
    from contextlib import contextmanager

    @contextmanager
    def fake_session(_target):
        yield client

    monkeypatch.setattr(ops, "modbus_session", fake_session)
    return client


class TestIdentification:
    def test_basic_objects_are_promoted_for_an_inventory_row(self, monkeypatch, target):
        client = patch_session(
            monkeypatch,
            FakeClient(
                FakeResponse(
                    {
                        0x00: b"Schneider Electric",
                        0x01: b"BMXP342020",
                        0x02: b"V2.70",
                    }
                )
            ),
        )
        result = ops.modbus_read_device_identification(target)
        assert result["vendor"] == "Schneider Electric"
        assert result["product_code"] == "BMXP342020"
        assert result["revision"] == "V2.70"
        assert result["object_count"] == 3
        assert result["unit_id"] == 3
        assert client.calls[0]["device_id"] == 3

    def test_it_asks_for_basic_by_default(self, monkeypatch, target):
        """BASIC is mandatory-ish and far more widely implemented than REGULAR;
        asking for more by default would fail on devices that support the less."""
        from pymodbus.pdu.mei_message import DeviceInformation

        client = patch_session(monkeypatch, FakeClient(FakeResponse({0x00: b"Acme"})))
        ops.modbus_read_device_identification(target)
        assert client.calls[0]["read_code"] == DeviceInformation.BASIC

    def test_extended_asks_for_regular(self, monkeypatch, target):
        from pymodbus.pdu.mei_message import DeviceInformation

        client = patch_session(monkeypatch, FakeClient(FakeResponse({0x00: b"Acme"})))
        ops.modbus_read_device_identification(target, extended=True)
        assert client.calls[0]["read_code"] == DeviceInformation.REGULAR

    def test_extended_object_names_are_mapped(self, monkeypatch, target):
        patch_session(
            monkeypatch,
            FakeClient(
                FakeResponse(
                    {
                        0x00: b"Acme",
                        0x03: b"https://acme.example",
                        0x04: b"FlowMaster",
                        0x05: b"FM-200",
                        0x06: b"Line 1 dosing",
                    }
                )
            ),
        )
        objects = ops.modbus_read_device_identification(target, extended=True)["objects"]
        assert objects["vendor_url"] == "https://acme.example"
        assert objects["product_name"] == "FlowMaster"
        assert objects["model_name"] == "FM-200"
        assert objects["user_application_name"] == "Line 1 dosing"

    def test_an_unknown_object_id_is_kept_not_dropped(self, monkeypatch, target):
        patch_session(monkeypatch, FakeClient(FakeResponse({0x00: b"Acme", 0x7F: b"custom"})))
        objects = ops.modbus_read_device_identification(target)["objects"]
        assert objects["object_0x7f"] == "custom"


class TestHonesty:
    def test_a_slave_without_fc43_answers_and_stays_alive(self, monkeypatch, target):
        """Many simple slaves reject FC43 with 'illegal function'. The device
        ANSWERED, so it is alive and reachable — OTProtocolError is the right
        signal, and the caller records 'identified by port only' rather than
        inventing a vendor or reporting an outage."""
        patch_session(monkeypatch, FakeClient(FakeResponse(error=True)))
        with pytest.raises(OTProtocolError) as excinfo:
            ops.modbus_read_device_identification(target)
        assert excinfo.value.protocol == "modbus"
        assert "device identification" in str(excinfo.value)

    def test_it_never_reads_a_register(self, monkeypatch, target):
        """Reading holding register 0 to identify a device is the unsafe path this
        function exists to replace: address 0 may be unmapped, and legacy slaves
        answer that by raising, dropping the session, or faulting."""
        client = patch_session(monkeypatch, FakeClient(FakeResponse({0x00: b"Acme"})))
        ops.modbus_read_device_identification(target)
        assert not hasattr(client, "read_holding_registers")
        assert list(client.calls[0]) == ["read_code", "device_id"]

    def test_undecodable_bytes_are_flagged_not_silently_mangled(self, monkeypatch, target):
        patch_session(monkeypatch, FakeClient(FakeResponse({0x00: b"Acm\xff\xfee"})))
        result = ops.modbus_read_device_identification(target)
        assert result["undecodable"] == ["vendor_name"]
        assert result["vendor"], "a flagged field is still reported, just marked"

    def test_clean_ascii_is_not_flagged(self, monkeypatch, target):
        patch_session(monkeypatch, FakeClient(FakeResponse({0x00: b"Acme"})))
        assert "undecodable" not in ops.modbus_read_device_identification(target)

    @pytest.mark.parametrize(
        ("label", "vendor"),
        [
            ("Chinese", "汇川 Inovance"),
            ("Japanese", "三菱電機"),
            ("German", "Müller GmbH"),
        ],
    )
    def test_non_ascii_vendor_names_are_clean_not_flagged(self, monkeypatch, target, label, vendor):
        """A Chinese, Japanese or German vendor name is ordinary in this market.
        An ASCII-first decoder flags every one of them, which puts a corruption
        warning on a perfectly good asset-register row and teaches the reader to
        ignore the flag entirely. Caught by putting a Chinese vendor name in the
        LIVE server fixture — every fake here had used ASCII, so the fake and the
        decoder agreed and were both wrong."""
        patch_session(monkeypatch, FakeClient(FakeResponse({0x00: vendor.encode("utf-8")})))
        result = ops.modbus_read_device_identification(target)
        assert result["vendor"] == vendor, label
        assert "undecodable" not in result, f"{label} vendor name wrongly flagged"

    def test_latin1_only_bytes_are_flagged_because_they_may_mis_render(self, monkeypatch, target):
        """latin-1 maps every byte, so it always yields something readable —
        possibly wrongly. The text is still returned; the operator is told it
        might be wrong."""
        patch_session(monkeypatch, FakeClient(FakeResponse({0x00: "Müller".encode("latin-1")})))
        result = ops.modbus_read_device_identification(target)
        assert result["vendor"] == "Müller"
        assert result["undecodable"] == ["vendor_name"]

    def test_embedded_nuls_and_padding_are_stripped(self, monkeypatch, target):
        patch_session(monkeypatch, FakeClient(FakeResponse({0x00: b"Acme\x00\x00  "})))
        assert ops.modbus_read_device_identification(target)["vendor"] == "Acme"

    def test_more_follows_is_reported_not_chased(self, monkeypatch, target):
        """Following continuations costs extra packets and identification does not
        need them, so the flag is surfaced and the round trip is not repeated."""
        client = patch_session(
            monkeypatch, FakeClient(FakeResponse({0x00: b"Acme"}, more_follows=True))
        )
        result = ops.modbus_read_device_identification(target)
        assert result["more_follows"] is True
        assert len(client.calls) == 1

    def test_a_multipart_object_is_joined(self, monkeypatch, target):
        patch_session(monkeypatch, FakeClient(FakeResponse({0x00: [b"Acme", b"Industrial"]})))
        assert ops.modbus_read_device_identification(target)["vendor"] == "Acme Industrial"

    def test_an_empty_information_set_yields_no_invented_vendor(self, monkeypatch, target):
        """A device that answers FC43 with nothing is identified as Modbus-speaking
        and nothing more. The vendor field must stay empty, not become 'Unknown'."""
        patch_session(monkeypatch, FakeClient(FakeResponse({})))
        result = ops.modbus_read_device_identification(target)
        assert result["object_count"] == 0
        assert result["vendor"] == ""
