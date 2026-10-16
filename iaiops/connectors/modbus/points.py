"""Typed Modbus points: the ref names the table, type, word order and scale.

HLD §16.5 S2 / D48. A Modbus register has no name and no type, so until now a
collected point was ``int(ref)`` — one holding register as a 16-bit word. A
float32 occupies two registers; collecting it stored the first half as an
ordinary-looking integer.

Grammar (case-insensitive table, otherwise exact)::

    <table>:<address>[:<type>[:<order>]][*<scale>]

    table   hr (holding, FC03) | ir (input, FC04)
    type    uint16 (default) | int16 | uint32 | int32 | float32
    order   AB (default for 16-bit) | BA ; ABCD | DCBA | BADC | CDAB — REQUIRED for 32-bit
    scale   a non-zero number multiplied into the value

    ir:0:float32:CDAB      hr:12:int16*0.1      hr:40

A bare address (``"40"``) is the legacy point and keeps its exact old meaning —
one holding register, unsigned — so existing configs and stored series do not
change under anyone. It is *untyped*: nothing about it says it is a uint16.

Decoding goes through the sensor decoder (``iaiops.core.runtime.sensor``), the
same one profiles use, so a typed point and a profile channel cannot disagree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from iaiops.core.runtime.sensor import Channel, SensorProfile, decode_registers, modbus_layout

_TABLES = {"hr": "holding", "ir": "input"}
GRAMMAR = (
    "<hr|ir>:<address>[:<type>[:<order>]][*<scale>], e.g. ir:0:float32:CDAB or hr:12:int16*0.1"
)

#: Reads ``count`` words of ``table`` starting at ``address``.
WordReader = Callable[[str, int, int], list[int]]


@dataclass(frozen=True)
class ModbusPoint:
    """A parsed ref. ``legacy`` = a bare address with its pre-typed meaning."""

    table: str
    address: int
    value_type: str = "uint16"
    order: str = "AB"
    scale: float = 1.0
    legacy: bool = False

    @property
    def words(self) -> int:
        return 2 if self.value_type in ("uint32", "int32", "float32") else 1

    def channel(self, name: str) -> Channel:
        layout = modbus_layout(self.table, self.address, self.value_type, self.order, name)
        return Channel(name=name, layout=layout, unit="", signal="level", scale=self.scale)


def _scale(text: str, ref: str) -> float:
    try:
        scale = float(text)
    except ValueError as exc:
        raise ValueError(f"Modbus point {ref!r}: scale {text!r} is not a number.") from exc
    if scale == 0:
        raise ValueError(f"Modbus point {ref!r}: scale 0 would turn every reading into 0.")
    return scale


def _address(text: str, ref: str) -> int:
    if not text.isdigit():
        raise ValueError(f"Modbus point {ref!r}: address {text!r} is not a register number.")
    return int(text)


def parse_point(ref: str) -> ModbusPoint:
    """Parse a Modbus ref; raise ``ValueError`` naming the grammar on any defect."""
    text = str(ref or "").strip()
    if text.isdigit():
        address = int(text)
        if address > 0xFFFF:
            raise ValueError(f"Modbus point {ref!r}: address must be 0..65535.")
        return ModbusPoint(table="holding", address=address, legacy=True)
    body, _, scale_text = text.partition("*")
    parts = body.split(":")
    if len(parts) < 2 or len(parts) > 4:
        raise ValueError(f"Modbus point ref {ref!r} is not in the grammar {GRAMMAR}.")
    table = _TABLES.get(parts[0].lower())
    if table is None:
        raise ValueError(f"Modbus point {ref!r}: table {parts[0]!r} must be hr or ir ({GRAMMAR}).")
    value_type = parts[2] if len(parts) > 2 else "uint16"
    order = parts[3] if len(parts) > 3 else None
    layout = modbus_layout(
        table, _address(parts[1], ref), value_type, order, f"Modbus point {ref!r}"
    )
    return ModbusPoint(
        table=layout.table,
        address=layout.address,
        value_type=layout.value_type,
        order=layout.order,
        scale=_scale(scale_text, ref) if scale_text else 1.0,
    )


def read_point_value(read_words: WordReader, ref: str) -> float | int | None:
    """Read and decode one point. Raises ``InvalidReadingError`` for a non-measurement."""
    point = parse_point(ref)
    words = list(read_words(point.table, point.address, point.words))
    if point.legacy:
        return words[0] if words else None
    return decode_registers(point.channel(str(ref).strip()), words).value


#: A ref naming a channel of the endpoint's sensor profile (HLD §16.5 S3).
CHANNEL_PREFIX = "ch:"


def is_channel_ref(ref: str) -> bool:
    return str(ref or "").strip().startswith(CHANNEL_PREFIX)


def profile_channel(ref: str, profile: SensorProfile | None) -> Channel:
    """Resolve ``ch:<name>`` through the endpoint's profile, or refuse."""
    name = str(ref).strip()[len(CHANNEL_PREFIX) :]
    if profile is None:
        raise ValueError(
            f"Modbus ref {ref!r} names a profile channel, but this endpoint has no "
            "sensor_profile. Add `sensor_profile: <file>` to it in config.yaml, or use "
            f"a typed point ({GRAMMAR})."
        )
    try:
        return profile.channel(name)
    except KeyError as exc:
        raise ValueError(str(exc.args[0])) from exc


def check_ref(ref: str, profile: SensorProfile | None) -> None:
    """Raise ``ValueError`` if ``ref`` cannot be read on this endpoint — touches nothing."""
    if is_channel_ref(ref):
        profile_channel(ref, profile)
    else:
        parse_point(ref)


def read_ref_value(
    read_words: WordReader, ref: str, profile: SensorProfile | None = None
) -> float | int | None:
    """Read a bare, typed or profile-channel ref. Raises ``InvalidReadingError``
    when the device sent something that is not a measurement."""
    if not is_channel_ref(ref):
        return read_point_value(read_words, ref)
    channel = profile_channel(ref, profile)
    layout = channel.layout
    words = list(read_words(layout.table, layout.address, layout.words))
    return decode_registers(channel, words).value


__all__ = [
    "CHANNEL_PREFIX",
    "GRAMMAR",
    "ModbusPoint",
    "check_ref",
    "is_channel_ref",
    "parse_point",
    "profile_channel",
    "read_point_value",
    "read_ref_value",
]
