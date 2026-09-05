"""``iaiops onboard`` — the chain from a network to an answer.

Four properties carry this feature, and every one of them was broken at least
once while it was being built:

* **A command the path prints must run.** ``status`` shipped its first draft
  printing ``iaiops collect run --endpoint X``, which does not parse — the
  endpoint is positional. A wrong next command on a plant floor costs an
  afternoon, so every command any step can emit is resolved against the real
  Typer app here.
* **A drafted value names its evidence.** ``DraftField`` refuses to hold a value
  without one, and refuses to hold a gap without saying what the gap is waiting
  for. A config draft is the artefact where a plausible default does the most
  damage: it is pasted once and trusted for years.
* **Only CONFIRMED protocols become endpoints.** An open 502 means something is
  listening. A config that says it is a Modbus device would be believed.
* **The block has to paste.** Every non-blank line is either YAML or a comment,
  and the fragment parses — a comment re-wrapped by a renderer loses its ``#``
  on the continuation line and takes the config with it.
"""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

from iaiops.core.onboard import (
    STATE_DONE,
    STATE_NEXT,
    STATE_WAITING,
    DraftField,
    assess_path,
    draft_from_scan,
    render_yaml,
)
from iaiops.core.onboard.path import _BROWSE

pytestmark = pytest.mark.unit

runner = CliRunner()


def _host(ip, protocols, open_ports=(), identity=None):
    return {
        "ip": ip,
        "open_ports": list(open_ports),
        "identity": identity or {},
        "protocols": list(protocols),
    }


def _confirmed(protocol, port, evidence="probe", detail="d"):
    return {
        "protocol": protocol,
        "confidence": "confirmed",
        "port": port,
        "evidence": evidence,
        "detail": detail,
    }


def _record(*hosts, scan_id="scan1"):
    return {
        "scan_id": scan_id,
        "site": "line-3",
        "started_at": "2026-09-05T00:00:00Z",
        "hosts": list(hosts),
    }


# --- the commands the path prints ------------------------------------------


def _resolve(command: str) -> None:
    """Walk a printed command through the real CLI, or fail saying why.

    Checks the sub-app, the command name, and every ``--option`` it uses.
    Placeholders (``<cidr>``, a file name) are values and are not checked —
    a value cannot be wrong in a way this test could see.
    """
    import typer.main

    from iaiops.cli._root import app

    parts = command.split()
    assert parts and parts[0] == "iaiops", f"not an iaiops command: {command!r}"
    # Typer vendors its own click, so `isinstance(node, click.Group)` against the
    # installed click is False for every group here and the walk stops at the
    # root — silently checking nothing. Duck typing is what actually holds.
    node = typer.main.get_command(app)
    index = 1
    while index < len(parts) and hasattr(node, "get_command"):
        name = parts[index]
        if name.startswith("-"):
            break
        child = node.get_command(None, name)
        assert child is not None, f"`{command}` names {name!r}, which no CLI group provides"
        node = child
        index += 1
    known = {opt for param in node.params for opt in getattr(param, "opts", ())}
    rest = parts[index:]
    used = [p for p in rest if p.startswith("--")]
    missing = [opt for opt in used if opt not in known]
    assert not missing, f"`{command}` passes {missing}, which {node.name!r} does not accept"

    # Required parameters, which the option check alone cannot see: a command can
    # name a real subcommand, pass only valid options, and still refuse to run
    # because a required one was never supplied.
    positionals = [tok for tok in rest if not tok.startswith("-")]
    supplied_opts = set(used)
    for param in node.params:
        if not getattr(param, "required", False):
            continue
        opts = set(getattr(param, "opts", ()))
        if any(o.startswith("-") for o in opts):
            assert opts & supplied_opts, (
                f"`{command}` omits required option {sorted(opts)} of {node.name!r}"
            )
        else:
            assert positionals, f"`{command}` omits the required argument {sorted(opts)}"
            positionals.pop(0)


