"""iaiops writes VALUES, never PLC LOGIC — a promise pinned by a test, not a slogan.

Field engineers' distrust of AI is about logic: generated ladder that does not
work, wrong compatibility claims. iaiops has no tool that downloads, uploads,
flashes or edits a PLC program; its program tools read an EXPORTED file. Its only
state-changing tools are ten MOC-gated value writes (setpoints, tags, registers,
properties, a state change). This file fails the day either stops being true, so
the claim in the README and the decks cannot drift away from the code.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.unit

#: The reviewed value writes. Adding a write tool means adding it HERE, in a
#: reviewed change that argues it writes a value and not logic.
VALUE_WRITE_TOOLS = frozenset(
    {
        "bacnet_write_property",
        "bas_command",
        "eip_write_tag",
        "ethercat_set_state",
        "ethercat_write_sdo",
        "fins_write_words",
        "mc_write_words",
        "mqtt_publish",
        "profinet_dcp_set",
        "s7_write_db",
    }
)

_LOGIC_TRANSFER = re.compile(
    r"(download|upload_program|program_(write|download|upload)|write_program|"
    r"flash|firmware_(write|update)|ladder_write|logic_write)",
    re.IGNORECASE,
)
#: In a description, "download" alone is not logic: CoE "SDO download" writes ONE
#: object-dictionary value (ethercat_write_sdo). Logic transfer names what moves.
_LOGIC_TRANSFER_TEXT = re.compile(
    r"(program|logic|ladder|firmware|project)\W+(download|upload|transfer|flash)"
    r"|(download|upload|flash)\w*\W+(the\s+|a\s+)?(program|logic|ladder|firmware|project)",
    re.IGNORECASE,
)
_LOGIC_PARAMS = {"program", "source", "l5x", "project", "ladder", "logic", "firmware"}


def _fn(tool):
    return getattr(tool, "fn", tool)


def test_the_only_state_changing_tools_are_the_reviewed_value_writes(full_tool_registry):
    writes = {
        name
        for name, tool in full_tool_registry.items()
        if getattr(_fn(tool), "_risk_level", "") in ("high", "critical")
    }
    assert writes == VALUE_WRITE_TOOLS, (
        f"new or removed write tools: +{sorted(writes - VALUE_WRITE_TOOLS)} "
        f"-{sorted(VALUE_WRITE_TOOLS - writes)} — review that each writes a value, not logic"
    )


def test_no_tool_transfers_plc_logic(full_tool_registry):
    offenders = [
        name
        for name, tool in full_tool_registry.items()
        if _LOGIC_TRANSFER.search(name) or _LOGIC_TRANSFER_TEXT.search(tool.description or "")
    ]
    assert not offenders, f"tools that look like they move PLC logic: {offenders}"


def test_value_writes_take_no_program_content(full_tool_registry):
    import inspect

    for name in VALUE_WRITE_TOOLS:
        params = set(inspect.signature(_fn(full_tool_registry[name])).parameters)
        assert not params & _LOGIC_PARAMS, f"{name} takes {sorted(params & _LOGIC_PARAMS)}"


def test_program_tools_only_read_exported_files(full_tool_registry):
    program_tools = {n: t for n, t in full_tool_registry.items() if n.startswith("plc_program_")}
    assert program_tools, "the plc_program_* tools disappeared — update this test deliberately"
    for name, tool in program_tools.items():
        assert getattr(_fn(tool), "_risk_level", "") == "low", name
        assert (tool.description or "").startswith("[READ]"), name
