"""Read-only Modbus-TCP operations.

Covers a wide range of PLCs that speak Modbus-TCP, including many domestic /
国产 controllers (汇川 Inovance, 信捷 Xinje, 和利时 Hollysys, 台达 Delta, etc.).
All reads go through a short-lived ``modbus_session``; nothing is written.

Register decode hints are supported (``uint16`` / ``int16`` / ``uint32`` /
``int32`` / ``float32`` / ``raw``) since raw Modbus registers are untyped 16-bit
words and the meaning is device-specific.
"""

from __future__ import annotations

import struct
from typing import Any

from iaiops.connectors.modbus import byteorder, templates
from iaiops.core.brain._shared import s
from iaiops.core.runtime.connection import OTProtocolError, modbus_session

MAX_COUNT = 125  # Modbus protocol max registers per read

_REGISTER_DECODES = ("raw", "uint16", "int16", "uint32", "int32", "float32")
_PAIR_DECODES = ("uint32", "int32", "float32")  # each value consumes 2 registers


def _clamp_count(count: int) -> int:
    return max(1, min(int(count), MAX_COUNT))


def _check(response: Any, address: int, kind: str) -> Any:
    """Raise a teaching OTProtocolError if a Modbus response is an exception.

    An exception response means the device ANSWERED at the protocol level (it is
    alive and reachable) but rejected the request — hence
    :class:`OTProtocolError`, a distinguishable subclass of
    :class:`OTConnectionError`, so diagnostics never misreport it as offline.
    """
    if response is None or (hasattr(response, "isError") and response.isError()):
        raise OTProtocolError(
            f"Modbus {kind} read at address {address} failed: {s(str(response), 120)}. "
            f"Check the address range, the unit/device id, and the function code "
            f"support on this PLC.",
            protocol="modbus",
        )
    return response


def _decode_registers(registers: list[int], decode: str) -> list:
    """Decode raw 16-bit registers per the requested hint (big-endian words)."""
    decode = decode if decode in _REGISTER_DECODES else "uint16"
    if decode in ("raw", "uint16"):
        return list(registers)
    if decode == "int16":
        return [struct.unpack(">h", struct.pack(">H", r & 0xFFFF))[0] for r in registers]
    # 32-bit decodes consume register pairs (big-endian word order).
    out: list = []
    for i in range(0, len(registers) - 1, 2):
        hi, lo = registers[i] & 0xFFFF, registers[i + 1] & 0xFFFF
        packed = struct.pack(">HH", hi, lo)
        if decode == "uint32":
            out.append(struct.unpack(">I", packed)[0])
        elif decode == "int32":
            out.append(struct.unpack(">i", packed)[0])
        elif decode == "float32":
            out.append(round(struct.unpack(">f", packed)[0], 6))
    return out


def _decode_note(registers: list[int], decode: str) -> str | None:
    """Explain when a pair (2-register) decode cannot consume every register.

    Never fabricates a value: a lone trailing register is half a 32-bit value.
    Returns None when the decode consumed everything (or is a 16-bit decode).
    """
    if decode not in _PAIR_DECODES or len(registers) % 2 == 0:
        return None
    if len(registers) == 1:
        return (
            f"'{decode}' needs 2 registers per value but only 1 was read — "
            f"nothing decoded. Re-read with count=2 (or a multiple of 2)."
        )
    return (
        f"'{decode}' decodes register pairs; the trailing odd register "
        f"({len(registers) - 1} pairs decoded of {len(registers)} registers) was "
        f"not decoded. Read an even count to decode all values."
    )


def _read_registers(target: Any, address: int, count: int, decode: str, fn_name: str) -> dict:
    """Shared body for holding / input register reads."""
    count = _clamp_count(count)
    with modbus_session(target) as client:
        fn = getattr(client, fn_name)
        resp = _check(fn(address, count=count, device_id=target.unit_id), address, fn_name)
        registers = list(resp.registers)
    decode = decode if decode in _REGISTER_DECODES else "uint16"
    note = _decode_note(registers, decode)
    result = {
        "address": address,
        "count": count,
        "unit_id": target.unit_id,
        "decode": decode,
        "raw_registers": registers,
        "decoded": _decode_registers(registers, decode),
    }
    if note:
        result["decode_note"] = note
    return result


def modbus_read_holding(target: Any, address: int, count: int = 1, decode: str = "uint16") -> dict:
    """[READ] Read holding registers (FC03) with an optional decode hint."""
    return _read_registers(target, address, count, decode, "read_holding_registers")


def modbus_read_input(target: Any, address: int, count: int = 1, decode: str = "uint16") -> dict:
    """[READ] Read input registers (FC04) with an optional decode hint."""
    return _read_registers(target, address, count, decode, "read_input_registers")


def _read_bits(target: Any, address: int, count: int, fn_name: str) -> dict:
    """Shared body for coil / discrete-input reads."""
    count = max(1, min(int(count), 2000))
    with modbus_session(target) as client:
        fn = getattr(client, fn_name)
        resp = _check(fn(address, count=count, device_id=target.unit_id), address, fn_name)
        bits = [bool(b) for b in list(resp.bits)[:count]]
    return {
        "address": address,
        "count": count,
        "unit_id": target.unit_id,
        "bits": bits,
    }


def modbus_read_coils(target: Any, address: int, count: int = 1) -> dict:
    """[READ] Read coils (FC01) — writable digital outputs, read-only here."""
    return _read_bits(target, address, count, "read_coils")


