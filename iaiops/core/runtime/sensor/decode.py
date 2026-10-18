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

from iaiops.core.runtime.sensor.profile import BitLayout, Channel, ModbusLayout, SwitchLayout


class InvalidReadingError(ValueError):
    """The device answered, and what it sent is not a measurement."""


class DescriptionMismatchError(InvalidReadingError):
    """The device answered, and its answer contradicts the sensor's description.

    Another device identity on the port, another process-data length: the device
    may be perfectly healthy — the description (or which sensor is fitted) is
    what is wrong. Still a gap, never a value; but diagnosis must name the
    configuration, not send someone to the field (#249 follow-up 2).
    """


class DescriptionUnusableError(ValueError):
    """The point's sensor description cannot be applied at all — touches no device.

    No profile bound, no such channel, a profile file that is gone or was edited
    to another protocol. A configuration cause, not a wrong address on the device.
    """


def is_description_cause(exc: BaseException) -> bool:
    """True when ``exc`` says the sensor description, not the site, is the cause."""
    return isinstance(exc, (DescriptionMismatchError, DescriptionUnusableError))


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
    if len(registers) < layout.words:
        # The device answered, with less than the value needs: a gap, not a
        # connection fault that would tear down a held session.
        raise InvalidReadingError(
            f"{channel.name}: {layout.value_type} needs {layout.words} register(s); "
            f"the device returned {len(registers)}."
        )
    raw = _raw_unsigned(registers, layout)
    _check_sentinel(channel, raw)
    return _finish(channel, _typed(raw, layout))


def _typed(raw: int, layout: ModbusLayout) -> float | int:
    """The ordered raw field as its declared type — unrounded.

    ``byteorder.decode_value`` rounds float32 to 6 decimals for display, which
    turns a 3.2e-9 reading into 0.0; a measurement must not go through it.
    """
    width = layout.words * 16
    if layout.value_type == "float32":
        return struct.unpack(">f", raw.to_bytes(4, "big"))[0]
    if layout.value_type.startswith("int") and raw >> (width - 1):
        return raw - (1 << width)
    return raw


def decode_bits(channel: Channel, data: bytes, expected_bits: int | None = None) -> Reading:
    """Decode an IO-Link channel from a process-data image.

    ``expected_bits`` is the profile's ``pd_bits``. Offsets count from the end of
    the image, so an image of any other length would shift every field: refused.
    """
    layout = channel.layout
    if not isinstance(layout, BitLayout):
        raise TypeError(f"Channel {channel.name!r} is not a bit-field channel.")
    available = len(data) * 8
    if not available:
        # Nothing at all is "no process data" (no device, no PD yet), not another
        # layout: calling it a description mismatch would blame the profile.
        raise InvalidReadingError(f"{channel.name}: the device sent no process data.")
    if expected_bits is not None and available != expected_bits:
        raise DescriptionMismatchError(
            f"{channel.name}: the device sent {available} bits of process data; the profile "
            f"was written for {expected_bits}. Another process-data layout is active — "
            "decoding it with this profile would shift every field."
        )
    if layout.bit_offset + layout.bit_length > available:
        # The device answered with less than the field needs: not a measurement
        # (a gap), not a connection fault.
        raise InvalidReadingError(
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
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidReadingError(f"{channel.name}: scaling gave a non-finite value ({value}).")
    if channel.range is not None:
        low, high = channel.range
        # Scaling happens in binary floating point (3 × 0.1 = 0.30000000000000004),
        # so the edge is compared with a tolerance far below any sensor's resolution.
        slack = 1e-9 * max(1.0, abs(low), abs(high))
        if not low - slack <= value <= high + slack:
            raise InvalidReadingError(
                f"{channel.name}: {value} {channel.unit} is outside the sensor's range "
                f"[{low}, {high}] — saturation or a fault, not a measurement."
            )
    band = channel.accuracy.band if channel.accuracy is not None else None
    return Reading(value=value, unit=channel.unit, band=band)


def decode_switch(channel: Channel, bits: list[int]) -> Reading:
    """A switching sensor's bit → 1 if actuated, 0 if not (HLD §17.5b, D60).

    "Actuated" follows the declared active level: on a normally-closed switch
    (``active: low``) a 0 on the wire means the switch is actuated.
    """
    layout = channel.layout
    if not isinstance(layout, SwitchLayout):
        raise TypeError(f"Channel {channel.name!r} is not a switching channel.")
    if not bits:
        raise InvalidReadingError(f"{channel.name}: the device answered with no bit.")
    level = 1 if bits[0] else 0
    actuated = level if layout.active == "high" else 1 - level
    return Reading(value=actuated, unit=channel.unit)
