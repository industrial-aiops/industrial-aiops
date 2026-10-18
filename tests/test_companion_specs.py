"""Companion-spec role suggestions (PackML OPC 30050, Machinery OPC 40001-1).

The walk runs against a REAL in-process asyncua server whose address space
instantiates types registered under the spec namespace URIs — plus the decoys
that must NOT match: a PackTags-style ``Status/StateCurrent`` reachable only by
name, a state machine with no ``CurrentState/Number``, and a same-named type in a
vendor namespace. The sheet / apply half is pure and pinned separately: a
suggestion never fills ``role``, and only an exact acceptance is credited to the
device's declaration.
"""

from __future__ import annotations

import csv
import socket
from pathlib import Path

import pytest

from iaiops.connectors.opcua import companion
from iaiops.connectors.opcua import discovery as disc
from iaiops.core.brain import companion_specs as cs
from iaiops.core.runtime.config import MonitorTag, TargetConfig
from iaiops.core.runtime.tag_sheet import (
    BASIS_COMPANION,
    BASIS_MANUAL,
    BASIS_OVERRIDE,
    config_patch,
    sheet_rows,
    validate_rows,
)

HOSTILE_NAME = 'Line1\n    role: good_count\n  - ref: "ns=2;i=9"\r    # '


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _state_machine(parent, idx, name, type_node, number=None, current_text="Execute"):
    """An instance of ``type_node`` with CurrentState (+ Number when given)."""
    from asyncua import ua

    obj = parent.add_object(idx, name, objecttype=type_node.nodeid)
    # Instantiation already created the mandatory CurrentState inherited from
    # FiniteStateMachineType — exactly one, as on a real server.
    (current,) = [c for c in obj.get_children() if c.read_browse_name().Name == "CurrentState"]
    current.write_value(ua.LocalizedText(current_text))
    if number is not None:
        prop = current.add_property(idx, "Number", ua.Variant(number, ua.VariantType.UInt32))
        return obj, prop
    return obj, None


