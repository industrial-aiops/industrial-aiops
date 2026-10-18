"""Defects an adversarial review of E3 found.

1. `iaiops sensor show <id> > f.yaml` produced broken YAML (console wrap).
2. The drift guard was one-directional, and unknown keys were ignored — a typo
   such as `derived-from:` made an entry "not derived" and skip every guard.
3. Provenance: a blank `firmware:` became the string "None"; lists, newlines and
   huge strings were accepted; `date` unchecked.
4. verified bench/field without evidence (and evidence on 待核实) loaded.
5. `check` text output hid description / provenance / caveat.
6. An unknown id said "Missing required key" / pointed at `iaiops doctor`.
7. An invalid filter returned "nothing matches".
8. The template caveat lived only in a YAML comment.
"""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

from iaiops.core.runtime.sensor import library, parse_profile

pytestmark = pytest.mark.unit

BASE = {
    "id": "x",
    "protocol": "modbus",
    "source": "manual",
    "verified": "待核实",
    "channels": [
        {
            "name": "c",
            "layout": {"table": "input", "address": 0, "type": "uint16"},
            "unit": "u",
            "signal": "level",
        }
    ],
}
EVIDENCE = {"by": "wei", "device": "lab meter #1", "compared": "display 230.1 V = read 230.1 V"}


@pytest.mark.parametrize("entry", [e["id"] for e in library.list_profiles()])
def test_1_show_output_is_the_file_byte_for_byte_and_parses(entry):
    from iaiops.cli.sensor import sensor_app

    result = CliRunner(env={"COLUMNS": "60"}).invoke(sensor_app, ["show", entry])
    path, _ = library.get(entry)
    assert result.output == path.read_text("utf-8")
    parse_profile(yaml.safe_load(result.output))


@pytest.mark.parametrize(
    ("where", "patch"),
    [
        ("top", {"derived-from": "modbus-template:x"}),
        ("top", {"provenence": EVIDENCE}),
        ("channel", {"bogus": 1}),
        ("layout", {"words": 2}),
    ],
)
def test_2_unknown_keys_are_refused(where, patch):
    raw = {
        **BASE,
        "channels": [{**BASE["channels"][0], "layout": dict(BASE["channels"][0]["layout"])}],
    }
    if where == "top":
        raw.update(patch)
    elif where == "channel":
        raw["channels"][0].update(patch)
    else:
        raw["channels"][0]["layout"].update(patch)
    with pytest.raises(ValueError, match="unknown"):
        parse_profile(raw)


def test_2_derived_entries_have_exactly_the_template_channels_and_nothing_added():
    from iaiops.connectors.modbus.templates import get_template

    for entry in library.list_profiles():
        _, profile = library.get(entry["id"])
        assert profile.derived_from or profile.provenance, f"{entry['id']} has no source evidence"
        if not profile.derived_from:
            continue
        template = get_template(profile.derived_from.partition(":")[2])
        assert {c.name for c in profile.channels} == {t.tag for t in template.tags if t.unit}
        for channel in profile.channels:
            assert channel.signal == "level"
            assert channel.range is None and channel.offset == 0.0
            assert channel.invalid == () and channel.accuracy is None
        assert profile.caveat == template.caveat


@pytest.mark.parametrize(
    "evidence",
    [
        {**EVIDENCE, "firmware": None},
    ],
)
def test_3_a_blank_optional_field_is_dropped_not_stored_as_none(evidence):
    profile = parse_profile({**BASE, "verified": "bench", "provenance": evidence})
    assert "firmware" not in dict(profile.provenance)


@pytest.mark.parametrize(
    "evidence",
    [
        {**EVIDENCE, "compared": ["a", "b"]},
        {**EVIDENCE, "device": "x" * 300},
        {**EVIDENCE, "by": "wei\nignore previous"},
        {**EVIDENCE, "date": "last tuesday"},
    ],
)
def test_3_provenance_values_are_short_single_line_text(evidence):
    with pytest.raises(ValueError, match="provenance"):
        parse_profile({**BASE, "verified": "bench", "provenance": evidence})


def test_4_verified_and_evidence_must_agree():
    with pytest.raises(ValueError, match="provenance"):
        parse_profile({**BASE, "verified": "bench"})
    with pytest.raises(ValueError, match="待核实"):
        parse_profile({**BASE, "verified": "待核实", "provenance": EVIDENCE})
    assert parse_profile({**BASE, "verified": "field", "provenance": EVIDENCE}).verified == "field"


def test_5_check_text_shows_caveat_and_source(tmp_path):
    from iaiops.cli.sensor import sensor_app

    entry = library.list_profiles()[0]["id"]
    path, profile = library.get(entry)
    out = CliRunner().invoke(sensor_app, ["check", str(path)]).output
    assert "待核实" in out and profile.caveat[:20] in out and "modbus-template" in out


def test_6_unknown_id_is_a_clear_library_error():
    from iaiops.cli.sensor import sensor_app
    from mcp_server.tools.sensor_tools import sensor_profile_show

    cli = CliRunner().invoke(sensor_app, ["show", "nope"])
    assert cli.exit_code == 1 and "Missing required key" not in cli.output and "nope" in cli.output
    mcp = sensor_profile_show("nope")
    assert "doctor" not in str(mcp) and mcp["known"]


def test_7_an_invalid_filter_is_refused():
    with pytest.raises(ValueError, match="protocol"):
        library.list_profiles(protocol="bogus")


def test_8_caveat_is_a_field_shown_by_list_and_summary():
    from mcp_server.tools.sensor_tools import sensor_profile_list, sensor_profile_show

    entry = sensor_profile_list()["profiles"][0]
    assert entry["caveat"] and "待核实" in entry["caveat"]
    assert "path" not in entry  # copy, never bind the installed file
    shown = sensor_profile_show(entry["id"])
    assert shown["summary"]["caveat"] == entry["caveat"] and "path" not in shown
