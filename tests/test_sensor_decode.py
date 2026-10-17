"""The pure decoder: raw words / bits → engineering value, or a refusal.

HLD §16.3 rules 3–5: sentinels and non-finite values are gaps, out-of-range is
a gap, and every reading carries the accuracy band it was measured with.
"""

from __future__ import annotations

import math
import struct

import pytest

from iaiops.core.runtime.sensor import (
    InvalidReadingError,
    decode_bits,
    decode_registers,
    parse_profile,
)


def _channel(layout, **extra):
    raw = {
        "id": "t",
        "protocol": "iolink" if "bit_offset" in layout else "modbus",
        "source": "manual",
        "verified": "bench",
        "channels": [{"name": "c", "layout": layout, "unit": "u", "signal": "level", **extra}],
    }
    return parse_profile(raw).channel("c")


def _f32_words(value: float, order: str = "ABCD") -> list[int]:
    a, b, c, d = struct.pack(">f", value)
    ordered = {"ABCD": (a, b, c, d), "CDAB": (c, d, a, b)}[order]
    return [(ordered[0] << 8) | ordered[1], (ordered[2] << 8) | ordered[3]]


@pytest.mark.unit
def test_uint16_with_scale_and_unit():
    ch = _channel({"table": "input", "address": 0, "type": "uint16"}, scale=0.1)
    reading = decode_registers(ch, [12345])
    assert reading.value == pytest.approx(1234.5)
    assert reading.unit == "u"


@pytest.mark.unit
def test_offset_is_applied_after_scale():
    ch = _channel({"table": "input", "address": 0, "type": "int16"}, scale=0.1, offset=-40)
    assert decode_registers(ch, [650]).value == pytest.approx(25.0)


@pytest.mark.unit
@pytest.mark.parametrize("order", ["ABCD", "CDAB"])
def test_float32_honours_the_declared_word_order(order):
    ch = _channel({"table": "holding", "address": 0, "type": "float32", "order": order})
    assert decode_registers(ch, _f32_words(-123.25, order)).value == pytest.approx(-123.25)


@pytest.mark.unit
def test_int16_is_signed():
    ch = _channel({"table": "input", "address": 0, "type": "int16"})
    assert decode_registers(ch, [0xFFFE]).value == -2


@pytest.mark.unit
def test_sentinel_is_compared_on_the_raw_word_not_the_scaled_value():
    """0xFFFF on an int16 is -1 decoded; the datasheet names the raw word."""
    ch = _channel(
        {"table": "input", "address": 0, "type": "int16"},
        scale=0.1,
        invalid=[{"raw": 0xFFFF, "meaning": "no_target"}],
    )
    with pytest.raises(InvalidReadingError, match="no_target"):
        decode_registers(ch, [0xFFFF])
    assert decode_registers(ch, [0xFFFE]).value == pytest.approx(-0.2)


@pytest.mark.unit
def test_sentinel_on_a_32_bit_value_uses_the_declared_order():
    ch = _channel(
        {"table": "input", "address": 0, "type": "uint32", "order": "CDAB"},
        invalid=[{"raw": 0x0001FFFF, "meaning": "fault"}],
    )
    with pytest.raises(InvalidReadingError, match="fault"):
        decode_registers(ch, [0xFFFF, 0x0001])  # CDAB: low word first


@pytest.mark.unit
@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_non_finite_floats_are_never_readings(value):
    ch = _channel({"table": "input", "address": 0, "type": "float32", "order": "ABCD"})
    with pytest.raises(InvalidReadingError, match="finite"):
        decode_registers(ch, _f32_words(value))


@pytest.mark.unit
def test_out_of_range_is_a_refusal_not_a_value():
    ch = _channel({"table": "input", "address": 0, "type": "uint16"}, range=[50, 6000])
    assert decode_registers(ch, [50]).value == 50
    with pytest.raises(InvalidReadingError, match="range"):
        decode_registers(ch, [6001])


@pytest.mark.unit
def test_too_few_registers_refuses():
    ch = _channel({"table": "input", "address": 0, "type": "float32", "order": "ABCD"})
    with pytest.raises(ValueError, match="2 register"):
        decode_registers(ch, [1])


@pytest.mark.unit
def test_accuracy_band_travels_with_the_reading():
    ch = _channel(
        {"table": "input", "address": 0, "type": "int16"},
        accuracy={"full_scale": 300, "linearity_pct": 3.0, "hysteresis_pct": 3.0},
    )
    reading = decode_registers(ch, [100])
    # Worst case: the declared components add. 6 % of 300 N.
    assert reading.band == pytest.approx(18.0)
    assert (
        decode_registers(_channel({"table": "input", "address": 0, "type": "int16"}), [1]).band
        is None
    )


@pytest.mark.unit
def test_bit_offset_counts_from_the_lsb_of_the_last_octet():
    """IODD convention: bitOffset 0 is the least significant bit of the payload."""
    data = bytes([0xAA, 0x17, 0x70, 0x00, 0xFF])
    ch = _channel({"bit_offset": 16, "bit_length": 16, "type": "uint"})
    assert decode_bits(ch, data).value == 0x1770  # bits 16..31 = octets 1..2
    signed = _channel({"bit_offset": 0, "bit_length": 8, "type": "int"})
    assert decode_bits(signed, data).value == -1  # last octet 0xFF


@pytest.mark.unit
def test_bits_sub_byte_field():
    ch = _channel({"bit_offset": 2, "bit_length": 3, "type": "uint"})
    assert decode_bits(ch, bytes([0b1011_0110])).value == 0b101


@pytest.mark.unit
def test_bits_float32():
    data = struct.pack(">f", 12.5)
    ch = _channel({"bit_offset": 0, "bit_length": 32, "type": "float"})
    assert decode_bits(ch, data).value == pytest.approx(12.5)


@pytest.mark.unit
def test_bits_beyond_the_payload_refuse():
    ch = _channel({"bit_offset": 16, "bit_length": 16, "type": "uint"})
    with pytest.raises(ValueError, match="bits"):
        decode_bits(ch, b"\x00\x00")


@pytest.mark.unit
def test_bits_sentinel():
    ch = _channel(
        {"bit_offset": 0, "bit_length": 16, "type": "uint"},
        invalid=[{"raw": 0xFFFF, "meaning": "no_echo"}],
    )
    with pytest.raises(InvalidReadingError, match="no_echo"):
        decode_bits(ch, b"\xff\xff")


@pytest.mark.unit
def test_a_modbus_channel_cannot_be_decoded_as_bits_and_vice_versa():
    modbus = _channel({"table": "input", "address": 0, "type": "uint16"})
    with pytest.raises(TypeError):
        decode_bits(modbus, b"\x00\x00")
    bits = _channel({"bit_offset": 0, "bit_length": 16, "type": "uint"})
    with pytest.raises(TypeError):
        decode_registers(bits, [0])


@pytest.mark.unit
def test_a_value_exactly_on_the_range_edge_survives_float_scaling():
    """3 × 0.1 is 0.30000000000000004 in binary floating point — still in range."""
    ch = _channel({"table": "input", "address": 0, "type": "uint16"}, scale=0.1, range=[0, 0.3])
    assert decode_registers(ch, [3]).value == pytest.approx(0.3)
    with pytest.raises(InvalidReadingError):
        decode_registers(ch, [4])