def test_every_browse_command_the_path_can_print_resolves_in_the_cli():
    for template in set(_BROWSE.values()):
        _resolve(template.format(endpoint="an-endpoint"))


def test_every_step_command_any_site_state_can_produce_resolves_in_the_cli(tmp_path):
    """Drive the path through each state and check whatever it offers.

    This is the test that would have caught ``collect run --endpoint``.
    """
    from dataclasses import dataclass

    @dataclass
    class Tag:
        ref: str
        role: str = ""

    @dataclass
    class Target:
        name: str
        protocol: str
        tags: tuple = ()

    @dataclass
    class Config:
        targets: tuple = ()

    states = [
        Config(),
        Config(targets=(Target("e1", "opcua"),)),
        Config(targets=(Target("e1", "modbus"),)),
        Config(targets=(Target("e1", "ethernetip"),)),
        Config(targets=(Target("e1", "opcua", (Tag("ns=2;i=2"),)),)),
        Config(targets=(Target("e1", "opcua", (Tag("ns=2;i=2", "run_state"),)),)),
    ]
    seen = set()
    for config in states:
        path = assess_path(config, db_path=tmp_path / "none.db")
        for step in path.steps:
            if step.command:
                seen.add(step.command)
                _resolve(step.command)
    assert seen, "the path offered no command in any state, so nothing was checked"


# --- a drafted value names its evidence -------------------------------------


def test_a_drafted_value_without_evidence_cannot_be_built():
    with pytest.raises(ValueError, match="no evidence"):
        DraftField("unit_id", 1)


def test_a_gap_without_a_caution_cannot_be_built():
    with pytest.raises(ValueError, match="no value and no caution"):
        DraftField("slot", None)


def test_every_drafted_field_across_every_protocol_carries_its_evidence():
    record = _record(
        _host(
            "10.0.0.5", [_confirmed("modbus", 502)], [502], {"modbus": {"extra": {"unit_id": 1}}}
        ),
        _host("10.0.0.6", [_confirmed("s7", 102)], [102], {"s7": {"extra": {"slot": 2}}}),
        _host(
            "10.0.0.7",
            [_confirmed("opcua", 4840)],
            [4840],
            {
                "opcua": {
                    "extra": {
                        "endpoint_count": 1,
                        "allows_none_security": True,
                        "allows_anonymous": True,
                    }
                }
            },
        ),
        _host("10.0.0.8", [_confirmed("mc", 5007)], [5007], {"mc": {"extra": {"plctype": "iQ-R"}}}),
        _host(
            "10.0.0.9",
            [_confirmed("mtconnect", 5000)],
            [5000],
            {"mtconnect": {"extra": {"device_count": 1, "devices": ["VMC-1"]}}},
        ),
        _host(
            "10.0.0.10",
            [_confirmed("iolink", 8000)],
            [8000],
            {"iolink": {"extra": {"flavor": "iotcore"}}},
        ),
        _host("10.0.0.11", [_confirmed("ethernetip", 44818)], [44818]),
    )
    draft = draft_from_scan(record)
    assert len(draft.endpoints) == 7
    for endpoint in draft.endpoints:
        for field in endpoint.fields:
            if field.established:
                assert field.observed.strip(), f"{endpoint.name}.{field.name} has no evidence"
            else:
                assert field.caution.strip(), f"{endpoint.name}.{field.name} explains nothing"


# --- only confirmed protocols ------------------------------------------------


def test_an_open_port_alone_never_becomes_an_endpoint():
    record = _record(
        _host(
            "10.0.0.9",
            [
                {
                    "protocol": "modbus",
                    "confidence": "port_only",
                    "port": 502,
                    "evidence": "tcp_open",
                    "detail": "",
                }
            ],
            [502],
        )
    )
    draft = draft_from_scan(record)
    assert draft.endpoints == ()
    assert len(draft.skipped) == 1
    assert "not that it speaks" in draft.skipped[0].reason


