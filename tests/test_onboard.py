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

import re
import shlex
from dataclasses import dataclass

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


_PLACEHOLDER = re.compile(r"<[^>]+>")


def _resolve(command: str) -> None:
    """Build a real click context for the command, or fail saying why.

    The first version compared the `--options` a command passes against the ones
    the sub-command declares. That is blind to absence: `iaiops scan plan`,
    `iaiops tags export` and `iaiops collect run e1` all pass only valid options
    and all exit 2 for a missing required parameter, and the whole suite stayed
    green with every required parameter stripped out. Handing the string to the
    parser that will actually run it is the only check that cannot be hollow —
    it also catches a bare group, an unknown short option, and a bad type.

    Placeholders (`<cidr>`, a file name) are values; a value cannot be wrong in a
    way this test could see.
    """
    import click
    import typer.main

    from iaiops.cli._root import app

    # `<cidr>`, `<device_id>` and friends are fill-me-in markers, and one of them
    # is typed `int`, so the literal string cannot be type-checked. Substituting
    # `1` keeps the SHAPE under test — how many arguments, which options, which
    # sub-command — which is the part a printed command can get wrong.
    parts = [("1" if _PLACEHOLDER.fullmatch(tok) else tok) for tok in shlex.split(command)]
    assert parts and parts[0] == "iaiops", f"not an iaiops command: {command!r}"
    # Typer vendors its own click, so `isinstance(node, click.Group)` against the
    # installed click is False for every group here and a walk keyed on it stops
    # at the root, silently checking nothing. Duck typing is what actually holds.
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
    assert not hasattr(node, "get_command"), (
        f"`{command}` stops at the group {node.name!r} and names no sub-command; "
        "running it prints help and exits 2"
    )
    try:
        ctx = node.make_context(node.name, parts[index:], resilient_parsing=False)
    except click.exceptions.UsageError as exc:
        raise AssertionError(f"`{command}` does not parse: {exc.format_message()}") from exc
    except SystemExit as exc:
        raise AssertionError(f"`{command}` exits {exc.code} instead of running") from exc
    ctx.close()


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
    # `scan run`, not `scan plan`: the command printed for a step has to be one
    # that can satisfy it, and `plan` stores nothing, so it looped forever.
    assert path.next_step.command.startswith("iaiops scan run")
    assert "scan plan" in path.next_step.detail, "the safe preview must still be named"


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


def test_status_reports_a_site_with_nothing_configured_without_raising(tmp_path, monkeypatch):
    """The name used to describe a condition the test never established: it set
    no config at all, so it asserted `next_step == survey`, which is true on any
    site whose temp --db has no scans."""
    from iaiops.cli._root import app

    monkeypatch.setenv("IAIOPS_CONFIG", str(tmp_path / "config.yaml"))
    result = runner.invoke(app, ["onboard", "status", "--db", str(tmp_path / "none.db"), "--json"])
    assert result.exit_code == 0, result.output
    assert '"next_step": "survey"' in result.output
    assert '"endpoints"' in result.output