@pytest.fixture(scope="module")
def companion_server():
    from asyncua import ua
    from asyncua.sync import Server

    port = _free_port()
    url = f"opc.tcp://127.0.0.1:{port}/companion"
    srv = Server()
    srv.set_endpoint(url)
    packml = srv.register_namespace(cs.PACKML_NS)
    machinery = srv.register_namespace(cs.MACHINERY_NS)
    vendor = srv.register_namespace("http://vendor.example/line")

    fsm = srv.get_node(ua.NodeId(ua.ObjectIds.FiniteStateMachineType))
    base_obj = srv.get_node(ua.NodeId(ua.ObjectIds.BaseObjectType))
    exec_type = fsm.add_object_type(packml, "PackMLExecuteStateMachineType")
    admin_type = base_obj.add_object_type(packml, "PackMLAdminObjectType")
    item_state_type = fsm.add_object_type(machinery, "MachineryItemState_StateMachineType")
    mode_type = fsm.add_object_type(machinery, "MachineryOperationModeStateMachineType")
    # A vendor subtype of the Machinery type: must still match, via its supertype.
    vendor_state = item_state_type.add_object_type(vendor, "AcmeItemStateMachineType")
    # Same NAME as the Machinery type, wrong namespace: must NOT match.
    impostor = fsm.add_object_type(vendor, "MachineryItemState_StateMachineType")

    objects = srv.nodes.objects
    filler = objects.add_object(vendor, "Filler")
    base_sm = filler.add_object(vendor, "BaseStateMachine")
    machine_state = base_sm.add_object(vendor, "MachineState")
    # PackML ExecuteState is a sub-state machine. Seen ACTIVE (Good 6), the walk cannot
    # tell whether this server goes Bad or stale when stopped: recognised only.
    _, packml_number = _state_machine(machine_state, packml, "ExecuteState", exec_type, number=6)
    # A stopped line whose server answers Bad_StateNotActive on Number, as the OPC
    # Foundation reference stack does: the device demonstrated it — suggested.
    wrapper_sm = objects.add_object(vendor, "Wrapper").add_object(vendor, "MachineState")
    _, stopped_number = _state_machine(wrapper_sm, packml, "ExecuteState", exec_type, number=6)
    stopped_number.write_value(
        ua.DataValue(StatusCode=ua.StatusCode(ua.StatusCodes.BadStateNotActive))
    )
    admin = filler.add_object(packml, "Admin", objecttype=admin_type.nodeid)
    processed = admin.add_variable(packml, "ProdProcessedCount", [1, 2])
    admin.add_variable(packml, "StopReason", 0)
    # PackTags-style name with no companion type behind it — a NAME, not a declaration.
    status = filler.add_object(vendor, "Status")
    state_current = status.add_variable(vendor, "StateCurrent", 6)

    press = objects.add_object(vendor, "Press")
    _, machinery_number = _state_machine(
        press, machinery, "MachineryItemState", item_state_type, number=3, current_text="Executing"
    )
    _state_machine(press, machinery, "MachineryOperationMode", mode_type, number=3)
    _, vendor_number = _state_machine(objects, vendor, "Capper", vendor_state, number=3)
    _state_machine(objects, vendor, "Labeller", item_state_type)  # no Number
    _, impostor_number = _state_machine(objects, vendor, "Fake", impostor, number=3)
    # A type whose BrowseName claims the Machinery namespace but whose NodeId is a vendor's.
    spoof_type = fsm.add_object_type(
        ua.NodeId(5000, vendor), ua.QualifiedName("MachineryItemState_StateMachineType", machinery)
    )
    _, spoof_number = _state_machine(objects, vendor, "Spoof", spoof_type, number=3)
    # An OBJECT with the spec's instance name but a plain FiniteStateMachineType: a name only.
    mixer = objects.add_object(vendor, "Mixer")
    plain = fsm.add_object_type(vendor, "PlainStateMachineType")
    _, decoy_number = _state_machine(mixer, vendor, "MachineryItemState", plain, number=3)
    # A browse name that tries to write YAML through the evidence comment.
    hostile = objects.add_object(vendor, HOSTILE_NAME)
    _, hostile_number = _state_machine(
        hostile, machinery, "MachineryItemState", item_state_type, number=3
    )

    srv.start()
    try:
        yield {
            "url": url,
            "packml": packml_number.nodeid.to_string(),
            "packml_stopped": stopped_number.nodeid.to_string(),
            "machinery": machinery_number.nodeid.to_string(),
            "vendor": vendor_number.nodeid.to_string(),
            "impostor": impostor_number.nodeid.to_string(),
            "decoy": decoy_number.nodeid.to_string(),
            "spoof": spoof_number.nodeid.to_string(),
            "hostile": hostile_number.nodeid.to_string(),
            "state_current": state_current.nodeid.to_string(),
            "processed": processed.nodeid.to_string(),
        }
    finally:
        srv.stop()


def _target(url: str, tags=()) -> TargetConfig:
    return TargetConfig(name="line1", protocol="opcua", endpoint_url=url, tags=tags)


@pytest.fixture(scope="module")
def hints(companion_server):
    return companion.companion_hints(_target(companion_server["url"]))


def _by_node(found: dict) -> dict[str, dict]:
    return {h["node_id"]: h for h in found["suggestions"]}


@pytest.mark.integration
def test_machinery_item_state_is_suggested_with_its_evidence(companion_server, hints):
    hint = _by_node(hints)[companion_server["machinery"]]
    assert (hint["role"], hint["running_when"], hint["spec_id"]) == ("run_state", [3], "machinery")
    assert hint["basis"] == "type_definition"
    assert hint["browse_path"].endswith("MachineryItemState/CurrentState/Number")
    assert "§12.2" in hint["why"] and cs.MACHINERY_NS in hint["why"]
    assert hint["current_value"] == 3


@pytest.mark.integration
def test_an_active_packml_execute_state_is_recognised_but_not_suggested(companion_server, hints):
    """Seen running, nothing says whether this server goes Bad or stays stale when stopped.

    The stale case counts stopped time as running, so a Good 6 is not evidence enough.
    """
    assert companion_server["packml"] not in _by_node(hints)
    (packml,) = [r for r in hints["recognised_without_role"] if r["type"].startswith("PackMLExec")]
    assert packml["browse_path"].startswith("Filler/")
    assert "sub-state machine" in packml["why_no_role"]
    assert "read Number as Good" in packml["why_no_role"]
    assert "Re-run the suggestion while the machine is stopped" in packml["why_no_role"]


