"""Sensor layer: decoding as data (HLD §16).

``profile`` validates what a sensor's raw bytes mean; ``decode`` turns raw words
or bits into a value — or refuses with :class:`InvalidReadingError`, which callers
record as a gap.
"""

from __future__ import annotations

from iaiops.core.runtime.sensor.decode import (
    InvalidReadingError,
    Reading,
    decode_bits,
    decode_registers,
    decode_switch,
)
from iaiops.core.runtime.sensor.profile import (
    Accuracy,
    BitLayout,
    Channel,
    ModbusLayout,
    SensorProfile,
    Sentinel,
    SwitchLayout,
    load_profile_file,
    modbus_layout,
    parse_profile,
    profile_summary,
    switch_layout,
)

__all__ = [
    "Accuracy",
    "BitLayout",
    "Channel",
    "InvalidReadingError",
    "ModbusLayout",
    "Reading",
    "SensorProfile",
    "Sentinel",
    "SwitchLayout",
    "decode_bits",
    "decode_registers",
    "decode_switch",
    "load_profile_file",
    "modbus_layout",
    "parse_profile",
    "profile_summary",
    "switch_layout",
]