def test_a_broken_config_makes_draft_say_so_instead_of_offering_tuned_endpoints(
    tmp_path, monkeypatch
):
    """The bare `except Exception` around `load_config` caught a config that
    exists and does not parse, answered "no endpoints", and so handed over the
    very block `already_configured` exists to withhold."""
    from iaiops.core.onboard.config_state import existing_endpoint_names

    good = tmp_path / "good.yaml"
    good.write_text(
        'endpoints:\n  - name: "e1"\n    protocol: "opcua"\n'
        '    endpoint_url: "opc.tcp://10.0.0.9:4840/"\n    tags: []\n'
    )
    monkeypatch.setenv("IAIOPS_CONFIG", str(good))
    names, error = existing_endpoint_names()
    assert names == ("e1",) and error == ""

    broken = tmp_path / "broken.yaml"
    broken.write_text('endpoints:\n  - name: "e1"\n   protocol: "opcua"\n')
    monkeypatch.setenv("IAIOPS_CONFIG", str(broken))
    names, error = existing_endpoint_names()
    assert names == ()
    assert error, "a file that will not parse is not a file with no endpoints"

    monkeypatch.setenv("IAIOPS_CONFIG", str(tmp_path / "absent.yaml"))
    names, error = existing_endpoint_names()
    assert names == () and error == "", "an absent config really does have none"


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
        formed an opinion of its own, which is how two front ends drift.

        The isolation here used to be inert: `load_config` resolves through
        `default_config_path()`, which reads $IAIOPS_CONFIG or a module constant
        bound at import time from `Path.home()`. Setting HOME and patching
        CONFIG_DIR afterwards changes neither, so this read the developer's own
        ~/.iaiops/config.yaml and passed because both sides read the same file.
        """
        from iaiops.core.runtime.config import default_config_path

        monkeypatch.setenv("IAIOPS_CONFIG", str(tmp_path / "config.yaml"))
        assert default_config_path() == tmp_path / "config.yaml", "isolation is real"
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


# --- the review pass ---------------------------------------------------------
# Every test below guards a defect an adversarial review reproduced in this
# branch before it merged. They share one shape: a tool-side limit, or a gap in
# what the scan established, was being reported as a fact about the site's work.


@dataclass
class _Tag:
    ref: str
    role: str = ""


@dataclass
class _Target:
    name: str
    protocol: str
    tags: tuple = ()


@dataclass
class _Config:
    targets: tuple = ()


def _step(config, key, db, facts_extra=None):
    from iaiops.core.onboard.path import assess_path

    path = assess_path(config, db_path=db)
    return path, next(s for s in path.steps if s.key == key)


class TestTheCommandCanSatisfyItsOwnStep:
    def test_survey_names_the_command_that_stores_a_scan(self, tmp_path):
        """`scan plan` is a preview and stores nothing, so printing it as the one
        next command left a first-time site at step 1 of 6 forever: run it,
        re-run status, get the identical output."""
        _, step = _step(_Config(), "survey", tmp_path / "none.db")
        assert step.command.startswith("iaiops scan run")
        assert "scan plan" in step.detail

    def test_the_mcp_refusal_names_it_too(self, tmp_path, tools):
        """Same defect in the front end whose caller is a loop."""
        out = str(tools.onboarding_config_draft(db=str(tmp_path / "none.db")))
        assert "scan run" in out, out


class TestAToolSideFailureIsNotASiteFact:
    def test_an_unreadable_scan_store_is_not_reported_as_no_scans(self, tmp_path):
        """A corrupt store, a permission error or a `--db` typo all became "no
        scan has been stored", and the remedy offered was a live plant scan."""
        broken = tmp_path / "not-a-database.db"
        broken.write_bytes(b"this is not sqlite" * 64)
        _, step = _step(_Config(), "survey", broken)
        assert "no scan has been stored" not in step.detail
        assert "could not be read" in step.detail
        assert step.command == "", "do not send someone onto a plant network over our own error"

    def test_a_config_that_will_not_parse_is_not_reported_as_having_no_endpoints(self, tmp_path):
        broken = tmp_path / "config.yaml"
        broken.write_text("endpoints:\n  - name: e1\n   protocol: opcua\n")  # bad indent
        import os

        old = os.environ.get("IAIOPS_CONFIG")
        os.environ["IAIOPS_CONFIG"] = str(broken)
        try:
            # config=None forces gather_facts to load the file, and fail on it
            _, step = _step(None, "endpoints", tmp_path / "none.db")
        finally:
            if old is None:
                os.environ.pop("IAIOPS_CONFIG", None)
            else:
                os.environ["IAIOPS_CONFIG"] = old
        assert "no endpoints in config.yaml" not in step.detail
        assert "did not parse" in step.detail
        assert step.command == "", "drafting more into a file that will not load cannot help"

    def test_a_protocol_with_no_sampler_is_a_build_limit_not_a_missing_endpoint(self, tmp_path):
        """ "no endpoint that can be sampled on a schedule YET" was false twice:
        nothing the site does makes an MTConnect agent collectable, and the
        limit is this build's."""
        config = _Config(targets=(_Target("m1", "mtconnect", (_Tag("avail", "run_state"),)),))
        _, step = _step(config, "collect", tmp_path / "none.db")
        assert "yet" not in step.detail.lower()
        assert "a limit here, not something missing at your site" in step.detail
        assert "opcua" in step.detail, "name the protocols that DO work"