def test_a_confirmed_protocol_with_no_connector_is_skipped_and_named():
    record = _record(_host("10.0.0.9", [_confirmed("ignition", 8088)], [8088]))
    draft = draft_from_scan(record)
    assert draft.endpoints == ()
    assert "no connector" in draft.skipped[0].reason


# --- the port, which is the whole reason the candidate now carries one -------


def test_the_recorded_port_is_used_even_when_it_is_not_the_default():
    record = _record(_host("10.0.0.5", [_confirmed("modbus", 5020)], [5020]))
    port = next(f for f in draft_from_scan(record).endpoints[0].fields if f.name == "port")
    assert port.value == 5020


def test_an_old_scan_with_one_possible_port_deduces_it_and_says_it_deduced():
    record = _record(_host("10.0.0.5", [_confirmed("modbus", 0)], [502]))
    port = next(f for f in draft_from_scan(record).endpoints[0].fields if f.name == "port")
    assert port.value == 502
    assert "deduced" in port.caution


def test_an_old_scan_with_two_possible_ports_refuses_rather_than_picking_the_lower():
    """4840 and 4843 (TLS) both serve OPC-UA, and both open is an ordinary server."""
    record = _record(_host("10.0.0.7", [_confirmed("opcua", 0)], [4840, 4843]))
    url = next(f for f in draft_from_scan(record).endpoints[0].fields if f.name == "endpoint_url")
    assert url.value is None
    assert "4840" not in (url.caution or "")


# --- the semantic boundary ---------------------------------------------------


def test_tags_are_always_empty_no_matter_what_the_scan_identified():
    record = _record(
        _host(
            "10.0.0.7",
            [_confirmed("opcua", 4840)],
            [4840],
            {"opcua": {"name": "GoodPartsCounter", "extra": {"endpoint_count": 1}}},
        )
    )
    parsed = yaml.safe_load(render_yaml(draft_from_scan(record)))
    assert parsed["endpoints"][0]["tags"] == []


def test_an_mtconnect_agent_with_several_devices_refuses_to_pick_one():
    record = _record(
        _host(
            "10.0.0.8",
            [_confirmed("mtconnect", 5000)],
            [5000],
            {"mtconnect": {"extra": {"device_count": 3, "devices": ["Agent", "VMC-1", "VMC-2"]}}},
        )
    )
    device = next(f for f in draft_from_scan(record).endpoints[0].fields if f.name == "device")
    assert device.value is None
    assert "Agent" in device.caution and "never down" in device.caution


def test_an_opcua_server_that_refuses_anonymous_says_so_instead_of_drafting_none():
    record = _record(
        _host(
            "10.0.0.7",
            [_confirmed("opcua", 4840)],
            [4840],
            {
                "opcua": {
                    "extra": {
                        "endpoint_count": 2,
                        "allows_none_security": False,
                        "allows_anonymous": False,
                    }
                }
            },
        )
    )
    fields = {f.name: f for f in draft_from_scan(record).endpoints[0].fields}
    assert fields["security_mode"].value is None
    assert fields["username"].value is None
    assert "secret set" in fields["username"].caution


# --- the block has to paste --------------------------------------------------


def _sample_draft():
    return draft_from_scan(
        _record(
            _host("10.0.0.5", [_confirmed("modbus", 502)], [502]),
            _host("10.0.0.11", [_confirmed("ethernetip", 44818)], [44818]),
            _host(
                "10.0.0.9",
                [
                    {
                        "protocol": "mqtt",
                        "confidence": "port_only",
                        "port": 1883,
                        "evidence": "tcp_open",
                        "detail": "",
                    }
                ],
                [1883],
            ),
        )
    )


def test_the_rendered_draft_parses_as_yaml_and_loads_as_real_endpoints():
    from iaiops.core.runtime.config import _parse_target

    parsed = yaml.safe_load(render_yaml(_sample_draft()))
    targets = [_parse_target(entry) for entry in parsed["endpoints"]]
    assert [t.protocol for t in targets] == ["modbus", "ethernetip"]
    assert targets[0].host == "10.0.0.5" and targets[0].port == 502