@pytest.mark.integration
def test_a_stopped_packml_execute_state_is_suggested_on_its_own_evidence(companion_server, hints):
    """Number answered Bad_StateNotActive during the walk: the device showed what it does."""
    hint = _by_node(hints)[companion_server["packml_stopped"]]
    assert (hint["role"], hint["running_when"], hint["spec_id"]) == ("run_state", [6], "packml")
    assert hint["browse_path"] == "Wrapper/MachineState/ExecuteState/CurrentState/Number"
    assert "§6.3.8" in hint["why"] and "answered BadStateNotActive" in hint["why"]
    assert hint["current_value"] == cs.STATE_NOT_ACTIVE
    assert hint["verified_on"] == "2026-10-18"
    # The stale-server hole and the mode caveat travel with it into the sheet.
    evidence = cs.evidence_line(hint)
    assert "stale" in evidence and "待核实" in evidence
    assert any("Maintenance" in c for c in hint["caveats"])


@pytest.mark.integration
def test_a_vendor_subtype_matches_through_its_supertype(companion_server, hints):
    hint = _by_node(hints)[companion_server["vendor"]]
    assert hint["instance_type"] == "AcmeItemStateMachineType"
    assert "subtype of MachineryItemState_StateMachineType" in hint["why"]


@pytest.mark.integration
def test_names_alone_never_match(companion_server, hints):
    """D16: a PackTags name, a same-named type in a vendor namespace, or an Object
    carrying the spec's instance name over a plain type — none is a declaration."""
    nodes = _by_node(hints)
    for decoy in ("state_current", "impostor", "decoy", "spoof"):
        assert companion_server[decoy] not in nodes, decoy
    assert set(nodes) == {
        companion_server[k] for k in ("machinery", "vendor", "hostile", "packml_stopped")
    }


@pytest.mark.integration
def test_a_hostile_browse_name_cannot_write_the_config_patch(companion_server, hints):
    """Evidence reaches a YAML comment; a newline or CR there would let it write keys."""
    import yaml

    hint = _by_node(hints)[companion_server["hostile"]]
    assert "\n" not in hint["browse_path"] and "\r" not in hint["browse_path"]
    ref = companion_server["hostile"]
    config = _Config(
        [_target("opc.tcp://x", tags=(MonitorTag(ref=ref), MonitorTag(ref="ns=2;i=9")))]
    )
    rows = [dict(r) for r in sheet_rows(config, {("line1", ref): hint})]
    rows[0].update(role="run_state", running_when="3")
    # Even a sheet whose evidence cell a person (or anything) edited to carry newlines:
    forged = dict(rows[0], suggestion_evidence="x\n    role: good_count\r  - ref: z")
    for row in (rows[0], forged):
        patch = yaml.safe_load(config_patch(validate_rows([row]), by="alice\n  - ref: q"))
        assert patch == [{"ref": ref, "role": "run_state", "running_when": [3]}]


@pytest.mark.integration
def test_declared_children_without_a_role_are_reported_not_suggested(companion_server, hints):
    recognised = {r["browse_path"].rsplit("/", 1)[-1]: r for r in hints["recognised_without_role"]}
    assert "PackMLCountDataType[]" in recognised["ProdProcessedCount"]["why_no_role"]
    assert "case" in recognised["StopReason"]["why_no_role"]
    assert "MODE" in recognised["MachineryOperationMode"]["why_no_role"]
    assert "Number" in recognised["Labeller"]["why_no_role"]
    assert companion_server["processed"] not in _by_node(hints)


@pytest.mark.integration
def test_the_suggested_running_value_is_what_collection_reads(companion_server, hints):
    """Judged running by the SAME rule `oee measure` uses, read through the collector's path."""
    from iaiops.core.runtime.capabilities import get_capabilities

    target = _target(companion_server["url"])
    hint = _by_node(hints)[companion_server["machinery"]]
    tag = MonitorTag(
        ref=hint["node_id"], role="run_state", running_when=tuple(hint["running_when"])
    )
    value, _ = get_capabilities("opcua").monitor_read(target, hint["node_id"])
    assert tag.is_running(value), value


@pytest.mark.integration
def test_tag_discovery_carries_companion_specs(companion_server):
    model = disc.tag_discovery(_target(companion_server["url"]))
    assert len(model["companion_specs"]["suggestions"]) == 4
    assert model["companion_specs"]["is_truncated"] is False


