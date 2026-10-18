"""Sensor profiles: what a sensor's raw bytes mean, as validated data (HLD §16.3).

A profile answers exactly one question — *how to decode* — and never what a
channel is *for*. "This channel is millimetres" belongs here; "this channel is
the production counter" does not, and never will (D16, D43): decoding can be
checked against a device, a semantic role cannot.

Everything is validated when the profile is parsed. A typo in a word order must
fail once, at load time — not as a week of gaps, and certainly not as a week of
plausible wrong numbers.

The objects are frozen; a profile is read, never edited in place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROTOCOLS = ("modbus", "iolink")
#: Where a profile came from. It travels into reports with ``verified``.
SOURCES = ("iodd", "datasheet", "manual")
#: How far the decoding has been checked against a real device.
VERIFIED = ("待核实", "bench", "field")
#: Decides how a channel can honestly be collected (HLD §16.4).
SIGNALS = ("level", "counter", "event", "waveform")

MODBUS_TABLES = ("holding", "input")
#: Single-bit Modbus tables a switching sensor (NPN / PNP / dry contact) lands in
#: through a DI module: discrete inputs (FC02) and coils (FC01) — HLD §17.5b.
SWITCH_TABLES = ("discrete", "coil")
ACTIVE_LEVELS = ("high", "low")
#: A switch is a state or an event — never a counter (D45 / D61) or a waveform.
SWITCH_SIGNALS = ("level", "event")
#: Modbus value type → registers it spans.
MODBUS_WIDTHS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}
MODBUS_ORDERS = {1: ("AB", "BA"), 2: ("ABCD", "DCBA", "BADC", "CDAB")}
#: The Modbus specification's own order for a single register. A 32-bit order has
#: no such default: vendors split on it, and a wrong guess decodes to a plausible
#: number. It must be stated.
DEFAULT_ORDER_16 = "AB"
MAX_ADDRESS = 0xFFFF

BIT_TYPES = ("uint", "int", "float")
#: IO-Link process data is at most 32 octets (IO-Link 1.1).
MAX_PD_BITS = 32 * 8


@dataclass(frozen=True)
class SwitchLayout:
    """A switching sensor's bit (HLD §17.5b). ``active`` is the level that means
    "actuated" — required, because a normally-closed switch reads 0 when a part
    is present (D60)."""

    table: str
    address: int
    active: str


@dataclass(frozen=True)
class ModbusLayout:
    """A value in a Modbus register table."""

    table: str
    address: int
    value_type: str
    order: str

    @property
    def words(self) -> int:
        return MODBUS_WIDTHS[self.value_type]


@dataclass(frozen=True)
class BitLayout:
    """A field in an IO-Link process-data image.

    ``bit_offset`` follows the IODD convention: bit 0 is the least significant bit
    of the LAST octet, so an IODD ``RecordItem`` offset can be copied unchanged.
    """

    bit_offset: int
    bit_length: int
    value_type: str


@dataclass(frozen=True)
class Sentinel:
    """A raw value the device sends instead of a measurement."""

    raw: int
    meaning: str


@dataclass(frozen=True)
class Accuracy:
    """Declared error components, each as % of ``full_scale``."""

    full_scale: float
    linearity_pct: float = 0.0
    hysteresis_pct: float = 0.0
    crosstalk_pct: float = 0.0

    @property
    def band(self) -> float:
        """Worst case: the declared components add. A difference inside it is noise."""
        total = self.linearity_pct + self.hysteresis_pct + self.crosstalk_pct
        return abs(self.full_scale) * total / 100.0


@dataclass(frozen=True)
class Channel:
    """One decoded quantity."""

    name: str
    layout: ModbusLayout | BitLayout | SwitchLayout
    unit: str
    signal: str
    scale: float = 1.0
    offset: float = 0.0
    range: tuple[float, float] | None = None
    invalid: tuple[Sentinel, ...] = ()
    accuracy: Accuracy | None = None
    response_ms: float | None = None


@dataclass(frozen=True)
class SensorProfile:
    """A sensor's channels, with where the decoding came from and how far it is checked."""

    id: str
    protocol: str
    source: str
    verified: str
    channels: tuple[Channel, ...]
    #: IO-Link only: the device this profile was written for. When set, the
    #: device on the port is checked before anything is decoded with it.
    vendor_id: int | None = None
    device_id: int | None = None
    #: IO-Link only: the process-data-in length the layout was written for. Bit
    #: offsets count from the END of the image, so an image of another length
    #: (another PD variant, same device id) shifts every field — refused.
    pd_bits: int | None = None

    def channel(self, name: str) -> Channel:
        for candidate in self.channels:
            if candidate.name == name:
                return candidate
        known = ", ".join(c.name for c in self.channels)
        raise KeyError(f"Profile {self.id!r} has no channel {name!r}. Channels: {known}.")