def test_no_rendered_line_is_wide_enough_to_be_rewrapped_by_an_80_column_terminal():
    """A re-wrapped comment's second line has no `#`, and the paste stops parsing."""
    for line in render_yaml(_sample_draft()).splitlines():
        assert len(line) <= 80, f"{len(line)} chars would wrap: {line!r}"


def test_an_unestablished_field_never_appears_as_a_value():
    text = render_yaml(_sample_draft())
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        assert "NOT ESTABLISHED" not in stripped
    # ...and the ethernetip slot, which the scan genuinely cannot know, is there
    # as a comment rather than silently omitted.
    assert "# slot: NOT ESTABLISHED BY THE SCAN." in text


def test_an_endpoint_already_in_config_is_reported_but_not_offered_again():
    draft = draft_from_scan(
        _record(_host("10.0.0.5", [_confirmed("modbus", 502)], [502])),
        existing_names=("modbus-10-0-0-5",),
    )
    assert draft.endpoints[0].already_configured
    assert draft.pastable == ()
    assert "Already in config.yaml" in render_yaml(draft)


def test_the_draft_states_what_it_structurally_cannot_contain():
    limits = " ".join(_sample_draft().limits)
    assert "is NOT evidence that the site does not speak it" in limits
    # Read off the discovery tables, so a protocol that becomes identifiable
    # stops being listed without anyone remembering to edit this.
    from iaiops.core.discovery.identify import NO_SAFE_IDENTIFY

    for protocol in NO_SAFE_IDENTIFY:
        assert f"{protocol}: seen as an open port only" in limits


# --- the path ----------------------------------------------------------------


def test_exactly_one_step_is_next(tmp_path):
    path = assess_path(None, db_path=tmp_path / "none.db")
    assert [s.state for s in path.steps].count(STATE_NEXT) == 1
    assert path.next_step is not None and path.next_step.key == "survey"
    assert path.next_step.command.startswith("iaiops scan plan")


def test_a_step_that_is_genuinely_done_stays_done_even_behind_the_cursor(tmp_path):
    """Someone who hand-wrote config.yaml before ever scanning has real endpoints.

    Reporting them as `waiting` to keep the sequence tidy would be a lie in the
    direction that makes the tool look more necessary.
    """
    from dataclasses import dataclass

    @dataclass
    class Target:
        name: str
        protocol: str
        tags: tuple = ()

    @dataclass
    class Config:
        targets: tuple = ()

    path = assess_path(Config(targets=(Target("e1", "opcua"),)), db_path=tmp_path / "none.db")
    by_key = {s.key: s for s in path.steps}
    assert by_key["survey"].state == STATE_NEXT  # no scan stored
    assert by_key["endpoints"].state == STATE_DONE  # ...but the endpoints are real
    assert by_key["collect"].state == STATE_WAITING
    assert [s.state for s in path.steps].count(STATE_NEXT) == 1


def test_a_protocol_with_no_point_list_says_why_instead_of_naming_a_command(tmp_path):
    from dataclasses import dataclass

    @dataclass
    class Target:
        name: str
        protocol: str
        tags: tuple = ()

    @dataclass
    class Config:
        targets: tuple = ()

    # S7, not Modbus: an S7 CPU really does expose no symbol table on the wire,
    # whereas Modbus has register templates — which is what this test used to use
    # as its example of "nothing to ask", and got wrong.
    path = assess_path(Config(targets=(Target("e1", "s7"),)), db_path=tmp_path / "none.db")
    points = next(s for s in path.steps if s.key == "points")
    assert points.command == ""
    assert "TIA/STEP7 project" in points.detail


