"""Vendor register-map templates for Modbus (data + lookup, no device needed).

A register *template* is a named, read-only map of common vendor/meter register
layouts: each entry names a tag, its register offset (relative to the block base),
its numeric ``value_type``, word/byte ``order`` and an optional ``scale`` + unit.
Applying a template to a raw register block decodes it into named, engineering
tags — sparing the user from re-deriving the map and the byte order by hand.

Templates are intentionally a small, curated set: a couple of generic layouts
plus a couple of well-known community meter/PLC maps. The PRECISE per-firmware
addresses vary, so each non-generic template carries a ``待核实`` caveat — treat
it as a documented starting point, then confirm against the device manual or the
``modbus_detect_byte_order`` helper.

Pure data + ``get_template`` / ``list_templates`` / ``apply_template`` lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iaiops.connectors.modbus.byteorder import decode_value


@dataclass(frozen=True)
class TemplateTag:
    """One decoded tag in a register template (offset is relative to block base)."""

    tag: str
    offset: int
    value_type: str = "float32"
    order: str = "ABCD"
    scale: float = 1.0
    unit: str = ""
    label: str = ""


@dataclass(frozen=True)
class RegisterTemplate:
    """A named register map for a vendor device family."""

    name: str
    register_type: str  # holding | input
    description: str
    tags: tuple[TemplateTag, ...]
    caveat: str = ""

    @property
    def base_offset(self) -> int:
        """Lowest register offset in the template (the block's natural start address)."""
        return min((t.offset for t in self.tags), default=0)

    @property
    def span(self) -> int:
        """Register count from the template's base offset to its last tag's end.

        Measured from ``base_offset`` (NOT from 0) so a template using absolute
        vendor addresses (e.g. Schneider's 2999-3111) spans ~112 registers, not
        ~3111 — otherwise a default read would blow past the Modbus 125-reg limit.
        """
        if not self.tags:
            return 0
        from iaiops.connectors.modbus.byteorder import _TYPE_WIDTH

        base = self.base_offset
        return max(t.offset + _TYPE_WIDTH.get(t.value_type, 2) for t in self.tags) - base


def _float_block(pairs: list[tuple[str, int, str, str]], order: str) -> tuple[TemplateTag, ...]:
    """Build a tuple of float32 TemplateTags: (tag, offset, unit, label)."""
    return tuple(
        TemplateTag(tag=tag, offset=off, value_type="float32", order=order, unit=unit, label=label)
        for (tag, off, unit, label) in pairs
    )


def _typed_block(
    rows: list[tuple[str, int, str, str, float, str]],
) -> tuple[TemplateTag, ...]:
    """Build TemplateTags of mixed integer/scaled types.

    Each row: (tag, offset, value_type, order, scale, unit) — for vendor maps that
    encode engineering values as scaled integers (e.g. deci-volts, milli-amps).
    """
    return tuple(
        TemplateTag(
            tag=tag, offset=off, value_type=vt, order=order, scale=scale, unit=unit, label=""
        )
        for (tag, off, vt, order, scale, unit) in rows
    )


# ── The curated template catalog (vendor-neutral; OT device families only) ──────

_TEMPLATES: dict[str, RegisterTemplate] = {
    "generic_float32_be": RegisterTemplate(
        name="generic_float32_be",
        register_type="holding",
        description="Generic block of big-endian (ABCD) float32 values, one per register pair.",
        tags=_float_block(
            [(f"f{i}", i * 2, "", f"float #{i}") for i in range(8)], order="ABCD"
        ),
    ),
    "generic_float32_word_swap": RegisterTemplate(
        name="generic_float32_word_swap",
        register_type="holding",
        description="Generic block of word-swapped (CDAB) float32 values — common on many PLCs.",
        tags=_float_block(
            [(f"f{i}", i * 2, "", f"float #{i}") for i in range(8)], order="CDAB"
        ),
    ),
    # Eastron SDM630 — very widely deployed DIN-rail 3-phase energy meter. Input
    # registers (FC04), float32 big-endian (ABCD). Addresses below are the common
    # community map; 待核实 against the exact firmware.
    "eastron_sdm630": RegisterTemplate(
        name="eastron_sdm630",
        register_type="input",
        description="Eastron SDM630 3-phase energy meter (FC04 input regs, float32 ABCD).",
        caveat="待核实 — community register map; exact addresses vary by firmware revision.",
        tags=_float_block(
            [
                ("voltage_l1", 0x0000, "V", "Phase 1 line-to-neutral volts"),
                ("voltage_l2", 0x0002, "V", "Phase 2 line-to-neutral volts"),
                ("voltage_l3", 0x0004, "V", "Phase 3 line-to-neutral volts"),
                ("current_l1", 0x0006, "A", "Phase 1 current"),
                ("current_l2", 0x0008, "A", "Phase 2 current"),
                ("current_l3", 0x000A, "A", "Phase 3 current"),
                ("power_total", 0x0034, "W", "Total system power"),
                ("frequency", 0x0046, "Hz", "Line frequency"),
            ],
            order="ABCD",
        ),
    ),
    # Schneider PM5xxx series power-meter basic block (FC03 holding, float32 ABCD).
    "schneider_pm5xxx_basic": RegisterTemplate(
        name="schneider_pm5xxx_basic",
        register_type="holding",
        description="Schneider PM5xxx power meter, basic metering block (FC03, float32 ABCD).",
        caveat="待核实 — community register map; confirm base addresses per model/firmware.",
        tags=_float_block(
            [
                ("current_a", 2999, "A", "Current phase A"),
                ("current_b", 3001, "A", "Current phase B"),
                ("current_c", 3003, "A", "Current phase C"),
                ("voltage_ab", 3019, "V", "Voltage A-B"),
                ("voltage_bc", 3021, "V", "Voltage B-C"),
                ("voltage_ca", 3023, "V", "Voltage C-A"),
                ("active_power_total", 3059, "kW", "Total active power"),
                ("frequency", 3109, "Hz", "Frequency"),
            ],
            order="ABCD",
        ),
    ),
    # Phoenix Contact PLCnext vPLC — its Modbus-TCP server maps GDS / process data
    # into holding registers, but the exact addresses are set per engineering
    # project (no fixed vendor block). This is a documented DEFAULT float32 process
    # block (ABCD, the PLCnext default word order) — a starting point to adapt.
    "phoenix_plcnext_process_be": RegisterTemplate(
        name="phoenix_plcnext_process_be",
        register_type="holding",
        description="Phoenix Contact PLCnext vPLC default process-data block "
        "(FC03 holding, float32 ABCD; addresses per engineering project).",
        caveat="待核实 — PLCnext Modbus register mapping is engineering-configured; "
        "confirm base addresses against the project's GDS / Modbus port map.",
        tags=_float_block(
            [
                ("pv1", 0x0000, "", "Process value 1"),
                ("pv2", 0x0002, "", "Process value 2"),
                ("pv3", 0x0004, "", "Process value 3"),
                ("pv4", 0x0006, "", "Process value 4"),
                ("setpoint", 0x0008, "", "Setpoint"),
                ("cycletime_ms", 0x000A, "ms", "PLC cycle time"),
            ],
            order="ABCD",
        ),
    ),
    # Carlo Gavazzi EM24-DIN — widely deployed 3-phase energy analyzer. Values are
    # scaled INTEGERS on input registers (FC04): voltages in 0.1 V, currents in
    # 0.001 A, power in 0.1 W. The EM24 stores int32 least-significant-word-first
    # (word swap → CDAB); frequency is a single int16 word.
    "carlo_gavazzi_em24": RegisterTemplate(
        name="carlo_gavazzi_em24",
        register_type="input",
        description="Carlo Gavazzi EM24 3-phase energy analyzer (FC04, scaled int32, CDAB).",
        caveat="待核实 — community register map; word order (CDAB) and scaling vary by "
        "EM24 variant/firmware; confirm against the device manual.",
        tags=_typed_block(
            [
                ("voltage_l1_n", 0x0000, "int32", "CDAB", 0.1, "V"),
                ("voltage_l2_n", 0x0002, "int32", "CDAB", 0.1, "V"),
                ("voltage_l3_n", 0x0004, "int32", "CDAB", 0.1, "V"),
                ("current_l1", 0x000C, "int32", "CDAB", 0.001, "A"),
                ("power_total", 0x0028, "int32", "CDAB", 0.1, "W"),
                ("frequency", 0x0033, "int16", "AB", 0.1, "Hz"),
            ]
        ),
    ),
    # Huawei SUN2000 string inverter — a very common Modbus-TCP/RTU device (国产
    # 友好). Holding registers (FC03), big-endian (ABCD). Power values are int32 in
    # watts; frequency/efficiency are uint16 in 0.01 units; device status is uint16.
    "huawei_sun2000_inverter": RegisterTemplate(
        name="huawei_sun2000_inverter",
        register_type="holding",
        description="Huawei SUN2000 inverter core telemetry (FC03, int32/uint16, ABCD).",
        caveat="待核实 — public register map; addresses/gains vary by SUN2000 model "
        "and firmware; confirm against the Huawei Modbus interface definition.",
        tags=_typed_block(
            [
                ("input_power", 32064, "int32", "ABCD", 1.0, "W"),
                ("active_power", 32080, "int32", "ABCD", 1.0, "W"),
                ("grid_frequency", 32085, "uint16", "AB", 0.01, "Hz"),
                ("efficiency", 32086, "uint16", "AB", 0.01, "%"),
                ("device_status", 32089, "uint16", "AB", 1.0, ""),
            ]
        ),
    ),
    # Growatt string inverter — another very common PV inverter (信创 friendly).
    # Input registers (FC04), big-endian (ABCD). Power values are uint32 in 0.1 W;
    # PV voltage / grid frequency are uint16 in 0.1 V / 0.01 Hz.
    "growatt_inverter": RegisterTemplate(
        name="growatt_inverter",
        register_type="input",
        description="Growatt PV inverter core telemetry (FC04, uint32/uint16, ABCD).",
        caveat="待核实 — public RTU protocol map; addresses/scaling vary by Growatt "
        "series/firmware; confirm against the Growatt Modbus RTU protocol doc.",
        tags=_typed_block(
            [
                ("input_power", 1, "uint32", "ABCD", 0.1, "W"),
                ("pv1_voltage", 3, "uint16", "AB", 0.1, "V"),
                ("output_power", 35, "uint32", "ABCD", 0.1, "W"),
                ("grid_frequency", 37, "uint16", "AB", 0.01, "Hz"),
            ]
        ),
    ),
}


def list_templates() -> list[dict[str, Any]]:
    """Return a summary of every available template (name / type / description)."""
    return [
        {
            "name": t.name,
            "register_type": t.register_type,
            "description": t.description,
            "tag_count": len(t.tags),
            "span_registers": t.span,
            "caveat": t.caveat,
        }
        for t in _TEMPLATES.values()
    ]


def get_template(name: str) -> RegisterTemplate:
    """Return a template by name, or raise ``KeyError`` with the known names."""
    try:
        return _TEMPLATES[name]
    except KeyError:
        known = ", ".join(_TEMPLATES) or "(none)"
        raise KeyError(f"Unknown template {name!r}. Available: {known}.") from None


def apply_template(
    name: str, registers: list[int], *, start_address: int = 0
) -> dict[str, Any]:
    """Decode a raw register block into named tags using template ``name``.

    ``start_address`` is the absolute register address of ``registers[0]`` so a
    template's offsets can be aligned to a block read from anywhere. A tag whose
    registers fall outside the supplied block is reported with ``value=None`` and
    an ``out_of_range`` flag (rather than silently dropped). PURE — no device.
    """
    template = get_template(name)
    regs = [int(r) & 0xFFFF for r in registers]
    from iaiops.connectors.modbus.byteorder import _TYPE_WIDTH

    decoded: list[dict[str, Any]] = []
    for tag in template.tags:
        idx = tag.offset - start_address
        width = _TYPE_WIDTH.get(tag.value_type, 2)
        if idx < 0 or idx + width > len(regs):
            decoded.append(
                {
                    "tag": tag.tag,
                    "address": tag.offset,
                    "value": None,
                    "unit": tag.unit,
                    "label": tag.label,
                    "out_of_range": True,
                }
            )
            continue
        raw = decode_value(regs[idx : idx + width], tag.value_type, tag.order)
        value = round(raw * tag.scale, 6) if tag.scale != 1.0 else raw
        decoded.append(
            {
                "tag": tag.tag,
                "address": tag.offset,
                "value": value,
                "unit": tag.unit,
                "label": tag.label,
                "out_of_range": False,
            }
        )
    return {
        "template": template.name,
        "register_type": template.register_type,
        "start_address": start_address,
        "caveat": template.caveat,
        "tags": decoded,
    }
