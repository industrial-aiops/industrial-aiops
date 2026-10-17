"""Defects an adversarial review of #249 found — each a plausible wrong value
or a silent drop.

1. The identity cache was keyed on agent_url; two masters configured by host
   alone shared one key, so a foreign sensor on the second was decoded.
2. A process-data image of a different length (another PD variant, same device
   id) decoded silently with every field shifted.
3. A simple (non-record) PD item lost its gradient/unit with no note.
4. Any Float32T item made the whole IODD import fail (it has no bitLength).
5. Named values inside the ValueRange were dropped with no note.
6. Duplicate / non-integer port keys were accepted.
7. A directory or an unhashable value in a profile escaped load_config's
   per-endpoint error report.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import iaiops.connectors.iolink.ops as iolink_ops
from iaiops.connectors.iolink import points as iolink_points
from iaiops.core.runtime.sensor import InvalidReadingError, decode_bits, parse_profile
from iaiops.core.runtime.sensor.iodd import import_iodd
from iaiops.core.runtime.session_factory import OTNoReadingError

pytestmark = pytest.mark.unit

FIXTURE = (Path(__file__).parent / "fixtures" / "iodd" / "distance_sensor.xml").read_text("utf-8")


def _iolink_profile(**extra):
    return parse_profile(
        {
            "id": "p",
            "protocol": "iolink",
            "source": "iodd",
            "verified": "待核实",
            "match": {"vendor_id": 888, "device_id": 4660},
            "channels": [
                {
                    "name": "d",
                    "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
                    "unit": "mm",
                    "signal": "level",
                }
            ],
            **extra,
        }
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    iolink_points.clear_identity_cache()
    yield
    iolink_points.clear_identity_cache()


def test_1_masters_configured_by_host_do_not_share_an_identity_check(monkeypatch):
    identities = {"10.0.0.1": (888, 4660), "10.0.0.2": (999, 1)}
    monkeypatch.setattr(
        iolink_ops,
        "device_info",
        lambda t, port: {
            "device": dict(zip(("vendorid", "deviceid"), identities[t.host], strict=True))
        },
    )
    monkeypatch.setattr(iolink_ops, "read_pdin", lambda t, port: {"bytes": [0, 1, 0, 0]})
    profile = _iolink_profile()
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: profile)

    def master(host):
        return SimpleNamespace(
            name=host,
            protocol="iolink",
            agent_url="",
            host=host,
            port=0,
            port_profiles=((2, "p.yaml"),),
        )

    iolink_points.read_value(master("10.0.0.1"), "port2/d")
    with pytest.raises(OTNoReadingError, match="999"):
        iolink_points.read_value(master("10.0.0.2"), "port2/d")


def test_1_a_failed_read_forgets_the_identity(monkeypatch):
    calls = {"identity": 0}

    def device_info(t, port):
        calls["identity"] += 1
        return {"device": {"vendorid": 888, "deviceid": 4660}}

    pdin = {"data": [0, 1, 0, 0]}
    monkeypatch.setattr(iolink_ops, "device_info", device_info)

    def read_pdin(t, port):
        if pdin["data"] is None:
            raise OSError("port disconnected")
        return {"bytes": pdin["data"]}

    monkeypatch.setattr(iolink_ops, "read_pdin", read_pdin)
    profile = _iolink_profile()
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: profile)
    target = SimpleNamespace(
        name="m", protocol="iolink", agent_url="http://m", port_profiles=((2, "p"),)
    )
    iolink_points.read_value(target, "port2/d")
    pdin["data"] = None
    with pytest.raises(OSError):
        iolink_points.read_value(target, "port2/d")
    pdin["data"] = [0, 1, 0, 0]
    iolink_points.read_value(target, "port2/d")
    assert calls["identity"] == 2  # re-checked after the disconnect


def test_2_a_process_data_image_of_another_length_is_refused():
    channel = _iolink_profile(pd_bits=32).channel("d")
    profile = _iolink_profile(pd_bits=32)
    assert profile.pd_bits == 32
    with pytest.raises(InvalidReadingError, match="48 bits"):
        decode_bits(channel, bytes(6), expected_bits=profile.pd_bits)
    assert decode_bits(channel, bytes([0, 7, 0, 0]), expected_bits=32).value == 7


def test_2_the_importer_carries_the_pd_length():
    assert import_iodd(FIXTURE).profile["pd_bits"] == 32


def _simple_pd(info_subindex: str | None) -> str:
    record_start = FIXTURE.index('<Datatype xsi:type="RecordT"')
    record_end = FIXTURE.index("</Datatype>", record_start) + len("</Datatype>")
    simple = (
        FIXTURE[:record_start] + '<DatatypeRef datatypeId="DT_Distance"/>' + FIXTURE[record_end:]
    )
    simple = simple.replace('bitLength="32"', 'bitLength="16"', 1)
    if info_subindex is None:
        return simple.replace('subindex="1" gradient', 'subindex="9" gradient')
    return simple.replace('subindex="1" gradient', f'subindex="{info_subindex}" gradient')


def test_3_a_simple_pd_item_keeps_its_gradient_and_unit():
    channel = import_iodd(_simple_pd("0")).profile["channels"][0]
    assert channel["scale"] == pytest.approx(0.1)
    assert "1013" in channel["unit"]


def test_3_unmatched_ui_info_is_noted_not_dropped():
    draft = import_iodd(_simple_pd(None))
    assert any("scale" in note and "not" in note for note in draft.notes)


def test_4_float32_items_import():
    text = (
        FIXTURE.replace(
            '<SimpleDatatype xsi:type="IntegerT" bitLength="8">',
            '<SimpleDatatype xsi:type="Float32T">',
        )
        .replace('bitOffset="8"', 'bitOffset="32"')
        .replace(
            '<ProcessDataIn id="PD_In" bitLength="32">', '<ProcessDataIn id="PD_In" bitLength="64">'
        )
    )
    channels = {c["name"]: c for c in import_iodd(text).profile["channels"]}
    assert channels["device_temperature"]["layout"] == {
        "bit_offset": 32,
        "bit_length": 32,
        "type": "float",
    }


def test_5_named_values_inside_the_range_are_noted():
    notes = import_iodd(FIXTURE).notes
    assert any("Hundred" in n or "inside the range" in n for n in notes)


@pytest.mark.parametrize(
    ("ports", "message"),
    [
        ({2: "a.yaml", "2": "b.yaml"}, "twice"),
        ({3.9: "a.yaml"}, "port"),
        ({True: "a.yaml"}, "port"),
    ],
)
def test_6_bad_port_keys_are_refused(ports, message):
    from iaiops.core.runtime.sensor.binding import parse_port_profiles

    with pytest.raises(ValueError, match=message):
        parse_port_profiles(ports, "m")


def _config(tmp_path, endpoint):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"endpoints": [endpoint]}), "utf-8")
    return path


def test_7_a_directory_as_profile_is_a_config_problem(tmp_path):
    from iaiops.core.runtime.config import load_config

    (tmp_path / "profdir").mkdir()
    path = _config(
        tmp_path, {"name": "cell", "protocol": "modbus", "host": "h", "sensor_profile": "profdir"}
    )
    with pytest.raises(ValueError, match="cell"):
        load_config(path)


def test_7_an_unhashable_type_is_a_profile_error():
    with pytest.raises(ValueError, match="type"):
        parse_profile(
            {
                "id": "x",
                "protocol": "modbus",
                "source": "manual",
                "verified": "bench",
                "channels": [
                    {
                        "name": "c",
                        "layout": {"table": "input", "address": 0, "type": ["float32"]},
                        "unit": "u",
                        "signal": "level",
                    }
                ],
            }
        )


def test_readiness_says_not_applicable_without_modbus_or_iolink():
    from iaiops.core.readiness.sensors import decodable_points_req, sensor_point_facts

    opcua = SimpleNamespace(name="u", protocol="opcua", tags=(SimpleNamespace(ref="x"),))
    req = decodable_points_req({"sensor_points": sensor_point_facts((opcua,))})
    assert req.met and "not applicable" in req.detail


def test_2_the_read_path_enforces_pd_bits(monkeypatch):
    profile = _iolink_profile(pd_bits=32)
    monkeypatch.setattr("iaiops.core.runtime.sensor.binding.cached_profile", lambda path: profile)
    monkeypatch.setattr(
        iolink_ops, "device_info", lambda t, port: {"device": {"vendorid": 888, "deviceid": 4660}}
    )
    monkeypatch.setattr(iolink_ops, "read_pdin", lambda t, port: {"bytes": [0, 0, 0, 7, 0, 0]})
    target = SimpleNamespace(
        name="m", protocol="iolink", agent_url="http://m", port_profiles=((2, "p"),)
    )
    with pytest.raises(InvalidReadingError, match="48 bits"):
        iolink_points.read_value(target, "port2/d")


def test_2_a_channel_past_pd_bits_is_refused_at_load():
    with pytest.raises(ValueError, match="past pd_bits"):
        _iolink_profile(pd_bits=24)


def test_a_profile_edited_to_another_protocol_is_refused_at_read(monkeypatch):
    from iaiops.core.runtime.sensor.binding import endpoint_profile

    monkeypatch.setattr(
        "iaiops.core.runtime.sensor.binding.cached_profile", lambda path: _iolink_profile()
    )
    modbus = SimpleNamespace(name="cell", protocol="modbus", sensor_profile="force.yaml")
    with pytest.raises(ValueError, match="now a iolink profile"):
        endpoint_profile(modbus)


def test_lab_a_swap_without_a_disconnect_is_caught_within_seconds():
    """Found on the lab LAN (2026-10-17), not by any unit test.

    A sentinel read forgot the cached identity, the very next read re-verified
    it, and a sensor swapped 13 s later (no disconnect in between) was decoded
    for its whole 14 s with the 30 s cache — 14 s of a foreign device stored as
    the real one. A swap WITH a disconnect is caught by forget-on-failure; the
    window only matters for one without, so it must be short.
    """
    assert iolink_points.IDENTITY_TTL_S <= 5.0