class TestTheSemanticStepIsGradedOnWhatOeeRequires:
    def test_one_optional_role_is_not_a_finished_semantic_step(self, tmp_path):
        """Graded on "did somebody type a role: anywhere", this said DONE — and
        the header then said all six steps were done on a site where
        `oee measure` refuses for want of run_state and total_count."""
        config = _Config(targets=(_Target("p1", "modbus", (_Tag("40010", "good_count"),)),))
        path, step = _step(config, "meaning", tmp_path / "none.db")
        # Not-done is the assertion; which of next/waiting it is depends on
        # whether an earlier step still holds the cursor, and that is not the bug.
        assert step.state != STATE_DONE
        assert "run_state" in step.detail and "total_count" in step.detail
        assert path.next_step is not None, "the path must not report itself finished"

    def test_both_required_roles_finish_it(self, tmp_path):
        config = _Config(
            targets=(_Target("p1", "modbus", (_Tag("1", "run_state"), _Tag("2", "total_count"))),)
        )
        _, step = _step(config, "meaning", tmp_path / "none.db")
        assert step.state == STATE_DONE

    def test_a_duplicate_role_claim_is_not_reported_as_nothing_declared(self, tmp_path):
        """`roles_present` raises on the second claim and `gather_facts` discards
        the whole endpoint's roles — so a site that HAD declared a good
        run_state was told it had declared nothing."""
        config = _Config(
            targets=(
                _Target(
                    "p1",
                    "modbus",
                    (_Tag("1", "run_state"), _Tag("2", "total_count"), _Tag("3", "total_count")),
                ),
            )
        )
        _, step = _step(config, "meaning", tmp_path / "none.db")
        assert "none declared" not in step.detail
        assert "twice" in step.detail


class TestAdviceIsDerivedFromTheSiteNotFromYamlOrder:
    def test_reordering_config_does_not_change_whether_a_command_is_offered(self, tmp_path):
        s7_first = _Config(targets=(_Target("plc", "s7"), _Target("srv", "opcua")))
        opcua_first = _Config(targets=(_Target("srv", "opcua"), _Target("plc", "s7")))
        a = _step(s7_first, "points", tmp_path / "none.db")[1]
        b = _step(opcua_first, "points", tmp_path / "none.db")[1]
        assert a.command == b.command != "", (a.command, b.command)

    @pytest.mark.parametrize("key", ["points", "collect"])
    def test_an_endpoint_name_with_a_space_still_produces_a_runnable_command(self, tmp_path, key):
        """`- name: Line 3 PLC` is legal in config.yaml — nothing validates the
        charset — and produced `iaiops collect run Line 3 PLC --duration 30m`,
        which exits 2 with "unexpected extra argument". Both commands that
        interpolate a name have to quote it, so both are checked."""
        # The points step only offers a command while the endpoint has no tags;
        # the collect step only once the required roles are declared. Different
        # site states, same name, both interpolating it into a command.
        tags = (
            ()
            if key == "points"
            else (_Tag("ns=2;i=2", "run_state"), _Tag("ns=2;i=3", "total_count"))
        )
        config = _Config(targets=(_Target("Line 3 PLC", "opcua", tags),))
        _, step = _step(config, key, tmp_path / "none.db")
        assert step.command, f"the {key} step offered no command to check"
        _resolve(step.command)


