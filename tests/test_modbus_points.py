"""Typed Modbus points (HLD §16.5 S2, D48).

Before this, every collected Modbus point was ONE holding register read as a
16-bit word: a float32 force value was stored as half a float — a plausible
integer, never an error. A typed point names its table, type, word order and
scale in the ref itself, so every read path (collect, monitor, read_ref) gets the
same decoded value. A bare address keeps its old meaning for compatibility.
"""

from __future__ import annotations

import struct

import pytest

from iaiops.connectors.modbus.points import parse_point, read_point_value
from iaiops.core.runtime.sensor import InvalidReadingError


def _f32(value: float) -> list[int]:
    a, b, c, d = struct.pack(">f", value)
    return [(a << 8) | b, (c << 8) | d]


@pytest.mark.unit
def test_bare_address_is_the_legacy_point():
    point = parse_point("12")
    assert point.legacy and point.table == "holding" and point.address == 12
    assert point.words == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ref", "table", "address", "vtype", "order", "scale"),
    [
        ("hr:100", "holding", 100, "uint16", "AB", 1.0),
        ("ir:7:int16", "input", 7, "int16", "AB", 1.0),
        ("ir:7:int16*0.1", "input", 7, "int16", "AB", 0.1),
        ("hr:0:float32:CDAB", "holding", 0, "float32", "CDAB", 1.0),
        ("IR:3:uint32:ABCD*0.001", "input", 3, "uint32", "ABCD", 0.001),
        (" hr:5:int16:BA ", "holding", 5, "int16", "BA", 1.0),
    ],
)
def test_typed_points_parse(ref, table, address, vtype, order, scale):
    point = parse_point(ref)
    assert not point.legacy
    assert (point.table, point.address, point.value_type, point.order, point.scale) == (
        table,
        address,
        vtype,
        order,
        scale,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ref", "message"),
    [
        ("hr:0:float32", "order"),  # 32-bit needs an explicit word order
        ("xx:0", "table"),
        ("hr:-1", "address"),
        ("hr:65536", "address"),
        ("hr:abc", "address"),
        ("hr:0:float64:ABCD", "type"),
        ("hr:0:int16:ABCD", "order"),
        ("hr:0:uint16*0", "scale"),
        ("hr:0:uint16*x", "scale"),
        ("hr:0:uint16:AB:extra", "ref"),
        ("", "ref"),
        ("tank_level", "ref"),
    ],
)
def test_bad_points_refuse_with_the_grammar(ref, message):
    with pytest.raises(ValueError, match=message):
        parse_point(ref)


class _Reader:
    """Records which table/address/count was asked for and returns fixed words."""

    def __init__(self, words: list[int]) -> None:
        self.words = words
        self.calls: list[tuple[str, int, int]] = []

    def __call__(self, table: str, address: int, count: int) -> list[int]:
        self.calls.append((table, address, count))
        return self.words[:count]


@pytest.mark.unit
def test_float32_point_reads_two_words_and_decodes():
    read = _Reader(_f32(-42.5))
    assert read_point_value(read, "ir:10:float32:ABCD") == pytest.approx(-42.5)
    assert read.calls == [("input", 10, 2)]


@pytest.mark.unit
def test_scaled_int16_point():
    read = _Reader([0xFFF6])  # -10
    assert read_point_value(read, "hr:3:int16*0.1") == pytest.approx(-1.0)


@pytest.mark.unit
def test_legacy_point_reads_one_holding_word_unchanged():
    read = _Reader([0xFFFF, 0x1234])
    assert read_point_value(read, "5") == 0xFFFF
    assert read.calls == [("holding", 5, 1)]


@pytest.mark.unit
def test_non_finite_float_is_a_refusal():
    read = _Reader(_f32(float("nan")))
    with pytest.raises(InvalidReadingError):
        read_point_value(read, "ir:0:float32:ABCD")


@pytest.mark.unit
def test_short_read_refuses():
    read = _Reader([1])
    with pytest.raises(ValueError, match="2 register"):
        read_point_value(read, "ir:0:float32:ABCD")