@pytest.mark.integration
def test_discovery_depth_bounds_the_companion_walk(companion_server):
    shallow = disc.tag_discovery(_target(companion_server["url"]), max_depth=1)
    assert shallow["companion_specs"]["max_depth"] == 1
    found = {h["node_id"] for h in shallow["companion_specs"]["suggestions"]}
    assert companion_server["vendor"] in found  # Objects/Capper is depth 1
    assert companion_server["machinery"] not in found  # Objects/Press/… is depth 2


@pytest.mark.integration
def test_a_walk_over_budget_says_so(companion_server, monkeypatch):
    monkeypatch.setattr(companion, "MAX_NODES", 5)
    found = companion.companion_hints(_target(companion_server["url"]))
    assert found["is_truncated"] is True and found["nodes_examined"] == 5
    assert "absence" in found["truncation_note"] and "INCOMPLETE" in found["note"]


@pytest.mark.unit
def test_an_unexamined_walk_is_incomplete_not_empty():
    out = companion.unexamined("ConnectionRefusedError: x")
    assert out["is_truncated"] is True and out["suggestions"] == []


# ── sheet / apply (pure) ─────────────────────────────────────────────────────


class _Config:
    def __init__(self, targets):
        self.targets = targets


def _hint(node_id: str = "ns=2;i=7") -> dict:
    return cs.suggestion(
        cs.STATE_RULES[0],
        node_id=node_id,
        browse_path="Press/MachineryItemState/CurrentState/Number",
        instance_type="MachineryItemState_StateMachineType",
        current_value=3,
    )


#: A test-only stamp key; the stamp itself is covered in test_suggestion_stamp.py.
_KEY = b"t" * 32


def _sheet(hint: dict | None = None) -> list[dict]:
    config = _Config([_target("opc.tcp://x", tags=(MonitorTag(ref="ns=2;i=7"),))])
    hints = {("line1", "ns=2;i=7"): hint} if hint else None
    return [dict(r) for r in sheet_rows(config, hints, stamp_key=_KEY)]


@pytest.mark.unit
def test_a_suggestion_never_fills_role():
    (row,) = _sheet(_hint())
    assert row["suggested_role"] == "run_state"
    assert row["suggested_running_when"] == "3"
    assert "OPC 40001-1" in row["suggestion_evidence"]
    assert row["role"] == "" and row["running_when"] == ""


@pytest.mark.unit
def test_an_untouched_suggested_sheet_confirms_nothing():
    assert validate_rows(_sheet(_hint())) == ()


@pytest.mark.unit
def test_an_exact_acceptance_is_credited_to_the_device_declaration():
    (row,) = _sheet(_hint())
    row.update(role="run_state", running_when="3.0")
    (edit,) = validate_rows([row], stamp_key=_KEY)
    assert edit.basis == BASIS_COMPANION
    assert "OPC 40001-1" in edit.evidence
    patch = config_patch((edit,), by="alice")
    assert "companion-spec suggestion columns stated" in patch


@pytest.mark.unit
def test_a_changed_running_value_is_the_persons_call_not_the_devices():
    (row,) = _sheet(_hint())
    row.update(role="run_state", running_when="3 2")
    (edit,) = validate_rows([row])
    assert edit.basis == BASIS_OVERRIDE
    assert "differing from the sheet's companion-spec suggestion" in config_patch((edit,))


@pytest.mark.unit
def test_no_suggestion_or_no_evidence_is_manual():
    (row,) = _sheet()
    row.update(role="run_state", running_when="2")
    assert validate_rows([row])[0].basis == BASIS_MANUAL
    (row,) = _sheet(_hint())
    row.update(role="run_state", running_when="3", suggestion_evidence="")
    assert validate_rows([row])[0].basis == BASIS_MANUAL


@pytest.mark.unit
def test_a_sheet_from_before_the_suggestion_columns_still_applies():
    old = {"endpoint": "line1", "ref": "ns=2;i=7", "role": "run_state", "running_when": "2"}
    (edit,) = validate_rows([old])
    assert edit.basis == BASIS_MANUAL and edit.as_dict()["evidence"] == ""


