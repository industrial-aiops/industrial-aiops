"""Raw register words / process-data bits → an engineering value, or a refusal.

Pure: no device, no I/O. The order of checks is the point (HLD §16.3):

1. **Sentinels on the raw field**, before any scaling. A datasheet says "0xFFFF
   means no target"; on an int16 that word decodes to -1, so comparing after
   decoding would let the sentinel through as a measurement.
2. **Non-finite floats** are never readings.
3. **Scale and offset**, then **range**. A value outside the sensor's declared
   range is saturation or a fault, not a measurement.

Every refusal is :class:`InvalidReadingError`: the device answered, and what it sent is
not a value. Callers record it as a gap — the same rendering as a stale MQTT
point (§15.3) — never as a number.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from iaiops.core.runtime.sensor.profile import BitLayout, Channel, ModbusLayout


class InvalidReadingError(ValueError):
    """The device answered, and what it sent is not a measurement."""


@dataclass(frozen=True)
class Reading:
    """A decoded value with its unit and the accuracy band it was measured with."""

    value: float | int
    unit: str
    band: float | None = None


def _raw_unsigned(registers: list[int], layout: ModbusLayout) -> int:
    from iaiops.connectors.modbus.byteorder import decode_value

    unsigned = "uint16" if layout.words == 1 else "uint32"
    return int(decode_value(registers, unsigned, layout.order))


def decode_registers(channel: Channel, registers: list[int]) -> Reading:
    """Decode a Modbus channel from the words read at its address."""
    layout = channel.layout
    if not isinstance(layout, ModbusLayout):
        raise TypeError(f"Channel {channel.name!r} is not a Modbus channel.")
    from iaiops.connectors.modbus.byteorder import decode_value

    raw = _raw_unsigned(registers, layout)
    _check_sentinel(channel, raw)
    return _finish(channel, decode_value(registers, layout.value_type, layout.order))


def decode_bits(channel: Channel, data: bytes) -> Reading:
    """Decode an IO-Link channel from a process-data image."""
    layout = channel.layout
    if not isinstance(layout, BitLayout):
        raise TypeError(f"Channel {channel.name!r} is not a bit-field channel.")
    available = len(data) * 8
    if layout.bit_offset + layout.bit_length > available:
        raise ValueError(
            f"Channel {channel.name!r} needs bits {layout.bit_offset}.."
            f"{layout.bit_offset + layout.bit_length - 1}; the process data has {available} bits."
        )
    raw = (int.from_bytes(data, "big") >> layout.bit_offset) & ((1 << layout.bit_length) - 1)
    _check_sentinel(channel, raw)
    if layout.value_type == "float":
        value: float | int = struct.unpack(">f", raw.to_bytes(4, "big"))[0]
    elif layout.value_type == "int" and raw >> (layout.bit_length - 1):
        value = raw - (1 << layout.bit_length)
    else:
        value = raw
    return _finish(channel, value)


def _check_sentinel(channel: Channel, raw: int) -> None:
    for sentinel in channel.invalid:
        if sentinel.raw == raw:
            raise InvalidReadingError(
                f"{channel.name}: device sent 0x{raw:X} ({sentinel.meaning}) — not a measurement."
            )


def _finish(channel: Channel, value: float | int) -> Reading:
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidReadingError(f"{channel.name}: device sent a non-finite value ({value}).")
    if channel.scale != 1.0 or channel.offset != 0.0:
        value = value * channel.scale + channel.offset
    if channel.range is not None:
        low, high = channel.range
        if not low <= value <= high:
            raise InvalidReadingError(
                f"{channel.name}: {value} {channel.unit} is outside the sensor's range "
                f"[{low}, {high}] — saturation or a fault, not a measurement."
            )
    band = channel.accuracy.band if channel.accuracy is not None else None
    return Reading(value=value, unit=channel.unit, band=band)
