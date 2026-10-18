"""E3 (HLD §17.3, D52): the sensor profile library.

Profiles ship under ``iaiops/sensor_profiles/<category>/``. Guards:
- every entry loads, ids are unique, and an entry above 待核实 carries
  provenance evidence;
- an entry derived from a Modbus template matches it address by address — two
  copies of a register map must not drift apart;
- a template whose own caveat calls its offsets placeholders / vendor-specific /
  engineering-configured is never turned into a library entry: that would ship a
  guess as a profile.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from iaiops.core.runtime.sensor import library, parse_profile

pytestmark = pytest.mark.unit

_NOT_A_MAP = ("placeholder", "vendor-specific", "engineering-configured")


def _entries():
    return library.list_profiles()


def test_the_library_ships_inside_the_package():
    import iaiops

    assert library.LIBRARY_DIR.is_relative_to(Path(iaiops.__file__).parent)
    assert _entries(), "the library is empty"


def test_every_entry_loads_and_ids_are_unique():
    ids = [e["id"] for e in _entries()]
    assert len(ids) == len(set(ids))
    for entry in _entries():
        parse_profile(yaml.safe_load(Path(entry["path"]).read_text("utf-8")))


def test_entries_above_unverified_carry_provenance():
    for entry in _entries():
        profile = library.get(entry["id"])[1]
        if profile.verified != "待核实":
            keys = dict(profile.provenance)
            assert {"by", "device", "compared"} <= set(keys), entry["id"]


def test_entries_derived_from_a_template_match_it_exactly():
    from iaiops.connectors.modbus.templates import get_template

    derived = [e for e in _entries() if e["derived_from"]]
    assert derived, "expected template-derived entries"
    for entry in derived:
        _, profile = library.get(entry["id"])
        kind, _, name = profile.derived_from.partition(":")
        assert kind == "modbus-template", entry["id"]
        template = get_template(name)
        assert profile.verified == "待核实"  # the template itself is 待核实
        by_name = {c.name: c for c in profile.channels}
        for tag in template.tags:
            if not tag.unit:
                assert tag.tag not in by_name  # status codes are not measurements
                continue
            channel = by_name[tag.tag]
            layout = channel.layout
            assert (layout.table, layout.address) == (template.register_type, tag.offset), tag.tag
            assert (layout.value_type, layout.order) == (tag.value_type, tag.order), tag.tag
            assert (channel.scale, channel.unit) == (tag.scale, tag.unit), tag.tag


def test_no_entry_is_derived_from_a_template_that_admits_it_is_not_a_map():
    from iaiops.connectors.modbus.templates import get_template

    for entry in _entries():
        name = (library.get(entry["id"])[1].derived_from or "").partition(":")[2]
        if name:
            caveat = get_template(name).caveat.lower()
            assert not any(word in caveat for word in _NOT_A_MAP), entry["id"]


def test_filters():
    modbus = library.list_profiles(protocol="modbus")
    assert modbus and all(e["protocol"] == "modbus" for e in modbus)
    assert library.list_profiles(protocol="iolink", vendor_id=1, device_id=2) == []
    # The shipped entries are all Modbus today: an IO-Link filter must drop them.
    assert library.list_profiles(protocol="iolink") == []


def test_unknown_id_names_the_known_ones():
    with pytest.raises(LookupError, match="Known"):
        library.get("no-such-profile")


def test_provenance_when_present_must_name_who_what_and_how():
    base = {
        "id": "x",
        "protocol": "modbus",
        "source": "manual",
        "verified": "bench",
        "channels": [
            {
                "name": "c",
                "layout": {"table": "input", "address": 0, "type": "uint16"},
                "unit": "u",
                "signal": "level",
            }
        ],
    }
    with pytest.raises(ValueError, match="provenance"):
        parse_profile({**base, "provenance": {"by": "wei"}})
    profile = parse_profile(
        {**base, "provenance": {"by": "wei", "device": "lab meter", "compared": "display = read"}}
    )
    assert dict(profile.provenance)["by"] == "wei"


# ── front-ends ──────────────────────────────────────────────────────────────


def test_cli_list_show_and_copy(tmp_path):
    from typer.testing import CliRunner

    from iaiops.cli.sensor import sensor_app

    runner = CliRunner()
    listed = runner.invoke(sensor_app, ["list", "--json"])
    assert listed.exit_code == 0, listed.output
    first = _entries()[0]["id"]
    assert first in listed.output
    shown = runner.invoke(sensor_app, ["show", first])
    assert shown.exit_code == 0 and "待核实" in shown.output
    out = tmp_path / "p.yaml"
    copied = runner.invoke(sensor_app, ["show", first, "--out", str(out)])
    assert copied.exit_code == 0, copied.output
    assert parse_profile(yaml.safe_load(out.read_text("utf-8"))).id == first
    again = runner.invoke(sensor_app, ["show", first, "--out", str(out)])
    assert again.exit_code == 1 and "--force" in again.output


def test_mcp_list_and_show_are_governed():
    from mcp_server.tools import sensor_tools as tools

    for name in ("sensor_profile_list", "sensor_profile_show"):
        assert getattr(getattr(tools, name), "_is_governed_tool", False)
    listed = tools.sensor_profile_list()
    first = listed["profiles"][0]["id"]
    shown = tools.sensor_profile_show(first)
    assert shown["summary"]["id"] == first and "channels:" in shown["yaml"]
    assert "error" in tools.sensor_profile_show("no-such-profile")