class TestTheDraftClaimsOnlyWhatTheScanEstablished:
    def test_modbus_unit_id_is_never_drafted_as_a_value(self):
        """It used to be `1` with the evidence "unit 1 answered the FC43 identity
        request" — a sentence built out of the default, which is exactly what
        DraftField refuses and this smuggled past by manufacturing the string.
        Nothing observes a unit: the probe hardcodes 1 and the reply echoes it."""
        record = _record(
            _host(
                "10.0.0.5",
                [_confirmed("modbus", 502)],
                [502],
                {"modbus": {"extra": {"unit_id": 1}}},
            )
        )
        unit = next(f for f in draft_from_scan(record).endpoints[0].fields if f.name == "unit_id")
        assert unit.value is None
        assert "echoes back" in unit.caution

    def test_a_host_confirmed_by_rejection_does_not_claim_the_request_was_answered(self):
        """The rejection path returns an EMPTY identity. The block used to say the
        device declined the FC43 request and answered it, four lines apart."""
        record = _record(
            _host(
                "10.0.0.5",
                [
                    _confirmed(
                        "modbus",
                        502,
                        "modbus_fc43:rejected",
                        "device answered in-protocol and declined",
                    )
                ],
                [502],
            )
        )
        text = render_yaml(draft_from_scan(record))
        assert "answered the FC43 identity request" not in text

    def test_a_deduced_port_says_deduced_in_the_evidence_not_only_the_caution(self):
        """`observed:` is the line the rendered header tells the reader to trust,
        so the weaker claim has to live there, not below it."""
        record = _record(_host("10.0.0.5", [_confirmed("modbus", 0)], [502]))
        port = next(f for f in draft_from_scan(record).endpoints[0].fields if f.name == "port")
        assert port.value == 502
        assert "deduced" in port.observed

    def test_the_ethernetip_slot_caution_names_the_default_that_actually_applies(self):
        """It said "0 is right for a CompactLogix", which reads as: leave the line
        commented and you get 0. TargetConfig.slot defaults to 1, so a reader who
        agreed and left it alone read the wrong module — caused by the caution."""
        from iaiops.core.runtime.config import TargetConfig

        record = _record(_host("10.0.0.8", [_confirmed("ethernetip", 44818)], [44818]))
        fields = {f.name: f for f in draft_from_scan(record).endpoints[0].fields}
        assert TargetConfig(name="x", protocol="ethernetip").slot == 1, "premise of this test"
        assert "the default is 1" in fields["slot"].caution
        assert "port" in fields, "an omitted field takes the protocol default in silence"

    def test_a_host_with_no_address_is_skipped_not_drafted_with_an_empty_host(self):
        record = _record(_host("", [_confirmed("modbus", 502)], [502]))
        draft = draft_from_scan(record)
        assert draft.endpoints == ()
        assert any("no usable address" in h.reason for h in draft.skipped)


class TestDraftedNamesAreUsable:
    def test_one_protocol_on_two_ports_of_one_host_gets_two_distinct_names(self):
        """OPC-UA is allowlisted on 4840 and 4843. Protocol+ip alone minted the
        same name twice; `get_target` returns the first match, so the second
        endpoint was unreachable by name while both were collected under one."""
        record = _record(
            _host(
                "10.0.0.9",
                [_confirmed("opcua", 4840), _confirmed("opcua", 4843)],
                [4840, 4843],
                {"opcua": {"extra": {"endpoint_count": 1}}},
            )
        )
        names = [e.name for e in draft_from_scan(record).endpoints]
        assert len(names) == len(set(names)), names

    def test_no_two_drafted_endpoints_ever_share_a_name(self):
        record = _record(
            _host(
                "10.0.0.9",
                [_confirmed("opcua", 4840), _confirmed("opcua", 4843)],
                [4840, 4843],
                {"opcua": {"extra": {"endpoint_count": 1}}},
            ),
            _host(
                "10.0.0.10",
                [_confirmed("mtconnect", 5000), _confirmed("mtconnect", 8080)],
                [5000, 8080],
                {"mtconnect": {"extra": {"device_count": 1, "devices": ["VMC-1"]}}},
            ),
            _host("10.0.0.11", [_confirmed("modbus", 502)], [502]),
        )
        names = [e.name for e in draft_from_scan(record).endpoints]
        assert len(names) == len(set(names)), names