def test_every_supported_protocol_is_deliberately_in_one_table_or_the_other():
    """No protocol may fall through to a blanket sentence.

    The first version of this test pinned `_BROWSE` to the five entries it
    happened to have, which locked in a WRONG answer: BACnet has an object list,
    MQTT a topic tree, EtherCAT a slave enumeration, HART its dynamic variables
    and Modbus its register templates, and all five were being told "this
    protocol has no point list to ask for". A test that asserts the set someone
    typed cannot notice that the set is wrong — so this one requires every
    supported protocol to be an explicit, reasoned entry in one table or the
    other, and a protocol added later fails until somebody decides.
    """
    from iaiops.core.onboard.path import _NO_BROWSE_REASONS
    from iaiops.core.runtime.config import SUPPORTED_PROTOCOLS

    for protocol in SUPPORTED_PROTOCOLS:
        askable = protocol in _BROWSE
        explained = protocol in _NO_BROWSE_REASONS
        assert askable != explained, (
            f"{protocol!r} is in {'both' if askable else 'neither'} table — it must "
            "either name a command that asks for its point list, or say why there "
            "is none, and the reason must be about THAT protocol."
        )
    for protocol, reason in _NO_BROWSE_REASONS.items():
        assert len(reason) > 40, f"{protocol!r} has no real reason, just a placeholder"


def test_a_protocol_the_product_can_enumerate_is_never_told_to_type_it_by_hand():
    """The regression that motivated the table split, protocol by protocol.

    Each of these has a real enumeration command in its own CLI group; a site on
    that protocol must be sent to it, not told a register map comes from a
    vendor PDF.
    """
    for protocol in ("bacnet", "mqtt", "ethercat", "hart", "modbus"):
        assert protocol in _BROWSE, protocol
        _resolve(_BROWSE[protocol].format(endpoint="an-endpoint"))


def test_status_reports_a_site_with_nothing_configured_without_raising(tmp_path):
    from iaiops.cli._root import app

    result = runner.invoke(app, ["onboard", "status", "--db", str(tmp_path / "none.db"), "--json"])
    assert result.exit_code == 0, result.output
    assert '"next_step": "survey"' in result.output


def test_draft_without_a_stored_scan_says_what_to_run(tmp_path):
    from iaiops.cli._root import app

    result = runner.invoke(app, ["onboard", "draft", "--db", str(tmp_path / "none.db")])
    assert result.exit_code != 0
    assert "scan plan" in result.output


# --- both front ends, one engine (D17) ---------------------------------------


@pytest.fixture
def tools():
    from mcp_server.tools import overview_tools

    return overview_tools


class TestTheMcpFrontEnd:
    def test_both_tools_carry_the_governance_marker(self, tools):
        """An ungoverned tool is an unaudited path into the same engine."""
        for tool in (tools.onboarding_status, tools.onboarding_config_draft):
            assert getattr(tool, "_is_governed_tool", False), tool

    def test_both_are_declared_read_only(self, tools):
        for tool in (tools.onboarding_status, tools.onboarding_config_draft):
            assert (tool.__doc__ or "").startswith("[READ][risk=low]"), tool

    def test_status_is_the_engine_answer_verbatim(self, tmp_path, monkeypatch, tools):
        """Not "equivalent" — identical. Any divergence is the tool having
        formed an opinion of its own, which is how two front ends drift."""
        monkeypatch.setenv("HOME", str(tmp_path))
        from iaiops.core.runtime import config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".iaiops", raising=False)
        db = tmp_path / "none.db"
        assert tools.onboarding_status(db=str(db)) == assess_path(db_path=db).as_dict()

    def test_the_draft_tool_says_what_to_run_when_no_scan_is_stored(self, tmp_path, tools):
        """`tool_errors` turns the refusal into a payload rather than a raise, so
        what has to be asserted is that the payload still NAMES the command."""
        out = tools.onboarding_config_draft(db=str(tmp_path / "none.db"))
        assert "scan plan" in str(out), out

    def test_the_draft_tool_docstring_forbids_filling_in_a_null_field(self, tools):
        """The cautions ARE the content. A tool description that let an agent
        treat `value: null` as "pick a sensible default" would undo the whole
        module in one summarisation step."""
        doc = tools.onboarding_config_draft.__doc__ or ""
        assert "do not fill one in and do not drop it" in doc
        assert "`tags` is always empty" in doc