@pytest.mark.unit
def test_the_csv_round_trip_keeps_the_evidence(tmp_path: Path):
    from iaiops.core.runtime.tag_sheet import SHEET_COLUMNS

    rows = _sheet(_hint())
    path = tmp_path / "sheet.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    with path.open(newline="", encoding="utf-8") as handle:
        (back,) = list(csv.DictReader(handle))
    back.update(role="run_state", running_when="3")
    assert validate_rows([back], stamp_key=_KEY)[0].basis == BASIS_COMPANION


@pytest.mark.unit
def test_the_page_shows_the_declaration_without_selecting_it():
    from iaiops.core.runtime.tag_page import render_tag_page

    config = _Config([_target("opc.tcp://x", tags=(MonitorTag(ref="ns=2;i=7"),))])
    page = render_tag_page(config, hints={("line1", "ns=2;i=7"): _hint()})
    assert "Device declares" in page and 'data-accept="0"' in page
    assert "selected>" not in page and "selected=" not in page


# ── CLI, end to end against the real server ──────────────────────────────────


@pytest.fixture
def opcua_config(tmp_path, monkeypatch, companion_server):
    import yaml

    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    config = {
        "targets": [
            {
                "name": "filler",
                "protocol": "opcua",
                "endpoint_url": companion_server["url"],
                "tags": [
                    {"ref": companion_server["machinery"]},
                    {"ref": companion_server["state_current"]},
                ],
            },
            {
                "name": "gone",
                "protocol": "opcua",
                "endpoint_url": f"opc.tcp://127.0.0.1:{_free_port()}/x",
            },
        ]
    }
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("IAIOPS_CONFIG", str(path))
    return path


@pytest.mark.integration
def test_export_suggest_then_apply_round_trip(opcua_config, companion_server, tmp_path):
    import yaml
    from typer.testing import CliRunner

    from iaiops.cli.tags import tags_app
    from iaiops.core.runtime.config import load_config

    runner = CliRunner()
    sheet = tmp_path / "sheet.csv"
    result = runner.invoke(tags_app, ["export", str(sheet), "--suggest"])
    assert result.exit_code == 0, result.output
    assert "gone: not examined" in result.output  # unreachable is SAID, not skipped
    rows = list(csv.DictReader(sheet.open(newline="", encoding="utf-8")))
    by_ref = {r["ref"]: r for r in rows}
    assert by_ref[companion_server["machinery"]]["suggested_role"] == "run_state"
    assert by_ref[companion_server["state_current"]]["suggested_role"] == ""  # a name only

    untouched = runner.invoke(tags_app, ["apply", str(sheet), "--by", "alice"])
    assert "none confirmed" in untouched.output and "1 device suggestion" in untouched.output

    row = by_ref[companion_server["machinery"]]
    row.update(role=row["suggested_role"], running_when=row["suggested_running_when"])
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    patch_file = tmp_path / "patch.yaml"
    applied = runner.invoke(
        tags_app, ["apply", str(sheet), "--by", "alice", "--out", str(patch_file)]
    )
    assert applied.exit_code == 0, applied.output
    assert "1 companion_spec" in applied.output
    patch = yaml.safe_load(patch_file.read_text("utf-8"))
    (entry,) = patch
    # Merge into the real config and load it with the real loader.
    config = yaml.safe_load(opcua_config.read_text("utf-8"))
    config["targets"][0]["tags"][0].update(entry)
    opcua_config.write_text(yaml.safe_dump(config), encoding="utf-8")
    (tag,) = [t for t in load_config().targets[0].tags if t.role]
    assert tag.is_running(3) and not tag.is_running(2)


@pytest.mark.unit
def test_one_tag_given_two_meanings_is_refused():
    (row,) = _sheet(_hint())
    a = dict(row, role="run_state", running_when="3")
    b = dict(row, role="good_count", running_when="")
    with pytest.raises(ValueError, match="differently on two rows"):
        validate_rows([a, b])
    assert len(validate_rows([a, dict(a)])) == 2  # the same statement twice is not a conflict


@pytest.mark.unit
def test_configured_refs_match_however_they_are_spaced():
    from iaiops.cli.tags import _canonical_ref

    assert _canonical_ref("  ns=2;i=7 ") == "ns=2;i=7"
    assert _canonical_ref("nsu=http://x/;i=7") == _canonical_ref("nsu=http://x/;i=7")