class TestTheRecordShapeIsUntrusted:
    """`load_scan` does a bare `json.loads` on a sqlite column, so the shape is
    whatever was written. These all used to escape as raw tracebacks —
    AttributeError and TypeError are not in the CLI's handled set."""

    @pytest.mark.parametrize(
        "hosts",
        [
            [None],
            ["10.0.0.1"],
            [
                {
                    "ip": "10.0.0.1",
                    "identity": ["not", "a", "dict"],
                    "protocols": [_confirmed("modbus", 502)],
                    "open_ports": [502],
                }
            ],
            [
                {
                    "ip": "10.0.0.1",
                    "identity": "nope",
                    "protocols": [_confirmed("modbus", 502)],
                    "open_ports": [502],
                }
            ],
            [
                {
                    "ip": "10.0.0.1",
                    "protocols": [
                        {
                            "protocol": "modbus",
                            "confidence": "confirmed",
                            "port": "abc",
                            "evidence": "e",
                            "detail": "",
                        }
                    ],
                    "open_ports": [502],
                }
            ],
            [
                {
                    "ip": "10.0.0.1",
                    "protocols": [_confirmed("modbus", 0)],
                    "open_ports": ["x", None, 1.5],
                }
            ],
            [
                {
                    "ip": "10.0.0.1",
                    "protocols": [_confirmed("mtconnect", 5000)],
                    "open_ports": [5000],
                    "identity": {"mtconnect": {"extra": {"devices": 7, "device_count": "many"}}},
                }
            ],
            [
                {
                    "ip": "10.0.0.1",
                    "protocols": [_confirmed("mtconnect", 5000)],
                    "open_ports": [5000],
                    "identity": {"mtconnect": {"extra": {"devices": "abc"}}},
                }
            ],
        ],
    )
    def test_a_malformed_row_never_raises_and_never_invents(self, hosts):
        draft = draft_from_scan({"scan_id": "s", "hosts": hosts})
        text = render_yaml(draft)
        parsed = yaml.safe_load(text)
        for entry in (parsed or {}).get("endpoints", []):
            assert entry.get("host") != "", entry
            assert "port" not in entry or isinstance(entry["port"], int)

    def test_a_string_of_device_names_is_not_three_devices(self):
        record = _record(
            _host(
                "10.0.0.1",
                [_confirmed("mtconnect", 5000)],
                [5000],
                {"mtconnect": {"extra": {"devices": "abc"}}},
            )
        )
        device = next(f for f in draft_from_scan(record).endpoints[0].fields if f.name == "device")
        assert device.value is None


class TestTheRenderedBlockAlwaysParses:
    @pytest.mark.parametrize("code", [0x00, 0x07, 0x0A, 0x0D, 0x1B, 0x7F, 0x85, 0x2028])
    def test_a_control_character_from_a_device_cannot_break_the_yaml(self, code):
        """`_scalar` escaped only \\ and " — 30 control characters made the block
        UNPARSEABLE and three more folded to a space and changed the value. The
        function whose whole job is YAML safety must not lean on its callers."""
        name = f"VMC{chr(code)}1"
        record = _record(
            _host(
                "10.0.0.1",
                [_confirmed("mtconnect", 5000)],
                [5000],
                {"mtconnect": {"extra": {"device_count": 1, "devices": [name]}}},
            )
        )
        parsed = yaml.safe_load(render_yaml(draft_from_scan(record)))
        assert parsed["endpoints"][0]["device"] == name

    def test_a_device_name_cannot_inject_a_second_mapping_key(self):
        hostile = 'VMC"\n  - name: "pwned'
        record = _record(
            _host(
                "10.0.0.1",
                [_confirmed("mtconnect", 5000)],
                [5000],
                {"mtconnect": {"extra": {"device_count": 1, "devices": [hostile]}}},
            )
        )
        parsed = yaml.safe_load(render_yaml(draft_from_scan(record)))
        assert len(parsed["endpoints"]) == 1
        assert parsed["endpoints"][0]["device"] == hostile


def test_a_renamed_endpoint_is_still_recognised_as_already_configured():
    """The draft's own header says "rename this". Matching on the generated name
    alone meant the already-configured guard worked exactly once: rename it, and
    the next scan re-offered the same device, so the site configured it twice."""
    from iaiops.core.onboard.config_state import endpoint_address

    record = _record(
        _host(
            "10.0.0.9",
            [_confirmed("opcua", 4840)],
            [4840],
            {"opcua": {"extra": {"endpoint_count": 1}}},
        )
    )
    by_name_only = draft_from_scan(record, existing_names=("filler-line-3",))
    assert by_name_only.pastable, "premise: the renamed name does not match"

    class _Tgt:
        name = "filler-line-3"
        protocol = "opcua"
        endpoint_url = "opc.tcp://10.0.0.9:4840/"
        host = ""
        agent_url = ""

    draft = draft_from_scan(
        record, existing_names=("filler-line-3",), existing_addresses=(endpoint_address(_Tgt()),)
    )
    assert draft.endpoints[0].already_configured
    assert draft.pastable == ()
