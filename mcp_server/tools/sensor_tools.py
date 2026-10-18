"""Sensor MCP tools (READ-ONLY) — edition module (HLD §17.2).

An EDITION module (see ``EDITION_MODULES`` in ``mcp_server.profiles``): loads with
``IAIOPS_MCP=sensor``, not on a bare protocol and not in the always-on brain.

Three steps of "connect a sensor", each read-only:

* ``sensor_import_iodd`` drafts a profile from a vendor IODD and RETURNS the text
  — it writes nothing, so a person saves and reviews it;
* ``sensor_profile_check`` validates a profile file and lists its channels;
* ``sensor_read_channel`` reads one point once and reports reachable / decodable
  separately, with unit, accuracy band and the profile's verification level.

Binding a profile into config.yaml is deliberately NOT a tool (D51): config.yaml
is the one source of truth and which sensor sits on which port is a site fact.
The same engines back the CLI (``iaiops sensor import-iodd | check | read``).
"""

from pathlib import Path
from typing import Optional

from iaiops.core.governance import governed_tool
from mcp_server._shared import _target, mcp, tool_errors


def _local_file(path: str, suffixes: tuple[str, ...]) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        # A link named `x.yaml` can point anywhere; parser errors echo file content.
        raise ValueError(f"{path!r} is a symbolic link — pass the real file.")
    if candidate.suffix.lower() not in suffixes:
        raise ValueError(f"Expected a {'/'.join(suffixes)} file, got {path!r}.")
    if not candidate.is_file():
        raise ValueError(f"{path!r} is not a readable file.")
    return candidate


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sensor_import_iodd(path: str, process_data: Optional[str] = None) -> dict:
    """[READ][risk=low] Draft a sensor profile from a vendor IODD file. Writes nothing.

    The draft is marked ``verified: 待核实``: IODD unit codes are kept as codes,
    signal kinds are assumed (and say so), and every item that could not be
    represented is listed in ``notes``. Save the draft, replace the unit codes
    with real units, check one live reading, then bind it under ``port_profiles``
    in config.yaml yourself — this tool never edits config.

    Args:
        path: Local path to the device's IODD (.xml).
        process_data: ProcessData id, required when the IODD declares several.

    Returns dict: {draft (YAML text), profile_id, device_name, notes[]}.
    """
    from iaiops.core.runtime.sensor.iodd import MAX_IODD_BYTES, import_iodd, render_draft

    source = _local_file(path, (".xml",))
    if source.stat().st_size > MAX_IODD_BYTES:
        raise ValueError(f"{path!r} is larger than {MAX_IODD_BYTES // (1024 * 1024)} MB.")
    draft = import_iodd(source.read_text("utf-8"), process_data=process_data)
    return {
        "draft": render_draft(draft, source_name=source.name),
        "profile_id": draft.profile["id"],
        "device_name": draft.device_name,
        "notes": list(draft.notes),
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sensor_profile_check(path: str) -> dict:
    """[READ][risk=low] Validate a sensor profile file and list its channels.

    Args:
        path: Local path to a profile (.yaml / .yml).

    Returns dict: {id, protocol, source, verified, match, pd_bits,
        channels:[{channel, layout, unit, signal, range, sentinels, band}]}.
        An invalid profile returns {error} naming the field.
    """
    from iaiops.core.runtime.sensor import load_profile_file, profile_summary

    return profile_summary(load_profile_file(_local_file(path, (".yaml", ".yml"))))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sensor_read_channel(ref: str, endpoint: Optional[str] = None) -> dict:
    """[READ][risk=low] Read one sensor point once and say how far it got.

    Levels are reported separately and never upgraded: ``reachable`` (did the
    device answer — a Modbus exception or an IO-Link "different device" answer
    counts as answered; None when nothing was contacted) and ``decodable`` (did
    the answer decode into a measurement — None when the device never answered).
    Only when both are true are value, unit, accuracy band and the profile's
    verification level returned. A ref the endpoint cannot read is refused
    before contacting anything. Nothing is stored.

    Args:
        ref: ``ch:<name>`` (Modbus profile channel), ``port<N>/<channel>``
            (IO-Link), a typed Modbus point such as ``ir:0:float32:CDAB``, or a
            switching point ``di:<addr>:<high|low>`` / ``co:<addr>:<high|low>``
            (value 1 = actuated; the result carries ``active`` and ``meaning``).
        endpoint: Endpoint name from config (default endpoint if omitted).

    Returns dict: {endpoint, ref, contacted, refused?, levels:{reachable,
        decodable}, value?, unit?, band?, verified?, profile?, untyped?, note?,
        reason?}. ``refused: true`` = the ref cannot be read on this endpoint and
        nothing was contacted.
    """
    from iaiops.core.runtime.sensor import probe

    return probe.read_channel(_target(endpoint), ref)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sensor_profile_list(
    protocol: Optional[str] = None,
    vendor_id: Optional[int] = None,
    device_id: Optional[int] = None,
) -> dict:
    """[READ][risk=low] List the shipped sensor profile library (HLD §17.3).

    Entries are ``verified: 待核实`` unless they carry provenance evidence. For an
    IO-Link device, pass the vendor/device id read with ``iolink_device_info`` to
    find candidates — a match is a SUGGESTION: one device id can run several
    process-data layouts, and binding stays a person's edit of config.yaml.

    Args:
        protocol: modbus | iolink (optional).
        vendor_id: IO-Link vendor id (optional).
        device_id: IO-Link device id (optional).

    Returns dict: {profiles:[{id, category, protocol, verified, source,
        description, caveat, vendor_id, device_id, derived_from, channels}]}.
    """
    from iaiops.core.runtime.sensor import library

    entries = library.list_profiles(protocol=protocol, vendor_id=vendor_id, device_id=device_id)
    # No install path: a profile is COPIED (sensor_profile_show → save), never bound
    # in place — an upgrade would silently change the decoding under a config.
    return {"profiles": [{k: v for k, v in e.items() if k != "path"} for e in entries]}


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sensor_profile_show(profile_id: str) -> dict:
    """[READ][risk=low] Show one library profile: summary plus its YAML text.

    Writes nothing. To use it, a person saves the YAML, checks one reading
    against the device's own display, and binds it in config.yaml.

    Args:
        profile_id: An id from ``sensor_profile_list``.

    Returns dict: {summary (as sensor_profile_check), yaml, next}; {error, known}
        for an unknown id.
    """
    from iaiops.core.runtime.sensor import library, profile_summary

    try:
        path, profile = library.get(profile_id)
    except library.ProfileNotFoundError as exc:
        return {"error": str(exc), "known": exc.known}
    return {
        "summary": profile_summary(profile),
        "yaml": path.read_text("utf-8"),
        "next": "Save this YAML to a file, check one reading against the device's display, "
        "then bind that file (not the installed one) under sensor_profile in config.yaml.",
    }