def modbus_read_discrete(target: Any, address: int, count: int = 1) -> dict:
    """[READ] Read discrete inputs (FC02) — read-only digital inputs."""
    return _read_bits(target, address, count, "read_discrete_inputs")


def modbus_detect_byte_order(
    registers: list[int],
    value_type: str = "float32",
    hint: float | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
) -> dict:
    """[READ] Detect the word/byte order of a raw Modbus register block.

    Pure decode logic (no device): decodes ``registers`` under every candidate
    order for ``value_type`` (uint16/int16/uint32/int32/float32) and scores them
    against a ``hint`` value and/or a ``[value_min, value_max]`` plausibility band.
    Returns the candidates, the best-matching order and a confidence.
    """
    return byteorder.detect_byte_order(
        list(registers),
        value_type,
        hint=hint,
        value_min=value_min,
        value_max=value_max,
    )


def modbus_list_templates() -> dict:
    """[READ] List the built-in vendor register-map templates."""
    return {"templates": templates.list_templates()}


def modbus_apply_template(
    target: Any, template: str, address: int | None = None, count: int | None = None
) -> dict:
    """[READ] Read a register block and decode it into named tags via a template.

    Reads ``count`` registers (default: the template's span) starting at
    ``address`` from the right register file (holding/input per the template),
    then decodes them into named engineering tags. ``address`` defaults to the
    template's own base offset (its lowest register) so a template using absolute
    vendor addresses reads from the right place without the caller knowing them;
    pass ``address`` to override.
    """
    tmpl = templates.get_template(template)
    start = address if address is not None else tmpl.base_offset
    span = count if count is not None else tmpl.span
    fn_name = "read_input_registers" if tmpl.register_type == "input" else "read_holding_registers"
    block = _read_registers(target, start, span, "raw", fn_name)
    decoded = templates.apply_template(template, block["raw_registers"], start_address=start)
    decoded["unit_id"] = target.unit_id
    return decoded


def modbus_health_summary(
    target: Any,
    addresses: list[int] | None = None,
    thresholds: dict | None = None,
    register_type: str = "holding",
    decode: str = "uint16",
) -> dict:
    """[READ] Classify holding/input registers against warn/alarm thresholds.

    ``addresses`` defaults to the endpoint's configured tag refs (parsed as
    register addresses). ``thresholds`` overrides per-address bounds keyed by
    the address string. ``decode`` (uint16 default, or int16 — mirroring the
    read tools' decode vocabulary) controls how each single register is
    interpreted before threshold comparison, so bipolar int16 tags (e.g. −10 on
    the wire as 65526) don't false-alarm against high bounds. Mirrors the
    OPC-UA ``health_summary`` classifier.
    """
    addrs = _resolve_addresses(target, addresses)
    if not addrs:
        return {
            "error": "No addresses to evaluate. Pass addresses or add numeric "
            "'tags' to the endpoint's config entry.",
        }
    decode = decode if decode in ("uint16", "int16") else "uint16"
    fn_name = "read_input_registers" if register_type == "input" else "read_holding_registers"
    counts = {"ok": 0, "warn": 0, "alarm": 0, "unknown": 0}
    results: list[dict] = []
    with modbus_session(target) as client:
        fn = getattr(client, fn_name)
        for addr in addrs[:100]:
            tag = _resolve_addr_tag(target, addr, thresholds)
            try:
                resp = fn(addr, count=1, device_id=target.unit_id)
                if resp is None or (hasattr(resp, "isError") and resp.isError()):
                    value = None
                else:
                    value = float(_decode_registers(list(resp.registers[:1]), decode)[0])
            except Exception:  # noqa: BLE001 — per-address read error
                value = None
            status = "unknown" if value is None else tag.classify(value)
            counts[status] += 1
            results.append(
                {"address": addr, "label": s(tag.label, 64), "value": value, "status": status}
            )
    offenders = [r for r in results if r["status"] in ("warn", "alarm")]
    overall = "alarm" if counts["alarm"] else "warn" if counts["warn"] else "ok"
    return {
        "endpoint": s(target.name, 64),
        "register_type": register_type,
        "decode": decode,
        "overall": overall,
        "counts": counts,
        "evaluated": len(results),
        "offenders": offenders,
        "results": results,
    }


def _resolve_addresses(target: Any, addresses: list[int] | None) -> list[int]:
    """Resolve addresses from the argument or numeric config tag refs."""
    if addresses:
        return [int(a) for a in addresses]
    out: list[int] = []
    for t in target.tags:
        try:
            out.append(int(t.ref))
        except (TypeError, ValueError):
            continue
    return out


def _resolve_addr_tag(target: Any, address: int, overrides: dict | None):
    """Resolve thresholds for a Modbus address from overrides or config tags."""
    from iaiops.core.runtime.config import MonitorTag

    key = str(address)
    if overrides and key in overrides:
        o = overrides[key] or {}
        return MonitorTag(
            ref=key,
            label=str(o.get("label", "")),
            warn_high=_opt(o.get("warn_high")),
            alarm_high=_opt(o.get("alarm_high")),
            warn_low=_opt(o.get("warn_low")),
            alarm_low=_opt(o.get("alarm_low")),
        )
    return target.tag_for(key) or MonitorTag(ref=key)


def _opt(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
