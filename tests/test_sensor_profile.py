"""Sensor profiles: decoding is data, and a profile that cannot be decoded refuses.

HLD §16.3. A profile answers one question — what the raw bytes mean — and is
validated when it is loaded, so a typo fails once at load time rather than as a
week of gaps (or worse, a week of plausible wrong values).
"""

from __future__ import annotations

import pytest

from iaiops.core.runtime.sensor import (
    BitLayout,
    ModbusLayout,
    load_profile_file,
    parse_profile,
)


def _profile(**overrides):
    base = {
        "id": "distance-example",
        "protocol": "modbus",
        "source": "datasheet",
        "verified": "待核实",
        "channels": [
            {
                "name": "distance",
                "layout": {"table": "input", "address": 0, "type": "uint16", "order": "AB"},
                "scale": 0.1,
                "unit": "mm",
                "range": [50, 6000],
                "invalid": [{"raw": 0xFFFF, "meaning": "out_of_range"}],
                "accuracy": {"full_scale": 6000, "linearity_pct": 1.0},
                "response_ms": 2,
                "signal": "level",
            }
        ],
    }
    return {**base, **overrides}


@pytest.mark.unit
def test_a_valid_profile_parses_into_frozen_objects():
    profile = parse_profile(_profile())
    channel = profile.channel("distance")
    assert isinstance(channel.layout, ModbusLayout)
    assert channel.layout.words == 1
    assert channel.unit == "mm" and channel.signal == "level"
    assert profile.verified == "待核实"
    with pytest.raises(AttributeError):
        profile.id = "x"  # type: ignore[misc]


@pytest.mark.unit
def test_iolink_bit_layout_parses():
    profile = parse_profile(
        _profile(
            protocol="iolink",
            channels=[
                {
                    "name": "distance",
                    "layout": {"bit_offset": 16, "bit_length": 16, "type": "uint"},
                    "unit": "mm",
                    "signal": "level",
                }
            ],
        )
    )
    assert isinstance(profile.channel("distance").layout, BitLayout)


@pytest.mark.unit
def test_unknown_channel_names_the_known_ones():
    profile = parse_profile(_profile())
    with pytest.raises(KeyError, match="distance"):
        profile.channel("force")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.pop("verified"), "verified"),
        (lambda p: p.update(verified="trust me"), "verified"),
        (lambda p: p.update(source="vibes"), "source"),
        (lambda p: p.update(protocol="nope"), "protocol"),
        (lambda p: p.update(channels=[]), "at least one channel"),
        (lambda p: p["channels"][0].pop("unit"), "unit"),
        (lambda p: p["channels"][0].pop("signal"), "signal"),
        (lambda p: p["channels"][0].update(signal="analog"), "signal"),
        (lambda p: p["channels"][0]["layout"].update(type="float64"), "type"),
        (lambda p: p["channels"][0]["layout"].update(table="coil"), "table"),
        (lambda p: p["channels"][0]["layout"].update(address=-1), "address"),
        (lambda p: p["channels"][0].update(range=[10, 5]), "range"),
        (lambda p: p["channels"][0].update(scale=0), "scale"),
        (lambda p: p["channels"].append(dict(p["channels"][0])), "duplicate"),
        (lambda p: p["channels"][0]["accuracy"].pop("full_scale"), "full_scale"),
    ],
)
def test_bad_profiles_are_refused_at_load(mutate, message):
    raw = _profile()
    raw["channels"] = [
        {**c, "layout": dict(c["layout"]), "accuracy": dict(c["accuracy"])} for c in raw["channels"]
    ]
    mutate(raw)
    with pytest.raises(ValueError, match=message):
        parse_profile(raw)


@pytest.mark.unit
def test_a_32_bit_modbus_type_needs_an_explicit_word_order():
    """Guessing the word order of a float32 gives a plausible wrong number."""
    raw = _profile()
    raw["channels"][0]["layout"] = {"table": "input", "address": 0, "type": "float32"}
    with pytest.raises(ValueError, match="order"):
        parse_profile(raw)


@pytest.mark.unit
def test_profile_loads_from_yaml(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text(
        "id: x\nprotocol: modbus\nsource: manual\nverified: bench\nchannels:\n"
        "  - name: force\n    layout: {table: holding, address: 4, type: float32, order: CDAB}\n"
        "    unit: N\n    signal: level\n",
        "utf-8",
    )
    profile = load_profile_file(path)
    assert profile.channel("force").layout.words == 2


@pytest.mark.unit
def test_a_yaml_file_that_is_not_a_mapping_is_refused(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("- just\n- a list\n", "utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_profile_file(path)
