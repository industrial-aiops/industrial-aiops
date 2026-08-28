"""Every `iaiops ...` command the READMEs teach has to exist.

Both READMEs ship inside the wheel, so a command that does not exist is not a
typo — it is the product telling a customer to run something that will fail. The
zh README taught `iaiops modbus detect-byte-order` for several releases;
`modbus_detect_byte_order` exists, but **only as an MCP tool**. Same shape as
every gap found this week — a capability with one front end, documented as if it
had both — just pointing the other way.

Nothing checked it, so this does. It resolves the command through Typer rather
than by grepping the source: a command that is defined but never registered would
pass a grep and still fail for the reader.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

READMES = ("README.md", "README.zh-CN.md")

#: Shell blocks only. Prose starting a line with "iaiops is designed ..." is a
#: sentence, not an invocation — the first version of this test reported it as a
#: missing command, which is the way a guard like this loses its credibility.
_SHELL_BLOCK = re.compile(r"```(?:bash|sh|console|shell)\n(.*?)```", re.DOTALL)

#: `iaiops <group> <command>` at the start of a line. Two words only: a
#: single-word invocation is a top-level command or a group's help.
_INVOCATION = re.compile(r"^iaiops ([a-z][a-z0-9-]*) ([a-z][a-z0-9-]*)", re.MULTILINE)

#: Words that follow `iaiops <group>` in the docs without being subcommands.
_NOT_COMMANDS = {"--help", "--version"}


def _root():
    return Path(__file__).resolve().parents[1]


def _documented() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for name in READMES:
        text = (_root() / name).read_text("utf-8")
        for block in _SHELL_BLOCK.findall(text):
            found |= {(g, c) for g, c in _INVOCATION.findall(block) if c not in _NOT_COMMANDS}
    return found


def _registered() -> set[tuple[str, str]]:
    """Every (group, command) the CLI actually exposes, straight from Typer."""
    from iaiops.cli._root import app

    pairs: set[tuple[str, str]] = set()
    top = {c.name for c in app.registered_commands if c.name}
    for group in app.registered_groups:
        if not group.name:
            continue
        for command in group.typer_instance.registered_commands:
            if command.name:
                pairs.add((group.name, command.name))
    # `iaiops readiness --json` style: a top-level command followed by a flag is
    # matched by the regex too, so allow (top-level, anything).
    pairs |= {(name, "*") for name in top}
    return pairs


def test_every_documented_command_exists():
    registered = _registered()
    top_level = {g for g, c in registered if c == "*"}
    missing = sorted(
        f"iaiops {g} {c}"
        for g, c in _documented()
        if g not in top_level and (g, c) not in registered
    )
    assert not missing, (
        "The READMEs teach commands that do not exist. Both ship inside the "
        "wheel, so this is what a customer is told to run:\n  " + "\n  ".join(missing)
    )


def test_the_check_can_actually_fail():
    """A finder that matched nothing would pass the test above forever."""
    assert len(_documented()) > 20, _documented()


def test_a_known_good_command_is_seen_by_both_halves():
    assert ("investigate", "plan") in _documented()
    assert ("investigate", "plan") in _registered()