# ── parsing ──────────────────────────────────────────────────────────────────


def _choice(raw: dict, key: str, allowed: tuple[str, ...], where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{where}: {key} must be one of {', '.join(allowed)}; got {value!r}.")
    return str(value)


def _text(raw: dict, key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key} is required (a non-empty string).")
    return value.strip()


def _int(value: Any, key: str, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{where}: {key} must be an integer in {low}..{high}; got {value!r}.")
    return value


def _number(value: Any, key: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where}: {key} must be a number; got {value!r}.")
    number = float(value)
    if not math.isfinite(number):
        # YAML's .nan / .inf: a NaN range refuses every reading, a NaN scale
        # turns every reading into NaN.
        raise ValueError(f"{where}: {key} must be a finite number; got {value!r}.")
    return number


def modbus_layout(
    table: str, address: Any, value_type: str, order: str | None, where: str
) -> ModbusLayout:
    """Validate a Modbus layout. Shared with the typed-point grammar."""
    if not isinstance(table, str) or table not in MODBUS_TABLES:
        raise ValueError(
            f"{where}: table must be one of {', '.join(MODBUS_TABLES)}; got {table!r}."
        )
    address = _int(address, "address", where, 0, MAX_ADDRESS)
    if not isinstance(value_type, str) or value_type not in MODBUS_WIDTHS:
        raise ValueError(
            f"{where}: type must be one of {', '.join(MODBUS_WIDTHS)}; got {value_type!r}."
        )
    width = MODBUS_WIDTHS[value_type]
    if order is None:
        if width != 1:
            raise ValueError(
                f"{where}: a {value_type} spans two registers and needs an explicit word "
                f"order ({', '.join(MODBUS_ORDERS[2])}) — vendors differ, and a wrong guess "
                "decodes to a plausible number. `modbus detect-byte-order` can find it."
            )
        order = DEFAULT_ORDER_16
    if not isinstance(order, str) or order not in MODBUS_ORDERS[width]:
        raise ValueError(
            f"{where}: order {order!r} does not fit a {value_type}; use one of "
            f"{', '.join(MODBUS_ORDERS[width])}."
        )
    return ModbusLayout(table=table, address=address, value_type=value_type, order=order)


def _bit_layout(raw: dict, where: str) -> BitLayout:
    offset = _int(raw.get("bit_offset"), "bit_offset", where, 0, MAX_PD_BITS - 1)
    length = _int(raw.get("bit_length"), "bit_length", where, 1, 64)
    value_type = _choice(raw, "type", BIT_TYPES, where)
    if value_type == "float" and length != 32:
        raise ValueError(f"{where}: a float field is 32 bits; got bit_length {length}.")
    if offset + length > MAX_PD_BITS:
        raise ValueError(f"{where}: field ends past the {MAX_PD_BITS}-bit process-data limit.")
    return BitLayout(bit_offset=offset, bit_length=length, value_type=value_type)


def switch_layout(table: str, address: Any, active: Any, where: str) -> SwitchLayout:
    """Validate a switching-sensor bit. Shared with the ``di:`` / ``co:`` grammar."""
    if not isinstance(active, str) or active not in ACTIVE_LEVELS:
        raise ValueError(
            f"{where}: a switching point needs its active level — high or low; got "
            f"{active!r}. There is no default: a normally-closed switch reads 0 when "
            "actuated, so a guessed level inverts present and absent."
        )
    address = _int(address, "address", where, 0, MAX_ADDRESS)
    return SwitchLayout(table=table, address=address, active=active)


def _layout(raw: Any, protocol: str, where: str) -> ModbusLayout | BitLayout | SwitchLayout:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: layout is required (a mapping).")
    if protocol == "iolink":
        return _bit_layout(raw, where)
    if raw.get("table") in SWITCH_TABLES:
        extra = sorted(k for k in ("type", "order") if k in raw)
        if extra:
            raise ValueError(f"{where}: {', '.join(extra)} do not apply to a switching bit.")
        return switch_layout(raw["table"], raw.get("address"), raw.get("active"), where)
    return modbus_layout(
        raw.get("table"), raw.get("address"), raw.get("type"), raw.get("order"), where
    )


def _range(raw: Any, where: str) -> tuple[float, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        raise ValueError(f"{where}: range must be [low, high].")
    low, high = (_number(v, "range", where) for v in raw)
    if low >= high:
        raise ValueError(f"{where}: range low must be below high; got {list(raw)}.")
    return (low, high)


def _sentinels(raw: Any, where: str) -> tuple[Sentinel, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{where}: invalid must be a list of {{raw, meaning}}.")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{where}: each invalid entry needs raw and meaning.")
        value = _int(item.get("raw"), "invalid.raw", where, 0, 2**64 - 1)
        out.append(Sentinel(raw=value, meaning=_text(item, "meaning", where)))
    return tuple(out)


def _accuracy(raw: Any, where: str) -> Accuracy | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or "full_scale" not in raw:
        raise ValueError(
            f"{where}: accuracy needs full_scale — a % F.S. figure means nothing without it."
        )
    parts = {
        key: _number(raw.get(key, 0.0), key, where)
        for key in ("linearity_pct", "hysteresis_pct", "crosstalk_pct")
    }
    if any(v < 0 for v in parts.values()):
        raise ValueError(f"{where}: accuracy components cannot be negative.")
    full_scale = _number(raw["full_scale"], "full_scale", where)
    if full_scale <= 0:
        raise ValueError(f"{where}: accuracy full_scale must be positive; got {full_scale}.")
    return Accuracy(full_scale=full_scale, **parts)


#: The local store keeps 32 characters of a unit; a longer one would be cut
#: silently, so it is refused here instead.
MAX_UNIT_LENGTH = 32


def _unit(raw: dict, where: str) -> str:
    unit = _text(raw, "unit", where)
    if len(unit) > MAX_UNIT_LENGTH:
        raise ValueError(
            f"{where}: unit {unit!r} is longer than {MAX_UNIT_LENGTH} characters, which the "
            "store would cut — put the description in the channel name, keep the unit short."
        )
    return unit


def _switch_channel(raw: dict, name: str, layout: SwitchLayout, where: str) -> Channel:
    """A switching channel: a state or an event, no unit, no scale (HLD §17.5b)."""
    bad = sorted(k for k in ("scale", "offset", "range", "accuracy", "invalid") if k in raw)
    if bad:
        raise ValueError(f"{where}: {', '.join(bad)} do not apply to a switching channel.")
    signal = _choice(raw, "signal", SWITCH_SIGNALS, where)
    unit = raw.get("unit") or ""
    return Channel(name=name, layout=layout, unit=str(unit), signal=signal)


def _channel(raw: Any, protocol: str, index: int) -> Channel:
    if not isinstance(raw, dict):
        raise ValueError(f"channel #{index + 1}: must be a mapping.")
    name = _text(raw, "name", f"channel #{index + 1}")
    where = f"channel {name!r}"
    scale = _number(raw.get("scale", 1.0), "scale", where)
    if scale == 0:
        raise ValueError(f"{where}: scale 0 would turn every reading into 0.")
    response = raw.get("response_ms")
    layout = _layout(raw.get("layout"), protocol, where)
    if isinstance(layout, SwitchLayout):
        return _switch_channel(raw, name, layout, where)
    invalid = _sentinels(raw.get("invalid"), where)
    width = layout.words * 16 if isinstance(layout, ModbusLayout) else layout.bit_length
    for sentinel in invalid:
        if sentinel.raw >= 1 << width:
            raise ValueError(
                f"{where}: sentinel 0x{sentinel.raw:X} does not fit the {width}-bit field, "
                "so it could never match — check the datasheet value."
            )
    return Channel(
        name=name,
        layout=layout,
        unit=_unit(raw, where),
        signal=_choice(raw, "signal", SIGNALS, where),
        scale=scale,
        offset=_number(raw.get("offset", 0.0), "offset", where),
        range=_range(raw.get("range"), where),
        invalid=invalid,
        accuracy=_accuracy(raw.get("accuracy"), where),
        response_ms=None if response is None else _number(response, "response_ms", where),
    )


def _match(raw: Any, protocol: str, where: str) -> tuple[int | None, int | None]:
    if raw is None:
        return None, None
    if protocol != "iolink":
        raise ValueError(
            f"{where}: match (vendor_id/device_id) is IO-Link only — a Modbus device "
            "does not report a numeric identity to check against."
        )
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: match must be {{vendor_id, device_id}}.")
    vendor = _int(raw.get("vendor_id"), "match.vendor_id", where, 0, 0xFFFF)
    device = _int(raw.get("device_id"), "match.device_id", where, 0, 0xFFFFFF)
    return vendor, device


def parse_profile(raw: Any) -> SensorProfile:
    """Validate a profile mapping into frozen objects; raise ``ValueError`` on any defect."""
    if not isinstance(raw, dict):
        raise ValueError(f"A sensor profile must be a mapping, got {type(raw).__name__}.")
    where = f"profile {raw.get('id')!r}"
    protocol = _choice(raw, "protocol", PROTOCOLS, where)
    channels_raw = raw.get("channels")
    if not isinstance(channels_raw, list) or not channels_raw:
        raise ValueError(f"{where}: needs at least one channel.")
    channels = tuple(_channel(c, protocol, i) for i, c in enumerate(channels_raw))
    vendor_id, device_id = _match(raw.get("match"), protocol, where)
    pd_bits = raw.get("pd_bits")
    if pd_bits is not None:
        if protocol != "iolink":
            raise ValueError(f"{where}: pd_bits is IO-Link only.")
        pd_bits = _int(pd_bits, "pd_bits", where, 1, MAX_PD_BITS)
        for channel in channels:
            end = channel.layout.bit_offset + channel.layout.bit_length
            if end > pd_bits:
                raise ValueError(
                    f"{where}: channel {channel.name!r} ends at bit {end}, past pd_bits {pd_bits}."
                )
    names = [c.name for c in channels]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"{where}: duplicate channel name(s): {', '.join(duplicates)}.")
    return SensorProfile(
        id=_text(raw, "id", where),
        protocol=protocol,
        source=_choice(raw, "source", SOURCES, where),
        verified=_choice(raw, "verified", VERIFIED, where),
        channels=channels,
        vendor_id=vendor_id,
        device_id=device_id,
        pd_bits=pd_bits,
    )


def load_profile_file(path: Path | str) -> SensorProfile:
    """Read and validate one YAML profile."""
    import yaml

    text = Path(path).read_text("utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Sensor profile {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Sensor profile {path} must be a YAML mapping at the top level.")
    return parse_profile(raw)


def profile_summary(profile: SensorProfile) -> dict[str, Any]:
    """A profile as a plain mapping for display — shared by the CLI and MCP."""
    rows = []
    for channel in profile.channels:
        layout = channel.layout
        if isinstance(layout, BitLayout):
            where = f"bits {layout.bit_offset}+{layout.bit_length} {layout.value_type}"
        elif isinstance(layout, SwitchLayout):
            where = f"{layout.table}[{layout.address}] active-{layout.active}"
        else:
            where = f"{layout.table}[{layout.address}] {layout.value_type} {layout.order}"
        rows.append(
            {
                "channel": channel.name,
                "layout": where,
                "unit": channel.unit,
                "signal": channel.signal,
                "range": list(channel.range) if channel.range else None,
                "sentinels": len(channel.invalid),
                "band": channel.accuracy.band if channel.accuracy else None,
            }
        )
    return {
        "id": profile.id,
        "protocol": profile.protocol,
        "source": profile.source,
        "verified": profile.verified,
        "match": (
            {"vendor_id": profile.vendor_id, "device_id": profile.device_id}
            if profile.vendor_id is not None
            else None
        ),
        "pd_bits": profile.pd_bits,
        "channels": rows,
    }
